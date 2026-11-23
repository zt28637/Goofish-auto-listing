"""影刀编辑器 studio-mcp 客户端（本地真源读取）

影刀编辑器运行时在本机开一个 Streamable-HTTP MCP 服务（EmbedIO），
Copilot 就是用它读写流程画布。这里复用同一接口，把"真源"指令块
拉成纯文本清单——不解密、不逆向，走的官方本地接口。

用法:
    python sb_mcp.py                      # 列出编辑器当前应用的全部流程
    python sb_mcp.py blocks <flow名>       # 打印某流程的指令块原文(json)
"""

import json
import re
import urllib.request

_LOG_DIR = r"C:\Users\Admin\AppData\Local\ShadowBot\log"
_MCP_PATH = "/api/v1/mcp"


def _mcp_alive(port: int) -> bool:
    """对候选端口做一次 MCP initialize 握手，通了才算。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1.0"},
        },
    }
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{_MCP_PATH}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return b"serverInfo" in resp.read()
    except Exception:
        return False


def discover_port() -> int:
    """从影刀日志里收集候选端口并逐一握手，找到编辑器当前的 MCP 端口。"""
    import glob
    import os

    logs = sorted(glob.glob(os.path.join(_LOG_DIR, "*.log")), key=os.path.getmtime, reverse=True)
    candidates: list[int] = []
    for lg in logs[:12]:   # 引擎/桥日志会把消息日志挤出前3，扫描范围放宽
        with open(lg, "rb") as f:
            data = f.read()
        for p in reversed(re.findall(rb"127\.0\.0\.1:(\d{4,5})", data)):
            port = int(p)
            if port not in candidates:
                candidates.append(port)
    for port in candidates:
        if _mcp_alive(port):
            return port
    raise RuntimeError("未发现影刀编辑器 MCP 端口——请确认编辑器已启动并停在应用页")


def call(tool: str, arguments: dict | None = None, port: int | None = None, timeout: int = 60):
    """调用一个 studio-mcp 工具，返回解析后的 JSON 内容。"""
    port = port or discover_port()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{_MCP_PATH}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    # 兼容 SSE 帧：data: {...}
    for line in body.splitlines():
        if line.startswith("data:"):
            body = line[5:].strip()
            break
    rpc = json.loads(body)
    if "error" in rpc:
        raise RuntimeError(f"{tool}: {rpc['error']}")
    content = rpc["result"]["content"][0]["text"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


# ---- 应用身份门 -----------------------------------------------------------
# 影刀编辑器一次只开一个应用，而 app.list_flows / flow.blocks.list 都不区分应用：
# 开着别家应用时照样返回别家流程。读画布的工具必须先确认开的是本仓应用，否则会
# 拿别家画布判本仓不一致（2026-11-23：编辑器停在项目一应用，本仓闸门误报 main 83→16，
# 并准备把 process6~9 导进 project/canvas/）。
EXPECTED_APP_NAME = "自动化上架"   # 本应用 package.json 的 name


def current_app_name(port: int | None = None) -> str:
    """当前编辑器打开的应用名；读不到返回空串（不当成错误）。"""
    try:
        r = call("app.get_info", {}, port, timeout=10)
    except Exception:
        return ""
    meta = r.get("metadata") if isinstance(r, dict) else None
    return (meta or {}).get("name", "") or ""


def wrong_app(port: int | None = None) -> str | None:
    """None=应用正确或无法判定；否则返回当前打开的那个应用名。"""
    name = current_app_name(port)
    return None if not name or name == EXPECTED_APP_NAME else name


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    port = discover_port()
    print(f"[mcp port] {port}")
    print(f"[app] {current_app_name(port)}（本仓应为 {EXPECTED_APP_NAME}）")
    if len(sys.argv) >= 2 and sys.argv[1] == "blocks":
        print(json.dumps(call("flow.blocks.list", {"flow": sys.argv[2]}, port), ensure_ascii=False, indent=1)[:6000])
    else:
        print(json.dumps(call("app.list_flows", {}, port), ensure_ascii=False, indent=1))
