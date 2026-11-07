"""已发布台账（S3-2 / O4）+ 两阶段状态（S3-4 / O2a）

**为什么需要**：2026-11-07 真实发生过一次 —— P001 在测试轮被重复发布，
闲鱼上出现两条同样的商品，只能人工下架。根因是「状态列被人重置回待上架」后，
系统没有任何独立于 Excel 的发布记忆。

**两阶段（O2a）**：发布前先写「意图」，发布后再写「结果」。
崩溃时就能区分「还没开始」和「已经点了发布」：

    claim(pid)    → 事件=claim    状态=inflight    发布前写
    confirm(pid)  → 事件=confirm  状态=confirmed   发布后写
    release(pid)  → 事件=release  状态=released    人工核对为「没发出去」时冲销

一条商品的状态 = **最后一条记录**的状态。查重只认 `confirmed`，
所以 `inflight` / `released` 不会被误判成「已发布过」。

**台账口径**：一行一条 JSON（jsonl）。重复判定两条规则：
  1. 同一 `商品ID` 已 confirmed → 重复
  2. 不同 ID 但 `首图hash` 相同 → 极可能是同一件货换了个 ID，也提示

**首图口径**：与画布块 045「获取文件列表」一致 —— 递归、按文件名升序、名含点，取第一个。

用法:
    python ledger.py seed                     # 从 Excel 的「上架成功」行补齐（幂等）
    python ledger.py check P001 [--dir 目录]   # 查以前发过没
    python ledger.py inflight                 # 列出未确认的 claim
    python ledger.py list

台账落在 `project/runtime/data/`（运行态，已 gitignore），不入仓。
"""

import argparse
import datetime
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "project" / "runtime" / "data" / "published.jsonl"

COL_ID, COL_DIR, COL_STATUS = 0, 11, 13
DEFAULT_LEASE_MIN = 30


def first_image(folder) -> Path | None:
    """与画布块 045 同口径：递归、跳过目录、按文件名升序取第一个。"""
    p = Path(folder) if folder else None
    if not p or not p.is_dir():
        return None
    files = [f for f in p.rglob("*") if f.is_file() and "." in f.name]
    return sorted(files, key=lambda f: f.name)[0] if files else None


def cover_hash(folder) -> str:
    f = first_image(folder)
    if not f:
        return ""
    h = hashlib.md5()
    with open(f, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path | None = None) -> list:
    path = path or LEDGER
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # 坏行跳过：台账可重建，不该因一行脏数据堵死体检
    return out


def append(rec: dict, path: Path | None = None) -> None:
    path = path or LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _now() -> str:
    return f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"


def _age_minutes(ts: str) -> float:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return (datetime.datetime.now() - datetime.datetime.strptime(ts, fmt)).total_seconds() / 60
        except (ValueError, TypeError):
            continue
    return 0.0


def state(rec: dict) -> str:
    """单条记录代表的状态。无「事件」字段的是旧格式/seed 记录，按结果推断。"""
    ev = rec.get("事件")
    if ev == "claim":
        return "inflight"
    if ev == "release":
        return "released"
    res = rec.get("结果") or ""
    if res == "上架成功":
        return "confirmed"
    if res == "上架失败":
        return "failed"
    if res:
        return "unknown"
    return "unknown"


def current_state(pid: str, path: Path | None = None) -> str | None:
    """最后一条记录的状态。没有记录返回 None。"""
    last = None
    for rec in load(path):
        if rec.get("商品ID") == pid:
            last = rec
    return state(last) if last else None


def claim(pid: str, run_id: str = "", note: str = "", path: Path | None = None) -> dict:
    rec = {"商品ID": pid, "事件": "claim", "时间": _now(), "run_id": run_id, "note": note}
    append(rec, path)
    return rec


def confirm(pid: str, result: str, run_id: str = "", cover: str = "", path: Path | None = None) -> dict:
    rec = {"商品ID": pid, "事件": "confirm", "结果": result, "时间": _now(), "run_id": run_id}
    if cover:
        rec["首图hash"] = cover
    append(rec, path)
    return rec


def release(pid: str, note: str = "", path: Path | None = None) -> dict:
    """冲销 inflight：人工核对确认「没发出去」，允许重新入队。"""
    rec = {"商品ID": pid, "事件": "release", "结果": "未发布", "时间": _now(), "note": note}
    append(rec, path)
    return rec


def check(pid: str, cover: str = "", path: Path | None = None) -> list:
    """命中记录：同 ID 已 confirmed，或首图 hash 相同（cover 非空）。inflight/released 不算。"""
    hits = []
    for rec in load(path):
        if state(rec) != "confirmed":
            continue
        if (pid and rec.get("商品ID") == pid) or (cover and rec.get("首图hash") == cover):
            hits.append(rec)
    return hits


def inflight(path: Path | None = None, lease_minutes: int = DEFAULT_LEASE_MIN) -> list:
    """超过租约仍未确认的 claim → [(pid, rec)]。租约内的视为「正在跑」，不打扰。"""
    latest, out = {}, []
    for rec in load(path):
        pid = rec.get("商品ID")
        if pid:
            latest[pid] = rec
    for pid, rec in latest.items():
        if state(rec) == "inflight" and _age_minutes(rec.get("时间", "")) > lease_minutes:
            out.append((pid, rec))
    return out


def seed_from_excel(xlsx: Path, path: Path | None = None) -> dict:
    """把 Excel 里状态为「上架成功」的行补进台账。幂等：已是 confirmed 的跳过。"""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    added, skipped = [], 0
    for vals in ws.iter_rows(min_row=2, values_only=True):
        get = lambda n: (str(vals[n]).strip() if n < len(vals) and vals[n] is not None else "")
        pid, status = get(COL_ID), get(COL_STATUS)
        if status != "上架成功" or not pid:
            continue
        if current_state(pid, path) == "confirmed":
            skipped += 1
            continue
        append({"商品ID": pid, "事件": "confirm", "结果": status, "首图hash": cover_hash(get(COL_DIR)),
                "时间": _now(), "来源": "seed-from-xlsx"}, path)
        added.append(pid)
    return {"added": added, "skipped": skipped}


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="已发布台账（防重复发布 / 两阶段状态）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="从 Excel 的「上架成功」行补齐台账")
    s.add_argument("--xlsx", default=str(ROOT / "project" / "runtime" / "商品清单.xlsx"))

    c = sub.add_parser("check", help="查某商品是否发过")
    c.add_argument("pid")
    c.add_argument("--dir", help="套图目录，给了就一并比对首图")

    sub.add_parser("inflight", help="列出超租约未确认的 claim")
    sub.add_parser("list", help="列出台账")

    a = ap.parse_args()

    if a.cmd == "seed":
        r = seed_from_excel(Path(a.xlsx))
        print(f"新增 {len(r['added'])} 条：{r['added']}；已存在跳过 {r['skipped']} 条")
        print(f"台账：{LEDGER}")
        return 0

    if a.cmd == "check":
        hits = check(a.pid, cover_hash(a.dir) if a.dir else "")
        if not hits:
            print(f"[OK] {a.pid} 无已确认发布记录，可以发布（当前状态：{current_state(a.pid) or '无记录'}）")
            return 0
        print(f"[!] {a.pid} 命中 {len(hits)} 条已确认记录：")
        for h in hits:
            print(f"    {h}")
        return 1

    if a.cmd == "inflight":
        recs = inflight()
        if not recs:
            print("[OK] 无超租约的未确认发布")
            return 0
        print(f"[!] {len(recs)} 条未确认（需对账）：")
        for pid, rec in recs:
            print(f"    {pid:10} {rec.get('时间')}  run={rec.get('run_id', '')}")
        return 1

    recs = load()
    print(f"台账 {LEDGER}（{len(recs)} 条）")
    for h in recs:
        print(f"  {h.get('商品ID'):10} {state(h):10} {h.get('时间', '')}  {h.get('结果') or h.get('事件', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
