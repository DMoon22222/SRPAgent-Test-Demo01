import sys
from pathlib import Path

import pytest

from pico.mcp import MCPClient, MCPError, MCPServerConfig

SERVER_PATH = Path(__file__).parent / "fixtures" / "mcp_test_server.py"


def build_client(tmp_path, timeout_seconds=2):
    return MCPClient(
        MCPServerConfig(
            command=[sys.executable, str(SERVER_PATH)],
            cwd=str(tmp_path),
            timeout_seconds=timeout_seconds,
        )
    )


def test_client_initializes_ignores_notifications_and_collects_tool_pages(tmp_path):
    client = build_client(tmp_path)
    try:
        tools = client.list_tools()

        assert client.protocol_version == "2025-06-18"
        assert [tool["name"] for tool in tools] == ["echo", "mutate"]
        assert client.call_tool("echo", {"message": "hello"})["content"] == [
            {"type": "text", "text": "echo:hello"}
        ]
    finally:
        client.close()


def test_client_surfaces_tool_errors_and_invalid_json(tmp_path):
    client = build_client(tmp_path)
    try:
        with pytest.raises(MCPError, match="test tool failed"):
            client.call_tool("tool_error", {})
        with pytest.raises(MCPError, match="invalid JSON"):
            client.call_tool("invalid_json", {})
    finally:
        client.close()


def test_client_times_out_and_closes_the_server(tmp_path):
    client = build_client(tmp_path, timeout_seconds=1)

    with pytest.raises(MCPError, match="timed out"):
        client.call_tool("hang", {})

    assert client._process is None
