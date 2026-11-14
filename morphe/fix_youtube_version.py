#!/usr/bin/env python3
"""把 YouTube APK 的 versionName 從「X.Y.Z-BETA」改成純數字「X.Y.Z」。

版本號自動偵測：掃 AndroidManifest.xml 字串池，任何 ^\\d+(\\.\\d+)+-BETA$
字串都原地去掉 -BETA 後綴（新字串較短，原地覆寫並更新 length 欄位，
其餘字串 offset 不受影響）——以後換新版 APK 不用改腳本。

用法: fix_youtube_version.py <src.apk> <dst.apk>
（沿革：21.46.520-BETA → 21.46.520；本次 21.46.522-BETA → 21.46.522）
"""
import zipfile, struct, sys, re

PAT = re.compile(r'^\d+(\.\d+)+-BETA$')

def main():
    src, dst = sys.argv[1], sys.argv[2]
    with zipfile.ZipFile(src) as z:
        data = bytearray(z.read('AndroidManifest.xml'))

    type_, hsize, size = struct.unpack_from('<HHI', data, 0)
    assert type_ == 0x0003
    off = hsize
    type_, hsize2, size2 = struct.unpack_from('<HHI', data, off)
    assert type_ == 0x0001, 'first chunk is not string pool'
    stringCount, styleCount, flags, stringsStart, stylesStart = struct.unpack_from('<IIIII', data, off + 8)
    assert not (flags & 0x100), 'expected UTF-16 string pool'
    offsets_pos = off + hsize2
    string_data_pos = off + stringsStart

    def read_u16_string(pos):
        first = struct.unpack_from('<H', data, pos)[0]
        if first & 0x8000:
            length = ((first & 0x7FFF) << 16) | struct.unpack_from('<H', data, pos + 2)[0]
            hdr = 4
        else:
            length = first
            hdr = 2
        raw = data[pos + hdr: pos + hdr + length * 2]
        return length, hdr, raw.decode('utf-16-le')

    replaced = 0
    for i in range(stringCount):
        soff = struct.unpack_from('<I', data, offsets_pos + i * 4)[0]
        pos = string_data_pos + soff
        length, hdr, s = read_u16_string(pos)
        if PAT.match(s):
            new = s[:-len('-BETA')]
            new_bytes = new.encode('utf-16-le')
            struct.pack_into('<H', data, pos, len(new))
            data[pos + 2: pos + 2 + len(new_bytes)] = new_bytes
            struct.pack_into('<H', data, pos + 2 + len(new_bytes), 0)
            replaced += 1
            print('replaced %r -> %r (string #%d, pool offset %d)' % (s, new, i, soff))

    print('total replaced:', replaced)
    assert replaced >= 1, 'versionName string matching X.Y.Z-BETA not found'

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            buf = zin.read(item.filename)
            if item.filename == 'AndroidManifest.xml':
                buf = bytes(data)
            zout.writestr(item, buf)
    print('written:', dst)

if __name__ == '__main__':
    main()
