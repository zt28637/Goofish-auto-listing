"""影刀画布 MCP 服务器（stdio · 零依赖，手写 JSON-RPC 2.0）

把 画布转录工具链（sb_mcp + transcribe_canvas + extract_sb_catalog）封装成 MCP，
供 Claude Code / Cursor 等直接调用。注册见仓库根 .mcp.json 的 "shadowbot-canvas"。

暴露工具：
  sb_list_flows        列出编辑器当前应用全部流程（含画布映射状态）
  sb_get_canvas        预览单个流程的画布转录文本（只读，不落盘）
  sb_transcribe_canvas 转录落盘覆盖 project/modules 画布（支持单流程 / dry_run 只比对）
  sb_refresh_catalog   从编辑器 DLL 重建中文指令目录 sb_blocks_zh.json

前提：影刀编辑器已启动并停在目标应用页（端口从影刀日志自动发现）。
调试：printf 一行一个 JSON-RPC 消息管道进本脚本即可（见 索引.md 复现节）。
"""

import contextlib
import io
import json
import os
import re
import sys
import datetime
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sb_mcp
import transcribe_canvas as tc
import extract_sb_catalog

SERVER_INFO = {"name": "shadowbot-canvas", "version": "1.0.0"}
PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "sb_list_flows",
        "description": "列出影刀编辑器当前打开应用的全部流程：flow_id/名称/类型(visual画布|code代码)/组/块数，以及画布转录映射状态（已映射文件路径 / 未映射 / 刻意不落盘）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sb_get_canvas",
        "description": "预览单个 Visual 流程的画布转录文本（中文指令名+参数，与 project/modules 画布同格式）。只读，不写任何文件。",
        "inputSchema": {
            "type": "object",
            "properties": {"flow_id": {"type": "string", "description": "流程ID，如 main / process51"}},
            "required": ["flow_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sb_transcribe_canvas",
        "description": "把影刀编辑器当前流程转录落盘，覆盖 project/modules 对应画布 .md（手工注记/审核疑点附录自动保留）。不传 flow_id = 全部映射流程。dry_run=true 只比对不落盘。返回逐文件步数变化报告。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "string", "description": "只转录指定流程；缺省=全部"},
                "dry_run": {"type": "boolean", "description": "true=只比对差异，不写文件", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "sb_refresh_catalog",
        "description": "从影刀编辑器安装目录 DLL + 应用 xbot_extensions 明文目录重建中文指令目录 tools/sb_blocks_zh.json。仅编辑器升级或指令名渲染异常时需要。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sb_refresh_tools",
        "description": "重新拉取编辑器 studio-mcp 的 tools/list，写入 studio_tools.json 快照。编辑器升级后调用，重启/重连 MCP 生效。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

# ---- 编辑器 studio-mcp 全量工具代理 ----
# studio_tools.json = tools/list 快照（随编辑器版本变化，sb_refresh_tools 重建）。
# 工具名里的点号在 MCP 客户端不合法，统一换成下划线并加 sb_ 前缀：
#   flow.edit_blocks -> sb_flow_edit_blocks（描述里保留原名，便于对照影刀文档）
STUDIO_TOOLS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio_tools.json")
STUDIO_BY_PUBLIC = {}
_STUDIO_TIMEOUT = {"app.run": 130, "app.wait_run_finish": 130}


def _sanitize(name: str) -> str:
    return "sb_" + re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _load_studio_tools() -> list:
    try:
        with open(STUDIO_TOOLS_FILE, encoding="utf-8") as f:
            return json.load(f).get("tools", [])
    except (OSError, ValueError):
        return []


def _extend_studio_tools() -> list:
    extra, used = [], {t["name"] for t in TOOLS}
    for t in _load_studio_tools():
        pub = _sanitize(t["name"])
        while pub in used:          # 极端情况：多个原名压成同名
            pub += "_"
        used.add(pub)
        STUDIO_BY_PUBLIC[pub] = t["name"]
        extra.append({
            "name": pub,
            "description": f"[studio-mcp: {t['name']}] " + (t.get("description") or ""),
            "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
        })
    return extra


TOOLS.extend(_extend_studio_tools())


def _friendly(exc: Exception) -> str:
    msg = str(exc)
    if "MCP 端口" in msg or "Connection refused" in msg or "URLError" in msg:
        return f"影刀编辑器未检测到（studio-mcp 离线）：{msg}\n请打开影刀编辑器并停在目标应用页后重试。"
    return f"{type(exc).__name__}: {msg}"


def tool_list_flows() -> str:
    flows = tc.list_flows()
    rows = ["flow_id | 名称 | 类型 | 组 | 块数 | 画布映射"]
    for f in sorted(flows, key=lambda x: (x["flow_kind"], x["group_name"] or "", x["flow_id"])):
        fid = f["flow_id"]
        if f["flow_kind"] == "code":
            mapped = "CodeFlow（.py 源码在 project/modules 对应目录）"
        elif fid in tc.FLOW_MAP:
            mapped = tc.FLOW_MAP[fid]
        elif fid == "process61":
            mapped = "刻意不落盘（测试主流程）"
        else:
            mapped = "❌ 未映射（新流程请登记 transcribe_canvas.FLOW_MAP）"
        rows.append(f"{fid} | {f['flow_name']} | {f['flow_kind']} | {f['group_name'] or '—'} | {f['block_count']} | {mapped}")
    return "\n".join(rows)


def tool_get_canvas(flow_id: str) -> str:
    flows = {f["flow_id"]: f for f in tc.list_flows()}
    f = flows.get(flow_id)
    if not f:
        raise ValueError(f"编辑器中没有流程 {flow_id}（先用 sb_list_flows 查看）")
    if f["flow_kind"] != "visual":
        raise ValueError(f"{flow_id} 是 CodeFlow（Python 源码流程），无画布可转录；源码见 project/modules 对应 .py")
    cat = tc.load_catalog()
    now = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
    return tc.render_flow(flow_id, f, cat, now)


def tool_transcribe_canvas(flow_id: str = None, dry_run: bool = False) -> str:
    only = [flow_id] if flow_id else None
    if flow_id and flow_id not in tc.FLOW_MAP:
        raise ValueError(f"{flow_id} 不在 FLOW_MAP（画布路径映射）中；先登记 transcribe_canvas.py 的 FLOW_MAP 再转录")
    return "\n".join(tc.transcribe(only=only, dry_run=dry_run))


def tool_refresh_catalog() -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        extract_sb_catalog.main()
    return buf.getvalue() or "完成（无输出）"


def tool_studio_call(original: str, args: dict) -> str:
    """转发到编辑器 studio-mcp。run 类工具放宽超时（app.run 可内联等待 115s）。"""
    out = sb_mcp.call(original, args, timeout=_STUDIO_TIMEOUT.get(original, 60))
    return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)


def tool_refresh_tools() -> str:
    """重新拉取编辑器 tools/list 写入快照；当前进程的工具表不变，重连后生效。"""
    port = sb_mcp.discover_port()
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/mcp",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    body = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    for line in body.splitlines():
        if line.startswith("data:"):
            body = line[5:].strip()
            break
    tools = json.loads(body)["result"]["tools"]
    snap = {"fetched_at": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}", "port": port, "tools": tools}
    with open(STUDIO_TOOLS_FILE, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return f"已更新 {len(tools)} 个工具快照：{STUDIO_TOOLS_FILE}（重连 MCP 后生效）"


HANDLERS = {
    "sb_list_flows": lambda args: tool_list_flows(),
    "sb_get_canvas": lambda args: tool_get_canvas(args["flow_id"]),
    "sb_transcribe_canvas": lambda args: tool_transcribe_canvas(args.get("flow_id"), bool(args.get("dry_run", False))),
    "sb_refresh_catalog": lambda args: tool_refresh_catalog(),
    "sb_refresh_tools": lambda args: tool_refresh_tools(),
}

# 40 个 studio-mcp 工具逐个注册为转发 handler（闭包用工厂绑定，避免迟绑定）
for _pub, _orig in STUDIO_BY_PUBLIC.items():
    HANDLERS[_pub] = (lambda orig: lambda args: tool_studio_call(orig, args))(_orig)


def _send(out, obj) -> None:
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


def _result(id, result, out):
    _send(out, {"jsonrpc": "2.0", "id": id, "result": result})


def _error(id, code, message, out):
    _send(out, {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


def main() -> None:
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        id, method = msg.get("id"), msg.get("method")
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                _result(id, {
                    "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                }, stdout)
            elif id is None:
                pass  # 通知（notifications/initialized 等），无需应答
            elif method == "tools/list":
                _result(id, {"tools": TOOLS}, stdout)
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments") or {}
                handler = HANDLERS.get(name)
                if not handler:
                    _error(id, -32602, f"未知工具: {name}", stdout)
                    continue
                try:
                    text = handler(args)
                    _result(id, {"content": [{"type": "text", "text": text}]}, stdout)
                except Exception as exc:  # 工具级错误：isError 结果而非协议错误
                    _result(id, {"content": [{"type": "text", "text": _friendly(exc)}], "isError": True}, stdout)
            elif method == "ping":
                _result(id, {}, stdout)
            else:
                _error(id, -32601, f"不支持的方法: {method}", stdout)
        except Exception as exc:  # 协议层兜底，绝不让服务器崩掉断流
            if id is not None:
                _error(id, -32603, f"内部错误: {exc}", stdout)


if __name__ == "__main__":
    main()
