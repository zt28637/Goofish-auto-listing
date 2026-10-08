"""画布转录 v2：从影刀编辑器 studio-mcp 直接覆盖 project/modules 画布文件

比 transcribe_flows.py（v1，产出 docs/真源转录）更进一步：
  - 指令名/参数名用 sb_blocks_zh.json（extract_sb_catalog.py 从编辑器 DLL 提取）
  - 按 FLOW_MAP 直接写回 project/modules/<环节>/<画布名>.md（覆盖旧转录）
  - 行格式与既有画布一致：编号  指令名  参数=值  →目标流程  [机器名]

前提：影刀编辑器已启动，停在"淘宝竞品价格监控自动化"应用页。
用法：python transcribe_canvas.py            # 全部映射流程
      python transcribe_canvas.py main       # 只转指定 flow_id

不改动任何 .py 业务代码；1-3滚动策略优化蓝本.md 是设计文档、非转录，勿映射。
"""

import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sb_mcp

MOD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules")
CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sb_blocks_zh.json")

# flow_id -> (相对 project/modules 的画布路径)。新增画布在此登记。
FLOW_MAP = {
    "main": "主流程_main.md",
    "process65": "0.淘宝自动化登录/0-0自动化登录.md",
    # 文件名沿用仓库旧名"凭据"（README/USER-CONFIG 均引用此名）；画布标题以编辑器流程名"凭证"为准
    "process66": "0.淘宝自动化登录/0-1登录凭据设置.md",
    "process67": "0.淘宝自动化登录/0-2模拟登录.md",
    "process51": "1.竞品商品数据采集/1-1商品数据采集.md",
    "process64": "1.竞品商品数据采集/1-2下一页按钮翻页.md",
    "process62": "2.竞品SKU数据采集/2-0B-SKU数据采集.md",
    "process59": "2.竞品SKU数据采集/2-1B1-SKU一维数据采集.md",
    "process60": "2.竞品SKU数据采集/2-2B2-SKU二维数据采集.md",
    "process68": "工具箱/通用滚动策略.md",
}
# process61 测试主流程：开发期试验场，刻意不落盘（沿用旧索引约定）
# 工具箱/通用滚动策略.md = process68（影刀组"工具箱"，1-1/2-0 等共用）

# 手工注记（画布块序号 → 行尾追加文字），重转录自动保留
NOTES = {
    "process66": {1: "用户根变量", 2: "档目录变量", 3: "凭据文件变量"},
}
# 文末附录（flow_id → markdown 段落），重转录自动保留
APPENDIX = {
    "main": """
## 审核疑点（2026-09-30 · 对照模块 .py 签名交叉核对，仅记录，未改画布）
- **011 路径拼写**：导出目录 `product_alllraw`（3个l），磁盘实际为 `runtime/product_allraw` → 会静默新建错误目录，下游按实际名找不到文件
- **019 多余且有害的 report 调用**：`output_path=input 竞品清洗Excel`（report.py 会覆盖清洗产物），023 再调用时读到的已是被日报覆盖的文件而非 13 列清洗表；015→019→023 三连里 019 疑似返工遗留，应删（023 单独保留即可，或改 output_path）
- **027 alert keyword 传错**：alert.py 的 `keyword` 是"搜索关键词（拼消息标题）"，画布传了 `glv['dingtalk_secret']`（钉钉加签密钥）→ 标题出现密钥字样=泄露；且 alert.py 本身不实现加签，机器人若为"加签"型则发送会 401（若是"自定义关键词"型，此参数应传关键词文本而非 secret）
- **012/016 重复赋值**：`竞品清洗Excel` 同一表达式赋值两次（冗余无害）

> 复核 2026-10-08（重转录后逐条对照新画布）：**四条疑点在原位置全部仍成立**（011/012/016/019/023/027 块号未变）。
""",
}

MODE_CN = {
    "variable": "变量",
    "expression": "表达式",
    "selector": "元素库",
    "concat": "拼接",
    "list": "列表",
    "dict": "字典",
}
# 目录里残留繁体的条目，按旧画布口径转简（file.read 见 0-1:011 旧行）
TITLE_ZH_FIX = {"file.read": "读取文件", "file.write": "写入文件"}

_secret_re = re.compile(r"(access_token=|token=)[A-Za-z0-9_\-]{10,}")


def mask(s: str) -> str:
    return _secret_re.sub(r"\1***已脱敏***", s)


def render_value(v, translate=True) -> str:
    """值节点压成一行：mode 转中文（顶层），group_array 内部保持原始英文键。"""
    if v is None:
        return ""
    if isinstance(v, dict):
        if "group_array" in v:
            items = ";".join(render_value(e, translate=False) for e in v["group_array"])
            return f"group_array=[{items}]"
        parts = []
        for k, val in v.items():
            key = MODE_CN.get(k, k) if translate else k
            rv = render_value(val, translate)
            if rv == "":
                if val is None:
                    continue              # 键在但未赋值 → 整个跳过（一元条件 operand2 等）
                parts.append("")          # 空值留裸空位（;;），旧画布惯例，不写键
            else:
                parts.append(f"{key}={rv}")
        return ",".join(parts)
    if isinstance(v, (list, tuple)):
        inner = ";".join(render_value(x, translate) for x in v)
        return f"[{inner}]" if inner != "" else "[]"
    s = str(v).replace("\n", " ").strip()
    return s[:160] + ("…" if len(s) > 160 else "")


COND_ENTRY_LABELS = {}  # operand1/operand2/operator -> 对象1/对象2/关系，运行时从 catalog 填充


def render_entry(e: dict) -> str:
    """条件组条目：键走 workflow.if 的参数中文名（对象1/关系/对象2），值 mode 转中文。"""
    parts = []
    for k, v in e.items():
        key = COND_ENTRY_LABELS.get(k, k)
        rv = render_value(v)
        if rv == "":
            continue  # 一元条件空 operand2 整体省略（旧画布惯例）
        parts.append(f"{key}={rv}")
    return ",".join(parts)


def render_block(b: dict, cat: dict, notes: dict = None) -> str:
    proto = b.get("prototype_name", "?")
    title = TITLE_ZH_FIX.get(proto) or cat["titles"].get(proto) or proto
    block_labels = cat["labels"].get(proto) or {}
    seg = [f"{b['block_index']+1:03d}", title]
    kv = []
    for k, fv in (b.get("fields") or {}).items():
        label = block_labels.get(k, k)
        val = fv.get("value") if isinstance(fv, dict) and "value" in fv else None
        if k == "conditionals" and isinstance(val, dict) and "group_array" in val:
            label = "条件组"
            rv = "[" + ";".join(render_entry(e) for e in val["group_array"]) + "]"
        elif val is None:
            continue
        else:
            rv = render_value(val)
        if rv != "":
            kv.append(f"{label}={rv}")
    tf = b.get("target_flow")
    if tf:
        kv.append(f"→{tf.get('flow_name', tf.get('flow_id'))}")
    line = "  ".join(seg + kv)
    if proto != title:
        line += f"  [{proto}]"
    note = (notes or {}).get(b["block_index"] + 1)
    if note:
        line += f"  {note}"
    return mask(line)


def fetch_all_blocks(flow_id: str) -> list:
    blocks, offset = [], 0
    while True:
        r = sb_mcp.call("flow.blocks.list", {"flow_id": flow_id, "detail": "detail", "limit": 50, "offset": offset})
        for b in r.get("blocks", []):
            b.pop("llm_tips", None)
            blocks.append(b)
        if r.get("next_offset") in (None, ""):
            return blocks
        offset = int(r["next_offset"])


def old_block_count(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            m = re.search(r"块数=(\d+)", f.readline())
            return int(m.group(1)) if m else None
    except OSError:
        return None


def load_catalog() -> dict:
    cat = json.load(open(CATALOG, encoding="utf-8"))
    # 官方 label 为空/只有空格的（如 programing.sleep.random_number）视同无标签 → 渲染时回退英文键名
    cat["labels"] = {n: {k: v.strip() for k, v in lb.items() if v and v.strip()} for n, lb in cat["labels"].items()}
    COND_ENTRY_LABELS.update({k: v for k, v in cat["labels"].get("workflow.if", {}).items()
                              if k in ("operand1", "operand2", "operator")})
    return cat


def list_flows() -> list:
    return sb_mcp.call("app.list_flows")["flows"]


def render_flow(fid: str, f: dict, cat: dict, now: str) -> str:
    """把一个 Visual 流程渲染成完整画布文本（header+行+附录），不落盘。"""
    blocks = fetch_all_blocks(fid)
    header = [
        f"# {f['flow_name']}  (flow_id={fid}, 组={f['group_name'] or '—'}, 块数={len(blocks)})",
        f"# 转录时间 {now} · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1",
        "# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep",
        "",
    ]
    lines = [render_block(b, cat, NOTES.get(fid, {})) for b in blocks]
    text = "\n".join(header + lines) + "\n"
    if fid in APPENDIX:
        text += APPENDIX[fid].rstrip("\n") + "\n"
    return text


def transcribe(only=None, dry_run: bool = False) -> list:
    """转录落盘（或 dry_run 只比对）。返回报告行列表。only: flow_id 集合，None=全部。"""
    only = set(only) if only else set()
    cat = load_catalog()
    flows = {f["flow_id"]: f for f in list_flows()}
    now = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
    report = []
    for fid, rel in FLOW_MAP.items():
        if only and fid not in only:
            continue
        f = flows.get(fid)
        if not f or f["flow_kind"] != "visual":
            report.append(f"[SKIP] {fid} 不在编辑器 Visual 列表")
            continue
        path = os.path.normpath(os.path.join(MOD, rel))
        text = render_flow(fid, f, cat, now)
        n_blocks = int(re.search(r"块数=(\d+)", text).group(1))
        prev = old_block_count(path)
        if dry_run:
            same = os.path.exists(path) and _same_ignoring_time(open(path, encoding="utf-8").read(), text)
            report.append(f"[{'=' if same else '≠'}] {rel}  画布 {n_blocks} 步 vs 磁盘 {prev if prev is not None else '无'} 步")
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
        delta = f"{prev}→{n_blocks}" if prev is not None else f"新增({n_blocks})"
        report.append(f"[OK] {rel}  {delta} 步")

    unmapped = [fid for fid, f in flows.items() if f["flow_kind"] == "visual" and fid not in FLOW_MAP]
    if unmapped:
        report.append("[TODO] 编辑器中未映射的 Visual 流程: " + ", ".join(f"{u}({flows[u].get('flow_name', '')})" for u in unmapped))
    return report


def _same_ignoring_time(old: str, new: str) -> bool:
    """比较两版画布，忽略'转录时间'行（每次跑都变）。"""
    strip = lambda s: "\n".join(ln for ln in s.splitlines() if not ln.startswith("# 转录时间"))
    return strip(old) == strip(new)


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for line in transcribe(only=sys.argv[1:]):
        print(line)


if __name__ == "__main__":
    main()
