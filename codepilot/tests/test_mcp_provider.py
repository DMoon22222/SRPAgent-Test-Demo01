import json

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.mcp.provider import MCPToolProvider
from pico.tool_provider import BuiltinToolProvider


class FakeMCPClient:
    def __init__(self):
        self.calls = []
        self.cwds = []
        self.closed = 0

    def set_cwd(self, cwd):
        self.cwds.append(cwd)

    def list_tools(self):
        return [
            {
                "name": "echo",
                "description": "Echo a message.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            },
            {
                "name": "mutate",
                "description": "A risky operation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": f"{name}:{arguments}"}]}

    def close(self):
        self.closed += 1


def build_agent(tmp_path, outputs, client, approval_policy="auto"):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    provider = MCPToolProvider(
        "demo",
        client,
        read_only_tools={"echo"},
        workspace_cwd=True,
    )
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=approval_policy,
        tool_providers=[BuiltinToolProvider(), provider],
    )


def test_mcp_tool_schema_is_validated_before_the_server_is_called(tmp_path):
    client = FakeMCPClient()
    agent = build_agent(tmp_path, [], client)
    try:
        result = agent.execute_tool("mcp.demo.echo", {})

        assert "missing required argument: message" in result.content
        assert result.metadata["tool_error_code"] == "invalid_arguments"
        assert client.calls == []
    finally:
        agent.close()


def test_mcp_risky_tool_is_blocked_by_existing_approval_policy(tmp_path):
    client = FakeMCPClient()
    agent = build_agent(tmp_path, [], client, approval_policy="never")
    try:
        result = agent.execute_tool("mcp.demo.mutate", {"value": "change"})

        assert result.metadata["tool_error_code"] == "approval_denied"
        assert client.calls == []
    finally:
        agent.close()


def test_mcp_execution_is_recorded_in_existing_trace_and_report(tmp_path):
    client = FakeMCPClient()
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"mcp.demo.echo","args":{"message":"hello"}}</tool>',
            "<final>Done.</final>",
        ],
        client,
    )
    try:
        assert agent.ask("Use the MCP echo tool") == "Done."

        trace_path = agent.run_store.trace_path(agent.current_task_state.run_id)
        events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        tool_event = next(event for event in events if event["event"] == "tool_executed")
        report = agent.run_store.load_report(agent.current_task_state.run_id)

        assert tool_event["name"] == "mcp.demo.echo"
        assert tool_event["tool_status"] == "ok"
        assert tool_event["read_only"] is True
        assert report["prompt_metadata"]["tool_count"] == len(agent.tools)
        assert client.calls == [("echo", {"message": "hello"})]
    finally:
        agent.close()


def test_workspace_bound_mcp_provider_rebinds_after_workspace_switch(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    client = FakeMCPClient()
    agent = build_agent(first, [], client)
    try:
        agent.switch_workspace(second)

        assert client.cwds == [str(first.resolve()), str(second.resolve())]
        assert client.closed >= 1
    finally:
        agent.close()
