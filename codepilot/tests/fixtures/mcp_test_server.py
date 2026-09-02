"""用于 MCP Client 回归测试的标准 stdio Server。"""

from __future__ import annotations

import json
import sys
import time


FIRST_PAGE = [
    {
        "name": "echo",
        "description": "Return the provided message.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    }
]
SECOND_PAGE = [
    {
        "name": "mutate",
        "description": "A deliberately risky test tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    }
]


def result(request_id, value):
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def handle(request):
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    if method == "initialize":
        return result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-server", "version": "1"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        if not params.get("cursor"):
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "ready"}}), flush=True)
            return result(request_id, {"tools": FIRST_PAGE, "nextCursor": "page-2"})
        if params.get("cursor") == "page-2":
            return result(request_id, {"tools": SECOND_PAGE})
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "bad cursor"}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name == "echo":
            return result(request_id, {"content": [{"type": "text", "text": f"echo:{arguments.get('message', '')}"}]})
        if name == "tool_error":
            return result(request_id, {"content": [{"type": "text", "text": "test tool failed"}], "isError": True})
        if name == "invalid_json":
            print("not-json", flush=True)
            return None
        if name == "hang":
            time.sleep(2)
            return result(request_id, {"content": [{"type": "text", "text": "late"}]})
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown tool"}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown method"}}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        response = handle(json.loads(line))
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
