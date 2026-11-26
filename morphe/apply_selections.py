#!/usr/bin/env python3
"""把 Morphe Manager 匯出的 selections JSON 套用到 options-create 產生的 options 檔。

用法: apply_selections.py <export.json> <options.json> <package> [<options.json> <package> ...]
每組 options.json + package 對應一個要修補的 app。
"""
import json, os, re, sys

_ALIAS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'piko_patch_aliases.json')
try:
    with open(_ALIAS_PATH) as _f:
        _ALIASES = json.load(_f)
except Exception:
    _ALIASES = {}

def load_export(path):
    with open(path) as f:
        return json.load(f)

def decode_value(v):
    # Manager 把 option 值 JSON 編碼後再嵌進匯出檔，解一層
    try:
        return json.loads(v)
    except Exception:
        return v

def canonical(name):
    """把舊補丁源的 patch 名歸一化到新版名字。

    piko-newx 已歸檔，補丁源換成 crimera/piko 主倉（Capricornus007/piko fork），
    舊 export.json 的 'NewX: xxx' 名字在新版全對不上（morphe #56：52 個 patch
    一個都沒匹配到 → 整個 Piko bundle 被跳過 → X 12.46.1 只補到 Morphe/X-Shim）。
    """
    if name in _ALIASES:
        return _ALIASES[name]
    # 未在表內的 'NewX: xxx' 退而求其次剝前綴（新版多數補丁已去前綴）。
    return re.sub(r'^NewX:\s*', '', name)

def canonical_list(names):
    return [canonical(n) for n in names]

def bundle_matches(bundle_patches, selected):
    if not selected:
        return 0
    # 的名字兩側都歸一化，舊 'NewX: xxx' 能配上新版 'xxx'。
    return sum(1 for p in canonical_list(selected) if p in bundle_patches)

def source_hint(name):
    """從 bundleName 推測其補丁源關鍵詞，供 patch 名匹配失敗時兜底。"""
    n = name.lower()
    if 'piko' in n or 'newx' in n:
        return 'piko'
    if 'morphe' in n:
        return 'morphe'
    if 'shim' in n or 'x shim' in n:
        return 'shim'
    return None

def bundle_source_matches(ob, name):
    """patch 名全對不上時，用 options bundle 的 meta.source 認源。

    options-create 產生的 bundle meta.source 形如
    'v3.11.10__patches-3.11.10.mpp'（Capricornus007/piko），
    'v1.7.0__patches-1.7.0.mpp'（inotia00/x-shim）等，含倉庫/包名關鍵詞。
    """
    hint = source_hint(name)
    if not hint:
        return False
    src = str((ob.get('meta') or {}).get('source') or '').lower()
    return hint in src


def apply(export, options_path, package):
    with open(options_path) as f:
        bundles = json.load(f)
    # 收集匯出檔裡這個 package 的所有 bundle 選擇
    wanted = []  # (bundleName, [patches], {patch: {opt: val}})
    for b in export.get('bundles') or []:
        sel = (b.get('selections') or {}).get(package)
        if not sel:
            continue
        opts = (b.get('options') or {}).get(package, {}) or {}
        wanted.append((b.get('bundleName', '?'), sel, opts))
    if not wanted:
        print('!! 匯出檔裡沒有 %s 的選擇' % package)
        return 1
    used = set()
    missing_total = []
    for name, sel, opts in wanted:
        # 找包含最多所選 patch 的 options bundle
        best_i, best_score = None, 0
        for i, ob in enumerate(bundles):
            if i in used:
                continue
            score = bundle_matches(ob['patches'], sel)
            if score > best_score:
                best_i, best_score = i, score
        # 換源後 patch 名可能全部對不上（score=0），改用 meta.source 認出
        # 同一個補丁源的 bundle（Piko ↔ ...piko...），避免整個 bundle 跳過。
        if (best_i is None or best_score == 0):
            for i, ob in enumerate(bundles):
                if i in used:
                    continue
                if bundle_source_matches(ob, name):
                    best_i, best_score = i, -1  # -1 = 靠 source 兜底找到
                    break
        if best_i is None or best_score == 0:
            print('!! 找不到對應的 options bundle（%s，%d 個 patch）' % (name, len(sel)))
            missing_total.extend(sel)
            continue
        used.add(best_i)
        ob = bundles[best_i]
        if best_score == -1:
            print('== %s: patch 名全對不上，用 meta.source 兜底認源' % name)
        sel_set = set(canonical_list(sel))
        # 先全部關掉，再開所選的（匯出檔是完整選擇）
        for pname, pdata in ob['patches'].items():
            pdata['enabled'] = pname in sel_set
        # 套 option 值（舊名先歸一到新版）
        for pname, popts in opts.items():
            cname = canonical(pname)
            if cname not in ob['patches']:
                print('!! option 對應的 patch 不存在: %s' % pname)
                continue
            tgt = ob['patches'][cname].setdefault('options', {})
            for k, v in popts.items():
                tgt[k] = decode_value(v)
        # 用歸一化後的名字判斷缺失，避免舊名造成假 missing
        canon_sel = canonical_list(sel)
        missing = [p for p in canon_sel if p not in ob['patches']]
        if missing:
            print('!! %s: %d 個所選 patch 在最新版不存在: %s' % (name, len(missing), ', '.join(missing)))
            missing_total.extend(missing)
        applied = len(sel) - len(missing)
        print('== %s -> bundle[%d] %s: 開 %d/%d 個 patch' % (name, best_i, ob['meta'].get('source'), applied, len(sel)))
    with open(options_path, 'w') as f:
        json.dump(bundles, f, indent=2, ensure_ascii=False)
    if missing_total:
        print('!! 共 %d 個 patch 未套用' % len(missing_total))
    return 0

def main():
    args = sys.argv[1:]
    export = load_export(args[0])
    rc = 0
    i = 1
    while i < len(args):
        options_path, package = args[i], args[i + 1]
        rc |= apply(export, options_path, package)
        i += 2
    sys.exit(rc)

if __name__ == '__main__':
    main()
