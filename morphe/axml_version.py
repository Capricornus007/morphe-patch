#!/usr/bin/env python3
"""讀出 APK 的 versionName / versionCode（解析 binary AndroidManifest.xml）。

用法:
  axml_version.py <apk>                 # 印 "versionName versionCode"
  axml_version.py <apk> --name-only     # 只印 versionName

versionCode 是 manifest 元素的 typed value（dtype 0x10），不在 string pool；
START_ELEMENT 屬性基址 = chunk_pos + headerSize(16) + attributeStart。
"""
import struct
import sys
import zipfile


def load_manifest_bytes(path):
    """APK 直接讀；.apkm/.xapk（zip 合集）取其中 base.apk 的 manifest。"""
    if path.endswith(('.apkm', '.xapk')):
        z = zipfile.ZipFile(path)
        names = z.namelist()
        base = 'base.apk' if 'base.apk' in names else next(
            (n for n in names if n.endswith('.apk')), None)
        if base is None:
            raise SystemExit('no .apk inside bundle')
        inner = zipfile.ZipFile(z.open(base))
        return inner.read('AndroidManifest.xml')
    return zipfile.ZipFile(path).read('AndroidManifest.xml')


def manifest_attrs(apk_path):
    data = load_manifest_bytes(apk_path)
    # 檔頭（RES_XML_TYPE 0x0003）本身佔 8 bytes；string pool 緊隨其後
    t, hsize, _size = struct.unpack_from('<HHI', data, 0)
    assert t == 0x0003, 'not AXML'
    off = hsize
    t, hs, sz = struct.unpack_from('<HHI', data, off)
    assert t == 0x0001, 'first chunk is not string pool'
    sc, _styc, _flags, sstart, _ = struct.unpack_from('<IIIII', data, off + 8)
    op = off + hs
    sd = off + sstart
    strs = []
    for i in range(sc):
        soff = struct.unpack_from('<I', data, op + i * 4)[0]
        p = sd + soff
        first = struct.unpack_from('<H', data, p)[0]
        if first & 0x8000:
            ln = ((first & 0x7FFF) << 16) | struct.unpack_from('<H', data, p + 2)[0]
            hdr = 4
        else:
            ln = first
            hdr = 2
        strs.append(data[p + hdr:p + hdr + ln * 2].decode('utf-16-le', 'replace'))
    pos = off + sz
    while pos < len(data) - 8:
        t, hs, sz = struct.unpack_from('<HHI', data, pos)
        if t == 0x0102:  # START_ELEMENT (<manifest>)
            astart, asize, acount = struct.unpack_from('<HHH', data, pos + 24)
            base = pos + 16 + astart
            out = {}
            for i in range(acount):
                a = base + i * asize
                _ns, aname, _raw, _vsz, _res0, dtype, dval = struct.unpack_from('<IIIHBBI', data, a)
                nm = strs[aname] if aname < len(strs) else '?'
                val = strs[dval] if dtype == 3 and dval < len(strs) else dval
                out[nm] = val
            return out
        pos += sz
    raise SystemExit('no START_ELEMENT found')


def main():
    apk = sys.argv[1]
    attrs = manifest_attrs(apk)
    if '--name-only' in sys.argv:
        print(attrs['versionName'])
    else:
        print(attrs['versionName'], attrs['versionCode'])


if __name__ == '__main__':
    main()
