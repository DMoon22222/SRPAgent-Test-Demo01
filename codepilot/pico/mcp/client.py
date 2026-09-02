"""Pico 与本地 stdio MCP Server 的最小客户端。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from queue import Empty, Queue
from threading import Thread
from typing import Any

SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"2024-11-05", "2025-03-26", "2025-06-18"}
)
PREFERRED_PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "codepilot", "version": "0.1.0"}


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPServerConfig:
    command: list[str]
    cwd: str | None = None
    timeout_seconds: int = 20


class MCPClient:
    """仅支持本地 stdio、工具发现与工具调用所需的最小 MCP 生命周期。"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._initialized = False
        self.protocol_version = ""
        self.server_capabilities: dict[str, Any] = {}

    def set_cwd(self, cwd: str) -> None:
        """在工作区切换后重启 Server，避免继续操作旧工作区。"""
        cwd = str(cwd)
        if self.config.cwd == cwd:
            return
        self.close()
        self.config = replace(self.config, cwd=cwd)

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        try:
            self._process = subprocess.Popen(
                self.config.command,
                cwd=self.config.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # Server stderr 不是 MCP 协议通道；丢弃它既避免管道阻塞，也避免
                # 将第三方 Server 可能写入的敏感诊断内容带进 Agent trace。
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            self._process = None
            raise MCPError(f"failed to start MCP server: {exc}") from exc

        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        self._initialized = False
        self.protocol_version = ""
        self.server_capabilities = {}
        if process is None:
            return

        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors = set()
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            result = self.request("tools/list", params)
            page = result.get("tools")
            if not isinstance(page, list):
                raise MCPError("MCP tools/list response has no valid tools list")
            tools.extend(page)
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise MCPError("MCP tools/list returned an invalid nextCursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

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
        return self._request(method, params)

    def _initialize(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PREFERRED_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        version = result.get("protocolVersion")
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise MCPError(f"unsupported MCP protocol version: {version!r}")
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
            raise MCPError("MCP server did not declare tools capability")

        self.protocol_version = version
        self.server_capabilities = dict(capabilities)
        self._initialized = True
        self._send_notification("notifications/initialized")

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise MCPError("MCP server stdio is unavailable")

        request_id = self._next_id
        self._next_id += 1
        self._write_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        while True:
            line = self._readline_with_timeout()
            if not line:
                self.close()
                raise MCPError("MCP server exited before replying")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MCPError(f"MCP server returned invalid JSON: {line!r}") from exc
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                raise MCPError("MCP server returned an invalid JSON-RPC response")

            # 日志、进度和 tools/list_changed 等 notification 不属于当前请求；
            # 第一版无需消费其语义，但也不能把它们误判成响应 ID 错误。
            if "id" not in response:
                continue
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

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        self._write_message(payload)

    def _write_message(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise MCPError("MCP server stdin is unavailable")
        try:
            self._process.stdin.write(json.dumps(payload) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError("MCP server closed stdin") from exc

    def _readline_with_timeout(self) -> str:
        if self._process is None or self._process.stdout is None:
            raise MCPError("MCP server stdout is unavailable")

        stdout = self._process.stdout
        results: Queue[tuple[str | None, BaseException | None]] = Queue(maxsize=1)

        def read_line() -> None:
            try:
                results.put((stdout.readline(), None))
            except (OSError, ValueError) as exc:
                results.put((None, exc))

        reader = Thread(target=read_line, daemon=True)
        reader.start()

        try:
            line, error = results.get(timeout=self.config.timeout_seconds)
        except Empty as exc:
            self.close()
            raise MCPError(f"MCP request timed out after {self.config.timeout_seconds}s") from exc

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
