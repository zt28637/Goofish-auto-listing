"""已发布台账（S3-2 / O4）：防重复发布

**为什么需要**：2026-11-07 真实发生过一次 —— P001 在测试轮被重复发布，
闲鱼上出现两条同样的商品，只能人工下架。根因是「状态列被人重置回待上架」后，
系统没有任何独立于 Excel 的发布记忆。

**台账口径**：一行一条 JSON（jsonl），记 `商品ID + 首图hash + 时间`。
判定重复的两条规则：
  1. 同一 `商品ID` 已存在 → 重复
  2. 不同 ID 但 `首图hash` 相同 → 极可能是同一件货换了个 ID，也提示

**首图口径**：与画布块 045「获取文件列表」一致 —— 递归、按文件名升序、名含点，取第一个。
这样台账里的 hash 和实际上传的第一张图是同一张。

用法:
    python ledger.py seed                    # 从 Excel 里「上架成功」的行补齐台账（幂等）
    python ledger.py check P001              # 查某商品以前发过没
    python ledger.py check P001 --dir <套图目录>   # 连首图一起比对
    python ledger.py list

说明：台账落在 `project/runtime/data/`（运行态，已 gitignore），不入仓。
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


def first_image(folder) -> Path | None:
    """与画布块 045 同口径：递归、跳过目录、按文件名升序取第一个。"""
    p = Path(folder) if folder else None
    if not p or not p.is_dir():
        return None
    files = [f for f in p.rglob("*") if f.is_file() and "." in f.name]
    return sorted(files, key=lambda f: f.name)[0] if files else None


def cover_hash(folder) -> str:
    """首图内容 md5；取不到返回空串（空串不参与重复判定）。"""
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


def check(pid: str, cover: str = "", path: Path | None = None) -> list:
    path = path or LEDGER
    """返回命中记录：同 ID 命中，或首图 hash 相同（且 cover 非空）。"""
    hits = []
    for rec in load(path):
        same_id = pid and rec.get("商品ID") == pid
        same_cover = cover and rec.get("首图hash") == cover
        if same_id or same_cover:
            hits.append(rec)
    return hits


def seed_from_excel(xlsx: Path, path: Path | None = None) -> dict:
    path = path or LEDGER
    """把 Excel 里状态为「上架成功」的行补进台账。幂等：已有同 ID 记录则跳过。"""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    known = {r.get("商品ID") for r in load(path)}
    added, skipped = [], 0
    for vals in ws.iter_rows(min_row=2, values_only=True):
        get = lambda n: (str(vals[n]).strip() if n < len(vals) and vals[n] is not None else "")
        pid, status = get(COL_ID), get(COL_STATUS)
        if status != "上架成功" or not pid:
            continue
        if pid in known:
            skipped += 1
            continue
        rec = {
            "商品ID": pid,
            "首图hash": cover_hash(get(COL_DIR)),
            "结果": status,
            "时间": f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
            "来源": "seed-from-xlsx",
        }
        append(rec, path)
        known.add(pid)
        added.append(pid)
    return {"added": added, "skipped": skipped}


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="已发布台账（防重复发布）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="从 Excel 的「上架成功」行补齐台账")
    s.add_argument("--xlsx", default=str(ROOT / "project" / "runtime" / "商品清单.xlsx"))

    c = sub.add_parser("check", help="查某商品是否发过")
    c.add_argument("pid")
    c.add_argument("--dir", help="套图目录，给了就一并比对首图")

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
            print(f"[OK] {a.pid} 未在台账中出现，可以发布")
            return 0
        print(f"[!] {a.pid} 命中 {len(hits)} 条历史记录：")
        for h in hits:
            print(f"    {h}")
        return 1

    recs = load()
    print(f"台账 {LEDGER}（{len(recs)} 条）")
    for h in recs:
        print(f"  {h.get('商品ID'):10} {h.get('结果', ''):8} {h.get('时间', '')}  {h.get('来源', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
