"""对账（S3-4 / O2a）：把「上架中」残留变成一张人工核对清单，再按人的裁决回填

**为什么需要**：崩溃会留下 `N 列 = 上架中`，而这时**本地无法判断到底发出去没有**：

    155 写「上架中」→ 156 保存 → 157 点发布 → … → 164/170/174 回写结果

- 崩在 155→157 之间：**确定没发**
- 崩在 157 之后：「大概率已发」，但"点了"≠"发成功"（校验拦截/网络/风控都能让它无效）

判定依据不在本地（闲鱼没有可查询的接口，「我的发布」页是唯一真值，需要登录）。
所以本工具**只做三件事**：列清单、按人的裁决回填、把结果记进台账。

**红线**：
1. 脚本**永远不自动判定**结果 —— 只按 `--set` 的输入回填
2. 「上架中」**不会被自动改回「待上架」** —— 那是重发的开关，必须人工按

用法:
    python reconcile.py                        # 生成核对清单（runtime/data/reconcile/）
    python reconcile.py --set 4=已发布          # 回填：N=上架成功 + 台账 confirm
    python reconcile.py --set 4=未发布 --set 5=已发布
"""

import argparse
import datetime
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "project" / "runtime" / "商品清单.xlsx"
OUT_DIR = ROOT / "project" / "runtime" / "data" / "reconcile"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ledger

COL_ID, COL_CAT, COL_PRICE, COL_DIR, COL_DESC, COL_STATUS = 0, 3, 6, 11, 12, 13
STUCK = "上架中"
VERDICT_YES, VERDICT_NO = "已发布", "未发布"
RESULT_OF = {VERDICT_YES: "上架成功", VERDICT_NO: "待上架"}


def collect(xlsx: Path) -> list:
    """Excel 里所有停在「上架中」的行，附带台账状态。"""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for i, vals in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        get = lambda n: (str(vals[n]).strip() if n < len(vals) and vals[n] is not None else "")
        if get(COL_STATUS) != STUCK:
            continue
        pid = get(COL_ID)
        rows.append({
            "row": i, "pid": pid, "cat": get(COL_CAT), "price": get(COL_PRICE),
            "desc": get(COL_DESC)[:40], "dir": get(COL_DIR),
            "first_image": (ledger.first_image(get(COL_DIR)).name
                            if ledger.first_image(get(COL_DIR)) else "—"),
            "ledger": ledger.current_state(pid) or "无记录",
        })
    return rows


def write_checklist(rows: list) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}"
    path = OUT_DIR / f"{ts}.md"
    lines = [
        "# 上架待核对清单",
        "",
        f"> 生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · 共 **{len(rows)}** 条",
        "> 去闲鱼「我的发布」逐一核对，然后按下表回填：",
        "> `python project/tools/reconcile.py --set <行>=" + VERDICT_YES + "` 或 `--set <行>=" + VERDICT_NO + "`",
        "",
        "| 行 | 商品ID | 描述前 40 字 | 价格 | 首图 | 台账 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['row']} | {r['pid']} | {r['desc']} | {r['price']} | {r['first_image']} | {r['ledger']} |")
    lines += [
        "",
        "## 判定提示",
        "",
        "- 崩在「写『上架中』→ 点发布」之间 = **确定没发**，可直接 `未发布`",
        "- 崩在点发布之后 = **大概率已发**，但发布可能被校验/网络/风控拦下，必须去页面确认",
        "- 拿不准就填 `未发布` 之前先看闲鱼——**宁可多花一分钟，不要重复上架**",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def apply(sets: dict, xlsx: Path) -> int:
    """按 {行号: 已发布/未发布} 回填 Excel 与台账。"""
    import openpyxl

    bad = {k: v for k, v in sets.items() if v not in RESULT_OF}
    if bad:
        print(f"[!] 无法识别的裁决：{bad}（只接受 {VERDICT_YES} / {VERDICT_NO}）")
        return 2

    try:
        wb = openpyxl.load_workbook(xlsx)
    except PermissionError:
        print("[!] 清单被占用（WPS/Excel 开着的？），先关掉再回填")
        return 2
    ws = wb.active

    done = []
    for row, verdict in sorted(sets.items()):
        pid = ws.cell(row, COL_ID + 1).value
        pid = "" if pid is None else str(pid).strip()
        cur = ws.cell(row, COL_STATUS + 1).value
        if str(cur).strip() != STUCK:
            print(f"[跳过] 第 {row} 行当前是 {cur!r}，不是「{STUCK}」")
            continue
        ws.cell(row, COL_STATUS + 1).value = RESULT_OF[verdict]
        if verdict == VERDICT_YES:
            ledger.confirm(pid, "上架成功", cover=ledger.cover_hash(ws.cell(row, COL_DIR + 1).value))
        else:
            ledger.release(pid, note="reconcile: 人工核对未发布")
        done.append((row, pid, verdict))

    try:
        wb.save(xlsx)
    except PermissionError:
        print("[!] 保存失败：文件仍被占用，裁决未落盘")
        return 2

    print(f"[OK] 已回填 {len(done)} 行：")
    for row, pid, verdict in done:
        print(f"    第 {row} 行 {pid} → {verdict}（N 列={RESULT_OF[verdict]}）")
    return 0


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="上架中残留对账（只列清单，按人裁决回填）")
    ap.add_argument("--xlsx", default=str(XLSX))
    ap.add_argument("--set", action="append", default=[], metavar="行=已发布|未发布")
    a = ap.parse_args()
    xlsx = Path(a.xlsx)

    if a.set:
        sets = {}
        for item in a.set:
            if "=" not in item:
                print(f"[!] 格式应为 行=裁决，收到 {item!r}")
                return 2
            row, verdict = item.split("=", 1)
            try:
                sets[int(row)] = verdict.strip()
            except ValueError:
                print(f"[!] 行号必须是数字，收到 {row!r}")
                return 2
        return apply(sets, xlsx)

    rows = collect(xlsx)
    if not rows:
        print("[OK] 没有停在「上架中」的行，无需对账")
        return 0
    path = write_checklist(rows)
    print(f"[!] {len(rows)} 行停在「上架中」，需人工核对：")
    for r in rows:
        print(f"    第 {r['row']} 行 {r['pid']:8} {r['desc']}")
    print(f"\n清单已写入：{path}")
    print("核对后回填：python project/tools/reconcile.py --set <行>=已发布  或  --set <行>=未发布")
    return 1


if __name__ == "__main__":
    sys.exit(main())
