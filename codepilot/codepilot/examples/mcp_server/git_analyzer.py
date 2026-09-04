from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}

TOOLS = [
    {
        "name": "git_diff",
        "description": "Return the current Git diff; optionally limit to one path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "git_history",
        "description": "Return recent Git commits.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5, "enum": [1, 5, 10, 20]}},
            "required": [],
        },
    },
]


def text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def safe_path(raw_path: str) -> Path:
    path = (ROOT / raw_path).resolve()
    if ROOT not in path.parents and path != ROOT:
        raise ValueError("path escapes workspace")
    return path


def git_diff(arguments: dict) -> dict:
    command = ["git", "diff", "--"]
    raw_path = str(arguments.get("path", "")).strip()
    if raw_path:
        command.append(str(safe_path(raw_path).relative_to(ROOT)))
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if result.returncode != 0:
        return error(result.stderr.strip() or "git diff failed")
    return text_result(result.stdout.strip() or "(no diff)")


def git_history(arguments: dict) -> dict:
    limit = int(arguments.get("limit", 5))
    if limit not in {1, 5, 10, 20}:
        return error("limit must be one of 1, 5, 10, 20")
    result = subprocess.run(
        ["git", "log", f"-{limit}", "--oneline"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if result.returncode != 0:
        return error(result.stderr.strip() or "git log failed")
    return text_result(result.stdout.strip() or "(no commits)")


def handle(request: dict) -> dict:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    if method == "initialize":
        version = params.get("protocolVersion")
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "unsupported protocol version"},
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codepilot-git-analyzer", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            result = error("arguments must be an object")
        elif name == "git_diff":
            result = git_diff(arguments)
        elif name == "git_history":
            result = git_history(arguments)
        else:
            result = error(f"unknown tool: {name}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"unsupported method: {method}"}}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line))
        except (OSError, ValueError, TypeError) as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
