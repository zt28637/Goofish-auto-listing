"""画布结构化快照（S1-1）：把影刀画布导出成可 diff、可回滚的 JSON

**解决什么问题**：转录只产出 .md，是「给人看的渲染结果」，改完拿不到结构化 diff，
回滚只能靠记忆。11-07 改 `main` 块 9 时，旧表达式是凭对话上下文回忆起才能还原的。

**做法**：走编辑器本地 studio-mcp 只读接口，把每个流程的指令块（含填写值）导出成
`project/canvas/<flow_id>.json`。单文件覆盖 + git 历史 = 天然版本链：
  - `git diff` → 这次改了什么（块增删、表达式变更一目了然）
  - `git checkout <rev> -- project/canvas/process3.json` → 拿到旧版本照着还原

用法:
    python canvas_snapshot.py                    # 导出 FLOW_MAP 里全部 Visual 流程
    python canvas_snapshot.py process3 main      # 只导出指定流程
    python canvas_snapshot.py --check            # 与已存快照比对，有差异退出码 1
    python canvas_snapshot.py --commit "改了分类兜底"   # 写完顺手 git add+commit

**安全**：仓库是 Public，落盘前统一脱敏（手机号 / token / secret 类长串）。
脱敏只作用于值，不改变结构，JSON 仍然合法可 diff。
"""

import argparse
import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadowbot-canvas"))

import sb_mcp
import transcribe_canvas

# 快照落盘目录（project/canvas/，随仓库提交；不放在 runtime/ —— 那里整体被 gitignore）
SNAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "canvas")

# 脱敏规则：值里的手机号与「key=长串」形态的密钥
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_SECRET_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|pwd|cookie|authorization|access_key)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{8,}"
)


def sanitize(value):
    """递归脱敏字符串值。只改值内容，不改结构。"""
    if isinstance(value, str):
        value = _PHONE_RE.sub("1**********(已脱敏)", value)
        value = _SECRET_RE.sub(r"\1=***已脱敏***", value)
        return value
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    return value


def fetch_blocks(flow_id: str) -> list:
    """拉全量块（含填写值），去掉体积巨大且无信息量的 llm_tips。"""
    blocks, offset = [], 0
    while True:
        r = sb_mcp.call("flow.blocks.list", {"flow_id": flow_id, "detail": "detail", "limit": 50, "offset": offset})
        for b in r.get("blocks", []):
            b.pop("llm_tips", None)
            blocks.append(b)
        if r.get("next_offset") in (None, ""):
            return blocks
        offset = int(r["next_offset"])


def build_snapshot(fid: str, flow: dict, blocks: list) -> dict:
    return sanitize({
        "flow_id": fid,
        "flow_name": flow.get("flow_name", ""),
        "flow_kind": flow.get("flow_kind", ""),
        "is_main": flow.get("is_main", False),
        "block_count": len(blocks),
        "captured_at": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "blocks": blocks,
    })


def snap_path(fid: str) -> str:
    return os.path.join(SNAP_DIR, f"{fid}.json")


def load_old(fid: str):
    try:
        with open(snap_path(fid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def diff_summary(old: dict, new: dict) -> list:
    """给出人话级的差异摘要：块数变化 + 逐块对比（按 block_id 追踪）。"""
    lines = []
    if old is None:
        lines.append(f"  新增快照（{new['block_count']} 块）")
        return lines
    if old["block_count"] != new["block_count"]:
        lines.append(f"  块数 {old['block_count']} → {new['block_count']}")
    ob = {b["block_id"]: b for b in old.get("blocks", [])}
    nb = {b["block_id"]: b for b in new.get("blocks", [])}
    added = [b for i, b in nb.items() if i not in ob]
    removed = [b for i, b in ob.items() if i not in nb]
    changed = [b for i, b in nb.items() if i in ob and ob[i].get("fields") != b.get("fields")]
    for b in added:
        lines.append(f"  + [{b['block_index']+1:03d}] {b['prototype_name']}")
    for b in removed:
        lines.append(f"  - [{b['block_index']+1:03d}] {b['prototype_name']}")
    for b in changed:
        old_idx = ob[b["block_id"]]["block_index"]
        lines.append(f"  ~ [{old_idx+1:03d}→{b['block_index']+1:03d}] {b['prototype_name']}（填写值变更）")
    return lines or ["  无变化"]


def list_flows() -> dict:
    """flow_id -> flow。编辑器未停在应用页时返回的是 success=false 的短响应，这里统一成异常。"""
    r = sb_mcp.call("app.list_flows", {})
    if not isinstance(r, dict) or "flows" not in r:
        raise RuntimeError(f"读取流程列表失败：{r if isinstance(r, str) else r.get('message', r)}")
    return {f["flow_id"]: f for f in r["flows"]}


def take(only: set, dry_run: bool) -> int:
    flows = list_flows()
    targets = [fid for fid, f in flows.items()
               if f.get("flow_kind") == "visual" and (not only or fid in only)]
    if not targets:
        print("[!] 编辑器里没有可导出的 Visual 流程")
        return 1

    os.makedirs(SNAP_DIR, exist_ok=True)
    rc = 0
    for fid in targets:
        flow = flows[fid]
        snap = build_snapshot(fid, flow, fetch_blocks(fid))
        old = load_old(fid)
        diffs = diff_summary(old, snap)
        unchanged = old is not None and old["blocks"] == snap["blocks"]
        if dry_run:
            tag = "=" if unchanged else "≠"
            print(f"[{tag}] {fid:10} {snap['flow_name']:16} {snap['block_count']:3} 块")
            for ln in diffs:
                print(ln)
            if not unchanged:
                rc = 1
            continue
        with open(snap_path(fid), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        tag = "=" if unchanged else "±"
        print(f"[{tag}] {fid:10} {snap['flow_name']:16} {snap['block_count']:3} 块 → {os.path.relpath(snap_path(fid))}")
        if not unchanged:
            for ln in diffs:
                print(ln)
    return rc


def git_commit(message: str) -> int:
    import subprocess
    rel = os.path.relpath(SNAP_DIR)
    cmds = [["git", "add", rel], ["git", "commit", "-m", message, "--", rel]]
    for cmd in cmds:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"$ {' '.join(cmd)}\n{p.stdout.strip()}{p.stderr.strip()}")
        if p.returncode != 0:
            return p.returncode
    return 0


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="影刀画布结构化快照（只读）")
    ap.add_argument("flows", nargs="*", help="只导出指定 flow_id；省略=全部 Visual 流程")
    ap.add_argument("--check", action="store_true", help="只比对不落盘，有差异退出码 1")
    ap.add_argument("--commit", metavar="MSG", help="写完自动 git add + commit（只提交 project/canvas/）")
    a = ap.parse_args()

    try:
        rc = take(set(a.flows), dry_run=a.check)
    except RuntimeError as e:
        print(f"[!] {e}")
        return 2
    if rc == 0 and a.commit and not a.check:
        rc = git_commit(a.commit)
    return rc


if __name__ == "__main__":
    sys.exit(main())
