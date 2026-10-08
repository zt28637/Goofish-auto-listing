"""真源转录：从影刀编辑器 studio-mcp 编译流程步骤清单

产出到 project/docs/真源转录/：
  - 00-索引.md            应用/流程/步骤数总览 + 复现方法
  - <序号>_<flow_id>.md    每个 Visual 流程一份，行格式：编号 指令名 关键参数
可 diff、可 grep。密钥自动脱敏（access_token）。

前提：影刀编辑器已启动，且停在"淘宝竞品价格监控自动化"应用页。
用法：python transcribe_flows.py
"""

import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sb_mcp

OUT_DIR = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project\docs\真源转录"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prototype_names.json")
GROUP_ORDER = {"": -1, "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "测": 9}

_secret_re = re.compile(r"(access_token=)[A-Za-z0-9_\-]{10,}")


def mask(s: str) -> str:
    return _secret_re.sub(r"\1***已脱敏***", s)


def load_names() -> dict:
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def proto_title(proto: str, cache: dict) -> str:
    """wiki 查中文指令名，查不到退回机器名。"""
    if proto in cache:
        return cache[proto]
    title = proto
    try:
        r = sb_mcp.call("wiki.read", {"doc_ids": [f"wiki/blocks/{proto}"]})
        for doc in (r.get("documents") or []) if isinstance(r, dict) else []:
            if doc.get("doc_id", "").endswith(proto) and doc.get("text"):
                first = doc["text"].splitlines()[0].strip()
                if first.startswith("# "):
                    title = first[2:].strip()
                break
    except Exception:
        pass
    cache[proto] = title
    return title


def render_value(v) -> str:
    """字段值压成一行：优先 value，其次展开 dict。"""
    if v is None:
        return ""
    if isinstance(v, dict):
        if "value" in v and v["value"] not in (None, "", []):
            return render_value(v["value"])
        parts = [f"{k}={render_value(val)}" for k, val in v.items() if val not in (None, "", [])]
        return ",".join(p for p in parts if p)
    if isinstance(v, (list, tuple)):
        return "[" + ";".join(render_value(x) for x in v) + "]"
    s = str(v).replace("\n", " ").strip()
    return s[:120] + ("…" if len(s) > 120 else "")


def render_block(b: dict, cache: dict) -> str:
    proto = b.get("prototype_name", "?")
    title = proto_title(proto, cache)
    seg = [f"{b['block_index']+1:03d}", title]
    fields = b.get("fields") or {}
    kv = []
    for k, v in fields.items():
        rv = render_value(v)
        if rv:
            kv.append(f"{k}={rv}")
    tf = b.get("target_flow")
    if tf:
        kv.append(f"→{tf.get('flow_name', tf.get('flow_id'))}")
    line = "  ".join([seg[0], seg[1]] + kv) if kv else f"{seg[0]}  {seg[1]}"
    if proto != title:
        line += f"  [{proto}]"
    return mask(line)


def fetch_all_blocks(flow_id: str) -> list:
    blocks, offset = [], 0
    while True:
        r = sb_mcp.call("flow.blocks.list", {"flow_id": flow_id, "detail": "detail", "limit": 50, "offset": offset})
        blocks.extend(r.get("blocks", []))
        if r.get("next_offset") in (None, ""):
            return blocks
        offset = int(r["next_offset"])


def group_rank(name: str) -> int:
    return GROUP_ORDER.get((name or "")[:1], 8)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = load_names()
    flows = sb_mcp.call("app.list_flows")["flows"]
    visual = sorted([f for f in flows if f["flow_kind"] == "visual"], key=lambda f: (group_rank(f["group_name"]), f["flow_id"]))

    index_rows, n = [], 0
    for f in visual:
        blocks = fetch_all_blocks(f["flow_id"])
        n += 1
        safe_group = re.sub(r"[^\w.\-]+", "", f["group_name"] or "主流程")
        fname = f"{n:02d}_{safe_group}_{f['flow_id']}.md"
        header = [
            f"# {f['flow_name']}  (flow_id={f['flow_id']}, 组={f['group_name'] or '—'}, 块数={len(blocks)})",
            f"# 转录时间 {datetime.datetime.now():%Y-%m-%d %H:%M} · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1",
            "",
        ]
        lines = [render_block(b, cache) for b in blocks]
        with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as fp:
            fp.write("\n".join(header + lines) + "\n")
        index_rows.append((fname, f, len(blocks)))
        print(f"[OK] {fname}  {len(blocks)} 步")

    codes = [f for f in flows if f["flow_kind"] == "code"]
    idx = [
        "# 真源流程索引（影刀画布转录）",
        f"应用：淘宝竞品价格监控自动化 · 生成：{datetime.datetime.now():%Y-%m-%d %H:%M} · 方式：编辑器本地 studio-mcp（官方接口，非逆向）",
        "",
        "| 文件 | flow_id | 流程名 | 组 | 步数 |",
        "|---|---|---|---|---|",
    ]
    for fname, f, cnt in index_rows:
        idx.append(f"| [{fname}]({fname}) | {f['flow_id']} | {f['flow_name']} | {f['group_name'] or '—'} | {cnt} |")
    idx += ["", "## CodeFlow（正文即 Python 源码，见 project/modules 对应文件）", ""]
    idx += [f"- {c['flow_id']}  组={c['group_name'] or '—'}" for c in codes]
    idx += ["", "## 复现", "```", "打开影刀编辑器→停在应用页", "python project/tools/transcribe_flows.py", "```"]
    with open(os.path.join(OUT_DIR, "00-索引.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(idx) + "\n")

    with open(CACHE, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False, indent=1)
    print(f"\n完成：{len(index_rows)} 个 Visual 流程 → {OUT_DIR}")


if __name__ == "__main__":
    main()
