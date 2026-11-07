"""运行前体检（S3-1 / O1 + O2）：启动影刀流程之前，用 30 秒把所有「已知会让整轮报废」的环境问题查一遍

**为什么需要**：2026-11-07 真实发生过两件事 ——
  ① 上一轮中断，WPS 没关，`商品清单.xlsx` 被占用，写表 `PermissionError`，要人工关进程才能继续
  ② 崩溃后 N 列残留「上架中」，AGENTS 要求「先对账再改回待上架」，全靠人记

**不做什么**：不改任何数据、不连浏览器、不碰账号。只读 + 报告。

用法:
    python preflight.py                 # 体检默认清单
    python preflight.py --xlsx 路径      # 指定清单
    python preflight.py --json          # 机器可读

退出码: 0=无阻塞项（可能有警告）· 1=存在阻塞项（**不要启动**）· 2=清单读不了
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # 仓库根
CONF = ROOT / "project" / "conf" / "credentials.local.json"
RUNTIME = ROOT / "project" / "runtime"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl

import ledger

# 影刀按 0 起列号读表（块 037/043/053/057/106/111 等），表头漂移会静默串列 → 必须核对
EXPECTED_HEADERS = {
    3: "分类路径",
    6: "价格",
    7: "原价",
    8: "发货设置",
    11: "套图目录",
    12: "描述",
    13: "状态",
}
COL_CAT, COL_DIR, COL_ID, COL_STATUS = 3, 11, 0, 13
OFFICE_NAMES = {"wps.exe", "et.exe", "excel.exe", "wpscloudsvr.exe"}

OK, WARN, BLOCK = "OK", "WARN", "BLOCK"


def _office_processes():
    """返回正在运行的 Office 系进程；psutil 不可用时返回空（退化为只查锁文件）。"""
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for p in psutil.process_iter(["pid", "name"]):
        name = (p.info.get("name") or "").lower()
        if name in OFFICE_NAMES:
            found.append((p.info["pid"], p.info["name"]))
    return found


def _show(p: Path) -> str:
    """路径展示：优先相对仓库，仓库外的临时路径原样返回（relative_to 会抛 ValueError）。"""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def check_credentials():
    if not CONF.exists():
        return BLOCK, "凭据文件", f"缺失 {_show(CONF)} —— 画布块 009 读取会直接失败"
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
    except Exception as e:
        return BLOCK, "凭据文件", f"JSON 解析失败：{e}"
    missing = [k for k in ("phone", "password") if not str(d.get(k, "")).strip()]
    if missing:
        return BLOCK, "凭据文件", f"缺少字段 {missing}（改密后最容易忘了同步这里）"
    return OK, "凭据文件", f"phone {len(str(d['phone']))} 位 / password {len(str(d['password']))} 位"


def check_lock(xlsx: Path):
    locks = list(xlsx.parent.glob("~$*.xlsx"))
    procs = _office_processes()
    if not locks:
        if procs:
            return WARN, "Office 进程", f"有 {len(procs)} 个 Office 进程在跑（未必占用本表）：{procs[:3]}"
        return OK, "Excel 占用", "无锁文件、无 Office 进程"
    if procs:
        return BLOCK, "Excel 占用", f"锁文件 {[p.name for p in locks]} + Office 进程 {procs[:3]} —— 先关 WPS/Excel"
    return WARN, "Excel 占用", f"有残留锁文件 {[p.name for p in locks]} 但无 Office 进程，可能上次异常退出（通常可安全删除）"


def check_writable(xlsx: Path):
    try:
        with open(xlsx, "a+b"):
            pass
        return OK, "写权限", "文件可写"
    except PermissionError:
        return BLOCK, "写权限", "文件被占用或只读，画布块 128/151 保存会失败"
    except OSError as e:
        return WARN, "写权限", f"无法以追加方式打开：{e}"


def check_headers(xlsx: Path):
    try:
        wb = openpyxl.load_workbook(xlsx, read_only=True)
        ws = wb.active
        row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    except Exception as e:
        return BLOCK, "表头校验", f"读表失败：{e}"
    bad = []
    for idx, want in EXPECTED_HEADERS.items():
        got = str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""
        if got != want:
            bad.append(f"列{idx}={got!r} 应为 {want!r}")
    if bad:
        return BLOCK, "表头校验", "列漂移 -> " + "；".join(bad)
    return OK, "表头校验", f"{len(EXPECTED_HEADERS)} 个被消费列全部对位"


def scan_rows(xlsx: Path):
    """返回 [(行号, pid, 分类, 状态)]，供残留检测与台账比对。"""
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    out = []
    for i, vals in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(v is not None and str(v).strip() for v in vals):
            continue
        get = lambda n: (str(vals[n]).strip() if n < len(vals) and vals[n] is not None else "")
        out.append((i, get(COL_ID), get(COL_CAT), get(COL_STATUS)))
    return out


def check_residue(rows):
    stuck = [(r, pid) for r, pid, _c, st in rows if st == "上架中"]
    if not stuck:
        return OK, "残留状态", "无「上架中」残留"
    return WARN, "残留状态", (
        f"{len(stuck)} 行停在上架中 {stuck} —— 崩溃残留。"
        "跑 `python project/tools/reconcile.py` 生成核对清单，"
        "核对后按裁决回填（**不要直接改回「待上架」再重跑，可能重复发布**）"
    )


def check_ledger(rows):
    known = {r.get("商品ID") for r in ledger.load()}
    done = [(r, pid) for r, pid, _c, st in rows if st == "上架成功"]
    missing = [(r, pid) for r, pid in done if pid and pid not in known]
    if not done:
        return OK, "发布台账", "无「上架成功」行"
    if missing:
        return WARN, "发布台账", f"{len(missing)} 条已成功但不在台账 {missing[:5]} —— 跑一次 `python ledger.py seed`"
    return OK, "发布台账", f"{len(done)} 条「上架成功」均已在台账"


def run(xlsx: Path):
    checks = [check_credentials()]
    if xlsx.exists():
        checks += [check_lock(xlsx), check_writable(xlsx), check_headers(xlsx)]
        try:
            rows = scan_rows(xlsx)
            checks += [check_residue(rows), check_ledger(rows)]
        except Exception as e:
            checks.append((BLOCK, "读表", f"读取行数据失败：{e}"))
    else:
        checks.append((BLOCK, "清单文件", f"不存在 {xlsx}"))
    return checks


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="上架前环境体检（只读）")
    ap.add_argument("--xlsx", default=str(RUNTIME / "商品清单.xlsx"))
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    a = ap.parse_args()
    xlsx = Path(a.xlsx)

    checks = run(xlsx)
    n_block = sum(1 for lv, *_ in checks if lv == BLOCK)
    n_warn = sum(1 for lv, *_ in checks if lv == WARN)

    if a.json:
        print(json.dumps({"block": n_block, "warn": n_warn,
                          "checks": [{"level": lv, "name": nm, "detail": d} for lv, nm, d in checks]},
                         ensure_ascii=False, indent=1))
        return 1 if n_block else 0

    for lv, name, detail in checks:
        mark = {"OK": "✓", "WARN": "!", "BLOCK": "✗"}[lv]
        print(f"[{mark} {lv:5}] {name:8} {detail}")
    print()
    if n_block:
        print(f"[BLOCK] {n_block} 项阻塞、{n_warn} 项警告 —— 修完再启动，否则中途必挂")
        return 1
    print(f"[OK] 无阻塞项（{n_warn} 项警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
