#作用：实现Pico与MCP Server的最小通信层

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Any


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPServerConfig:
    command: list[str]
    cwd: str | None = None
    timeout_seconds: int = 20


class MCPClient:
    """仅支持 stdio transport、tools/list、tools/call。"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            self.config.command,
            cwd=self.config.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise MCPError("MCP tools/list response has no valid tools list")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if result.get("isError") is True:
            raise MCPError(self._content_to_text(result) or f"MCP tool '{name}' failed")
        return result

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.start()
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise MCPError("MCP server stdio is unavailable")

        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}

        try:
            self._process.stdin.write(json.dumps(payload) + "\n")
            self._process.stdin.flush()
        except BrokenPipeError as exc:
            raise MCPError("MCP server closed stdin") from exc

        line = self._readline_with_timeout()

        if not line:
            self.close()
            raise MCPError("MCP server exited before replying")

        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP server returned invalid JSON: {line!r}") from exc

        if response.get("id") != request_id:
            raise MCPError("MCP response id does not match request id")
        if "error" in response:
            error = response["error"]
            message = error.get("message", "unknown MCP error") if isinstance(error, dict) else str(error)
            raise MCPError(message)

        result = response.get("result")
        if not isinstance(result, dict):
            raise MCPError("MCP response result must be an object")
        return result

    def _readline_with_timeout(self) -> str:
        if self._process is None or self._process.stdout is None:
            raise MCPError("MCP server stdout is unavailable")

        results: Queue[tuple[str | None, BaseException | None]] = Queue(maxsize=1)

        def read_line() -> None:
            try:
                results.put((self._process.stdout.readline(), None))
            except BaseException as exc:
                results.put((None, exc))

        reader = Thread(target=read_line, daemon=True)
        reader.start()

        try:
            line, error = results.get(
                timeout=self.config.timeout_seconds,
            )
        except Empty as exc:
            self.close()
            raise MCPError(
                f"MCP request timed out after "
                f"{self.config.timeout_seconds}s"
            ) from exc

        if error is not None:
            raise MCPError(f"MCP server stdout read failed: {error}") from error

        return line or ""

    @staticmethod
    def _content_to_text(result: dict[str, Any]) -> str:
        parts = []
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
