# 将MCP Server的远程工具转换为Pico内部统一Tool Spec
from __future__ import annotations

from functools import partial
from typing import Any

from .client import MCPClient
from .schema import prompt_schema, validate_arguments


class MCPToolProvider:
    def __init__(
        self,
        server_id: str,
        client: MCPClient,
        read_only_tools: set[str] | None = None,
        workspace_cwd: bool = False,
    ):
        self.name = f"mcp:{server_id}"
        self.server_id = server_id
        self.client = client
        self.read_only_tools = set(read_only_tools or set())
        self.workspace_cwd = bool(workspace_cwd)

    def discover(self, context) -> dict[str, dict[str, Any]]:
        tools: dict[str, dict[str, Any]] = {}
        if self.workspace_cwd:
            self.client.set_cwd(str(context.root))

        for remote_tool in self.client.list_tools():
            native_name = str(remote_tool.get("name", "")).strip()
            if not native_name:
                raise ValueError(f"MCP server '{self.server_id}' returned a tool without name")

            input_schema = remote_tool.get("inputSchema", {"type": "object", "properties": {}})
            if not isinstance(input_schema, dict):
                raise TypeError(f"MCP tool '{native_name}' inputSchema must be object")

            internal_name = f"mcp.{self.server_id}.{native_name}"
            if internal_name in tools:
                raise ValueError(f"MCP server '{self.server_id}' returned duplicate tool: {native_name}")
            tools[internal_name] = {
                "schema": prompt_schema(input_schema),
                "risky": native_name not in self.read_only_tools,
                "description": str(remote_tool.get("description", "")).strip() or f"MCP tool from {self.server_id}",
                "provider": self.name,
                "validate": partial(validate_arguments, input_schema),
                "run": partial(self.execute, native_name),
            }

        return tools

    def close(self) -> None:
        self.client.close()

    def execute(self, native_name: str, arguments: dict[str, Any]) -> str:
        result = self.client.call_tool(native_name, arguments)
        lines = []
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    lines.append(text)
        return "\n".join(lines) or "(MCP tool returned no text)"
