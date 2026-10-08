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
    for lg in logs[:3]:
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


def call(tool: str, arguments: dict | None = None, port: int | None = None):
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
    with urllib.request.urlopen(req, timeout=60) as resp:
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


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    port = discover_port()
    print(f"[mcp port] {port}")
    if len(sys.argv) >= 2 and sys.argv[1] == "blocks":
        print(json.dumps(call("flow.blocks.list", {"flow": sys.argv[2]}, port), ensure_ascii=False, indent=1)[:6000])
    else:
        print(json.dumps(call("app.list_flows", {}, port), ensure_ascii=False, indent=1))
