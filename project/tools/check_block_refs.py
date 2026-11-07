"""块号引用校验（S1-3）：README 分区表的块号 vs 转录文件里的折叠区域

**为什么需要**：2026-11-07 在分类段插入 28 块后，发布段整体后移，
而 README 的「画布分区细节」整张表还停在旧编号（分类选择 056–102 实为 056–130）。
`check_truth_source.py` 只校验**总块数**，「154–157」这种区间不会超过 185，永远查不出来。

**做法**：不靠数字，靠**名字**。画布有「折叠区域名称」，README 表里也有区段名，
用名字对齐后比较起止块号——名字是语义，数字是位置，位置会漂，名字不会。

用法:
    python check_block_refs.py
    python check_block_refs.py --transcript <md> --readme <md>

退出码: 0 一致（或无可校验项）· 1 存在不一致 · 2 文件读不了
"""

import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT = ROOT / "project" / "modules" / "咸鱼_批量上架.md"
README = ROOT / "README.md"
SECTION = "## 画布分区细节"

REGION_BEGIN_RE = re.compile(r"^(\d{3})\s+折叠开始\s+折叠区域名称=(?P<name>\S+)")
REGION_END_RE = re.compile(r"^(\d{3})\s+折叠结束")
ROW_RE = re.compile(r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<a>\d{3})(?:\s*[–\-—~～]\s*(?P<b>\d{3}))?\s*\|")


def parse_regions(path: Path) -> dict:
    """转录 → {区域名: (起始块号, 结束块号)}。用栈支持嵌套。"""
    stack, regions = [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = REGION_BEGIN_RE.match(line)
        if m:
            stack.append((m["name"], int(line[:3])))
            continue
        m = REGION_END_RE.match(line)
        if m and stack:
            name, start = stack.pop()
            regions[name] = (start, int(line[:3]))
    return regions


def parse_readme_rows(path: Path) -> list:
    """README 分区表 → [(区段名, 起, 止)]。止为 None 表示单块。"""
    rows, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(SECTION):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if not inside:
            continue
        m = ROW_RE.match(line)
        if not m or m["name"] in ("区段", "------"):
            continue
        rows.append((m["name"], int(m["a"]), int(m["b"]) if m["b"] else None))
    return rows


def compare(regions: dict, rows: list, total_blocks: int) -> tuple:
    """返回 (checks, problems)。checks=[(状态, 名称, 声明, 实际)]。"""
    checks, problems = [], []
    for name, a, b in rows:
        if name in regions:
            actual = regions[name]
            declared = (a, b if b is not None else a)
            ok = declared == actual
            checks.append(("✓" if ok else "✗", name, declared, actual))
            if not ok:
                problems.append(f"「{name}」README 写 {declared[0]:03d}–{declared[1]:03d}，"
                                f"画布实际 {actual[0]:03d}–{actual[1]:03d}"
                                f"（起 {actual[0] - declared[0]:+d}，止 {actual[1] - declared[1]:+d}）")
        elif b is None:
            ok = a <= total_blocks
            checks.append(("·", name, (a, None), ("单块",)))
            if not ok:
                problems.append(f"「{name}」指向块 {a:03d}，但画布只有 {total_blocks} 块")
        else:
            checks.append(("·", name, (a, b), ("非折叠区域，跳过",)))
    return checks, problems


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="README 块号引用 vs 转录折叠区域")
    ap.add_argument("--transcript", default=str(TRANSCRIPT))
    ap.add_argument("--readme", default=str(README))
    a = ap.parse_args()

    tpath, rpath = Path(a.transcript), Path(a.readme)
    for p in (tpath, rpath):
        if not p.exists():
            print(f"[!] 文件不存在：{p}")
            return 2

    regions = parse_regions(tpath)
    rows = parse_readme_rows(rpath)
    total = sum(1 for line in tpath.read_text(encoding="utf-8").splitlines() if line[:3].isdigit())

    if not regions:
        print(f"[!] 转录里没找到折叠区域：{tpath}")
        return 2
    if not rows:
        print(f"[!] README 里没找到分区表：{rpath}")
        return 2

    checks, problems = compare(regions, rows, total)
    for mark, name, declared, actual in checks:
        if mark == "·":
            print(f"  · {name:8} {declared[0]:03d}" + (f"–{declared[1]:03d}" if declared[1] else "")
                  + f"  {actual[0]}")
        else:
            print(f"  {mark} {name:8} 声明 {declared[0]:03d}–{declared[1]:03d}  实际 {actual[0]:03d}–{actual[1]:03d}")

    checked = sum(1 for c in checks if c[0] in "✓✗")
    print()
    if problems:
        print(f"[FAIL] {len(problems)} 处不一致（已校验 {checked} 个折叠区域 / 共 {total} 块）:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"[OK] {checked} 个折叠区域的块号与 README 一致（画布共 {total} 块）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
