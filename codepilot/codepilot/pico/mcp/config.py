"""显式 MCP Server 配置的读取与校验。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import MCPServerConfig

SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SERVER_FIELDS = {"command", "cwd", "timeout_seconds", "read_only_tools"}


@dataclass(frozen=True)
class ConfiguredMCPServer:
    """一台经用户显式配置、可交给 MCPToolProvider 的本地 Server。"""

    server_id: str
    config: MCPServerConfig
    read_only_tools: frozenset[str]
    workspace_cwd: bool


def load_mcp_server_configs(
    config_path: str | Path,
    workspace_root: str | Path,
) -> list[ConfiguredMCPServer]:
    """加载 ``--mcp-config`` 指定的 JSON 文件。

    不会自动搜索工作区配置。启动外部进程只能来自用户显式提供的路径；
    配置中也不接受环境变量值，以免把 Token 写进项目文件。
    """
    path = Path(config_path).expanduser().resolve()
    workspace = Path(workspace_root).resolve()
    if not path.is_file():
        raise ValueError(f"MCP config file does not exist: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid MCP config JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise TypeError("MCP config must be a JSON object")
    if set(payload) != {"servers"}:
        raise ValueError("MCP config must contain only a 'servers' object")
    servers = payload["servers"]
    if not isinstance(servers, dict):
        raise TypeError("MCP config 'servers' must be an object")

    configured = []
    for server_id, raw_server in servers.items():
        configured.append(_parse_server(server_id, raw_server, workspace))
    return configured


def _parse_server(
    server_id: Any,
    raw_server: Any,
    workspace: Path,
) -> ConfiguredMCPServer:
    server_id = str(server_id)
    if not SERVER_ID_PATTERN.fullmatch(server_id):
        raise ValueError(f"invalid MCP server id: {server_id!r}")
    if not isinstance(raw_server, dict):
        raise TypeError(f"MCP server '{server_id}' must be an object")

    unknown_fields = sorted(set(raw_server) - SERVER_FIELDS)
    if unknown_fields:
        raise ValueError(
            f"MCP server '{server_id}' has unsupported fields: "
            f"{', '.join(unknown_fields)}"
        )

    command = raw_server.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item.strip() for item in command)
    ):
        raise ValueError(f"MCP server '{server_id}' command must be a non-empty string list")

    timeout_seconds = raw_server.get("timeout_seconds", 20)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
        raise ValueError(f"MCP server '{server_id}' timeout_seconds must be an integer from 1 to 300")

    cwd, workspace_cwd = _resolve_cwd(server_id, raw_server.get("cwd", "{workspace}"), workspace)
    read_only_tools = _read_only_tools(server_id, raw_server.get("read_only_tools", []))
    return ConfiguredMCPServer(
        server_id=server_id,
        config=MCPServerConfig(
            command=list(command),
            cwd=str(cwd),
            timeout_seconds=timeout_seconds,
        ),
        read_only_tools=frozenset(read_only_tools),
        workspace_cwd=workspace_cwd,
    )


def _resolve_cwd(server_id: str, value: Any, workspace: Path) -> tuple[Path, bool]:
    if value == "{workspace}":
        return workspace, True
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MCP server '{server_id}' cwd must be a path or '{{workspace}}'")
    if "{workspace}" in value:
        raise ValueError(f"MCP server '{server_id}' cwd must use '{{workspace}}' by itself")
    cwd = Path(value).expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"MCP server '{server_id}' cwd does not exist: {cwd}")
    return cwd, False


def _read_only_tools(server_id: str, value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(name, str) or not name.strip() for name in value):
        raise ValueError(f"MCP server '{server_id}' read_only_tools must be a string list")
    names = [name.strip() for name in value]
    if len(set(names)) != len(names):
        raise ValueError(f"MCP server '{server_id}' read_only_tools must not contain duplicates")
    return names
