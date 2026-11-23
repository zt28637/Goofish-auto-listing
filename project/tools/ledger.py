"""上架记录日志（ledger）—— 按商品维度记录本地发布动作的业务日志

**定位（2026-11-09 明确）**：它是一本**只追加、不回改的日志**，不是「平台在线清单」，
也不参与发布拦截。它只回答「这件货我们发过几次、每次判定结果是什么」，
回答不了「这件货现在还在不在线」——那是闲鱼后台的事，本地无从感知。

记录类型与状态推导（看某个商品 ID 的最后一条记录）：
    claim(pid)        → inflight   点了发布前的占位（30 分钟租约）
    confirm(pid, 结果) → confirmed / failed / unknown
    release(pid)      → released   人工修正（平台侧已删除/下架时用）
    无「事件」字段的旧记录（seed） → 按「结果」推

存储：`project/runtime/data/published.jsonl`，一行一条 JSON，坏行跳过（可重建）。
运行时落盘（gitignore），不入仓。

命令：
    python ledger.py list                 # 看全部记录与每条的状态
    python ledger.py check <ID> [--dir]   # 查历史命中（同 ID 或同首图 hash 的 confirmed）
    python ledger.py seed                 # 从 Excel「上架成功」行补录（幂等）
    python ledger.py inflight             # 超租约未确认的 claim
    python ledger.py release <ID> --note  # 人工修正记录

口径说明：
  · **check() 扫全历史**：某 ID 只要历史上出现过 confirmed 就命中，即使后面有 release。
    需要「当前状态」请用 current_state()（最后一条记录）。
  · 首图 hash 与上传口径一致：递归、按文件名升序、名含点。
  · 发布流程**不再依赖本日志拦截**（曾因平台侧人工删除产生过期 confirmed，
    误挡合法重发）；防误重发由 Excel 状态列决定。
"""

from __future__ import annotations

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


# 判定结果有两种口径：步骤代码写英文枚举（success/failed/unknown），
# reconcile/seed 与历史记录写中文。confirm 统一存中文，state 两种都认。
_RESULT_ZH = {
    "success": "上架成功",
    "failed": "上架失败",
    "unknown": "上架情况不明，待人工确认",
}
_RESULT_STATE = {
    "success": "confirmed",
    "failed": "failed",
    "上架成功": "confirmed",
    "上架失败": "failed",
    "上架情况不明，待人工确认": "unknown",
}


def state(rec: dict) -> str:
    """单条记录代表的状态。无「事件」字段的是旧格式/seed 记录，按结果推断。"""
    ev = rec.get("事件")
    if ev == "claim":
        return "inflight"
    if ev == "release":
        return "released"
    res = rec.get("结果") or ""
    return _RESULT_STATE.get(res, "unknown")


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
    rec = {"商品ID": pid, "事件": "confirm", "结果": _RESULT_ZH.get(result, result),
           "时间": _now(), "run_id": run_id}
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
    ap = argparse.ArgumentParser(description="上架记录日志（ledger）：按商品追溯，不拦发布")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="从 Excel 的「上架成功」行补录日志")
    s.add_argument("--xlsx", default=str(ROOT / "project" / "runtime" / "商品清单.xlsx"))

    c = sub.add_parser("check", help="查某商品是否发过")
    c.add_argument("pid")
    c.add_argument("--dir", help="套图目录，给了就一并比对首图")

    sub.add_parser("inflight", help="列出超租约未确认的 claim")
    sub.add_parser("list", help="列出记录")

    rel = sub.add_parser("release", help="人工在平台删除商品后补一条 release 记录")
    rel.add_argument("pid")
    rel.add_argument("--note", default="人工删除后冲销", help="冲销原因")

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

    if a.cmd == "release":
        rec = release(a.pid, note=a.note)
        print(f"[OK] {a.pid} 已冲销为 {state(rec)}（{a.note}）")
        print(f"     当前状态：{current_state(a.pid)}；之后可重新发布")
        return 0

    recs = load()
    print(f"台账 {LEDGER}（{len(recs)} 条）")
    for h in recs:
        print(f"  {h.get('商品ID'):10} {state(h):10} {h.get('时间', '')}  {h.get('结果') or h.get('事件', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
