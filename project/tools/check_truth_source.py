"""真源一致性检查（S1-2）：画布 / 转录 / 文档 三处块数必须对齐

**解决什么问题**：11-07 一天里画布从 157 → 176 → 185，每次都要人工去 README 和
AGENTS.md 里改数字。人一忘，文档就开始说谎，而「画布即真源」是这个项目的立身之本。

**检查三处**：
  1. 画布实际块数（studio-mcp `app.list_flows`）
  2. 转录 `project/modules/*.md` 表头的 `块数=N`
  3. 结构化快照 `project/canvas/<flow>.json` 的 `block_count`
  4. 文档里出现的「N 块」声明（README.md / AGENTS.md）

**口径**：文档里的块数只认 ≥50 的数字——像「增 12 块」这类是变更量，不是总数。

用法:
    python check_truth_source.py            # 连编辑器，全量比对
    python check_truth_source.py --offline  # 编辑器没开时，只比转录/快照/文档

退出码: 0 一致 · 1 存在不一致 · 2 连不上编辑器（未加 --offline）
"""

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 仓库根
sys.path.insert(0, os.path.join(HERE, "shadowbot-canvas"))

import sb_mcp
import transcribe_canvas

SNAP_DIR = os.path.join(ROOT, "project", "canvas")
DOC_FILES = ["README.md", "AGENTS.md"]

_BLOCK_CLAIM_RE = re.compile(r"(?<![\d.])(\d{2,4})\s*块")
_TRANSCRIPT_COUNT_RE = re.compile(r"块数=(\d+)")
MIN_CLAIM = 50      # 小于它的「N 块」视为变更量/片段，不当总数


def canvas_counts(offline: bool) -> dict:
    """flow_id -> 画布实际块数。offline 时返回空。"""
    if offline:
        return {}
    r = sb_mcp.call("app.list_flows", {})
    if not isinstance(r, dict) or "flows" not in r:
        raise RuntimeError(f"读取流程列表失败：{r if isinstance(r, str) else r.get('message', r)}")
    return {f["flow_id"]: f.get("block_count") for f in r["flows"] if f.get("flow_kind") == "visual"}


def transcript_count(rel_path: str):
    path = os.path.join(ROOT, "project", "modules", rel_path)
    try:
        with open(path, encoding="utf-8") as f:
            m = _TRANSCRIPT_COUNT_RE.search(f.readline())
            return int(m.group(1)) if m else None
    except OSError:
        return None


def snapshot_count(fid: str):
    try:
        with open(os.path.join(SNAP_DIR, f"{fid}.json"), encoding="utf-8") as f:
            return json.load(f).get("block_count")
    except (OSError, json.JSONDecodeError):
        return None


def doc_claims() -> list:
    """[(文件, 行号, 声称块数)]，只收 ≥MIN_CLAIM 的。"""
    out = []
    for name in DOC_FILES:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                for m in _BLOCK_CLAIM_RE.finditer(line):
                    n = int(m.group(1))
                    if n >= MIN_CLAIM:
                        out.append((name, ln, n))
    return out


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="画布/转录/文档 块数一致性检查")
    ap.add_argument("--offline", action="store_true", help="不连编辑器，只比转录/快照/文档")
    a = ap.parse_args()

    if not a.offline:
        bad = sb_mcp.wrong_app()
        if bad:
            print(f"[!] 编辑器当前打开的是「{bad}」，本仓应用是「{sb_mcp.EXPECTED_APP_NAME}」。")
            print("    再比下去就是拿别家画布判本仓不一致。请切到本仓应用后重跑；不依赖画布的部分用 --offline。")
            return 2

    try:
        counts = canvas_counts(a.offline)
    except RuntimeError as e:
        print(f"[!] {e}")
        return 2

    problems = []

    print("== 画布 vs 转录 ==")
    if a.offline:
        print("  (--offline：跳过画布，仅用转录自身作为基准)")
    for fid, rel in transcribe_canvas.FLOW_MAP.items():
        tc = transcript_count(rel)
        if fid in counts:
            cc = counts[fid]
            ok = tc == cc
            print(f"  {'✓' if ok else '✗'} {fid:10} 画布 {cc:>4} / 转录 {tc if tc is not None else '—':>4}  {rel}")
            if not ok:
                problems.append(f"{rel} 转录块数 {tc} ≠ 画布 {cc}（需重跑 transcribe_canvas.py）")
        elif not a.offline:
            print(f"  · {fid:10} 转录 {tc if tc is not None else '—':>4}  {rel} （编辑器里没有该流程）")

    print("== 快照 ==")
    if not os.path.isdir(SNAP_DIR):
        print("  (尚无 project/canvas/，跑一次 canvas_snapshot.py 建立基线)")
    else:
        for name in sorted(os.listdir(SNAP_DIR)):
            if not name.endswith(".json"):
                continue
            fid = name[:-5]
            sc = snapshot_count(fid)
            cc = counts.get(fid)
            if cc is None:
                print(f"  · {fid:10} 快照 {sc}（--offline 或编辑器无此流程，跳过比对）")
                continue
            ok = sc == cc
            print(f"  {'✓' if ok else '✗'} {fid:10} 快照 {sc:>4} / 画布 {cc:>4}")
            if not ok:
                problems.append(f"快照 {fid}.json 是 {sc} 块，画布已变 {cc} 块（需重跑 canvas_snapshot.py）")

    print("== 文档声明 ==")
    known = set(counts.values()) or {transcript_count(r) for r in transcribe_canvas.FLOW_MAP.values()}
    known.discard(None)
    claims = doc_claims()
    if not claims:
        print("  (文档里没有 ≥50 的「N 块」声明)")
    for name, ln, n in claims:
        ok = n in known
        print(f"  {'✓' if ok else '✗'} {name}:{ln:<4} 声称 {n:>4} 块")
        if not ok:
            problems.append(f"{name}:{ln} 声称 {n} 块，但没有任何流程是这个块数（实际: {sorted(known)}）")

    print()
    if problems:
        print(f"[FAIL] {len(problems)} 处不一致:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[OK] 画布 / 转录 / 快照 / 文档 三处一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
