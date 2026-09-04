"""Phase 4 benchmark 的真实 stdio MCP Server。

它只提供可重复的 echo、错误和高风险写入场景；所有请求仍经由
MCPClient / MCPToolProvider / ToolExecutor，而不是测试替身直连。
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path.cwd().resolve()
TOOLS = [
    {
        "name": "echo",
        "description": "Return a message.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "tool_error",
        "description": "Return a controlled MCP tool error.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "invalid_json",
        "description": "Return invalid JSON for transport-error coverage.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "hang",
        "description": "Delay the response for timeout coverage.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "mutate",
        "description": "A deliberately risky write operation.",
        "inputSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    },
]


def response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def content(text, *, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle(request):
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialize":
        return response(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "phase4-test-server", "version": "1"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return response(request_id, {"tools": TOOLS})
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown method"}}

    name = params.get("name")
    arguments = params.get("arguments", {})
    if name == "echo":
        return response(request_id, content(f"echo:{arguments.get('message', '')}"))
    if name == "tool_error":
        return response(request_id, content("controlled tool error", is_error=True))
    if name == "invalid_json":
        print("this-is-not-json", flush=True)
        return None
    if name == "hang":
        time.sleep(1)
        return response(request_id, content("late response"))
    if name == "mutate":
        (ROOT / "mutation.marker").write_text(str(arguments.get("value", "")), encoding="utf-8")
        return response(request_id, content("mutation complete"))
    return response(request_id, content("unknown tool", is_error=True))


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        result = handle(json.loads(line))
        if result is not None:
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
