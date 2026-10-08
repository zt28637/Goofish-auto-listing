"""从影刀编辑器 DLL 提取内置指令中文目录（离线，不开编辑器不查 wiki）

ShadowBot.Runtime.Development.dll 内嵌 UTF-8 JSON `"blocks": [...]`（按分类分段），
每块含 name(机器ID)/title(画布中文名)/inputs[].name→label(参数面板中文标签)。
DLL 里存了 英文/繁体/简体 三份副本：用 GB2312 编码判定取简体（编不进=繁体）。
市场/自定义模块（xbot_extensions.*）的元数据在明文解包目录
`AppData/Local/ShadowBot/users/<uid>/apps/<appUuid>/xbot_extensions/<模块>/prototype.block.json`，
一并合并进目录。

产出 project/tools/sb_blocks_zh.json：
  {"titles": {name: title}, "labels": {name: {input_name: label}}}

用法：python extract_sb_catalog.py
"""

import glob
import json
import os
import re
import sys

DLLS = [
    r"E:\Agent\RPA\shadowbot-6.3.22\ShadowBot.Runtime.Development.dll",
    r"E:\Agent\RPA\shadowbot-6.3.21\ShadowBot.Runtime.Development.dll",
    r"E:\Agent\RPA\shadowbot-6.3.13\ShadowBot.Runtime.Development.dll",
]
EXT_GLOBS = [
    r"C:\Users\Admin\AppData\Local\ShadowBot\users\*\apps\*\xbot_extensions\*\prototype.block.json",
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sb_blocks_zh.json")


def extract_arrays(data: bytes) -> list:
    """定位每个 "blocks":[ 起点，括号配对抠出完整 JSON 数组。"""
    arrays = []
    for m in re.finditer(rb'"blocks"\s*:\s*\[', data):
        start = data.index(b"[", m.start())
        depth, i, in_str, esc = 0, start, False, False
        while i < len(data):
            c = data[i:i + 1]
            if in_str:
                if esc:
                    esc = False
                elif c == b"\\":
                    esc = True
                elif c == b'"':
                    in_str = False
            else:
                if c == b'"':
                    in_str = True
                elif c == b"[":
                    depth += 1
                elif c == b"]":
                    depth -= 1
                    if depth == 0:
                        break
            i += 1
        try:
            arrays.append(json.loads(data[start:i + 1].decode("utf-8")))
        except Exception:
            pass
    return arrays


def locale_of(arr) -> str:
    """en / zh-CN / zh-TW：按块 title 的非 ASCII 字符判定。"""
    for b in arr:
        t = b.get("title") or ""
        if any(ord(ch) > 0x7F for ch in t):
            try:
                t.encode("gb2312")
                return "zh-CN"
            except UnicodeEncodeError:
                return "zh-TW"
    return "en"


def harvest(arrs: list, titles: dict, labels: dict) -> None:
    for arr in arrs:
        for b in arr:
            name = b.get("name")
            if not name:
                continue
            if b.get("title"):
                titles.setdefault(name, b["title"])
            lb = {}
            for inp in b.get("inputs") or []:
                if inp.get("name") and inp.get("label"):
                    lb[inp["name"]] = inp["label"]
            if lb:
                labels.setdefault(name, {}).update(lb)


def merge_tiered(tiers: list, titles: dict, labels: dict) -> None:
    """按 简体→繁体→英文 优先级、以 name 整块补缺（不逐字段混语言）。"""
    for t2, l2 in tiers:
        for name, title in t2.items():
            titles.setdefault(name, title)
        for name, lb in l2.items():
            labels.setdefault(name, lb)


def main() -> None:
    titles, labels = {}, {}
    dll_used = None
    for dll in DLLS:
        if not os.path.exists(dll):
            continue
        data = open(dll, "rb").read()
        arrs = extract_arrays(data)
        by_locale = {}
        for arr in arrs:
            by_locale.setdefault(locale_of(arr), []).append(arr)
        tiers = []
        for loc in ("zh-CN", "zh-TW", "en"):
            t2, l2 = {}, {}
            harvest(by_locale.get(loc, []), t2, l2)
            tiers.append((t2, l2))
        merge_tiered(tiers, titles, labels)
        dll_used = dll
        print(f"[dll] {dll}")
        print(f"[dll] 段数={len(arrs)} 分布={ {k: len(v) for k, v in by_locale.items()} }")
        print(f"[dll] 简体 name={len(tiers[0][0])}")
        break
    if not dll_used:
        sys.exit("未找到编辑器 DLL，检查 DLLS 路径")

    n_builtin = len(titles)

    # 市场/自定义模块（明文解包目录；文件本身是简体环境下载，直接合并）
    n_ext = 0
    for pat in EXT_GLOBS:
        for f in glob.glob(pat):
            try:
                obj = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            blocks = obj.get("blocks") if isinstance(obj, dict) else (obj if isinstance(obj, list) else None)
            if isinstance(blocks, list):
                before = len(titles)
                harvest([blocks], titles, labels)
                n_ext += len(titles) - before

    out = {"titles": titles, "labels": labels}
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"[OK] 内置 {n_builtin} + 扩展 {n_ext} = {len(titles)} 个指令名；{len(labels)} 个有参数标签 → {OUT}")


if __name__ == "__main__":
    main()
