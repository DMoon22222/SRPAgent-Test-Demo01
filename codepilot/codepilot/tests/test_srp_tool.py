import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.cli import _build_tool_providers
from pico.integrations import (
    SrpConnectionError,
    SrpHttpError,
    SrpResponseError,
    SrpTimeoutError,
    SrpToolProvider,
)
from pico.mcp.provider import MCPToolProvider
from pico.tool_provider import BuiltinToolProvider


class FakeSrpClient:
    def __init__(self, result=None, error=None, *, enabled=True):
        self.enabled = enabled
        self.result = result or success_response()
        self.error = error
        self.calls = []

    def execute_and_analyze(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class FakeMcpClient:
    def list_tools(self):
        return [
            {
                "name": "echo",
                "description": "Echo text.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            }
        ]

    def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": arguments["message"]}]}

    def close(self):
        pass


def success_response():
    return {
        "execution": {
            "success": True,
            "status": "SUCCESS",
            "failedStage": "NONE",
            "timeout": False,
            "exitCode": 0,
            "executionTimeMs": 12,
            "stdout": "5\n",
            "stderr": "",
            "errorLog": "",
        },
        "analysis": None,
    }


def failure_response(status, stage, subtype, **analysis_overrides):
    analysis = {
        "failedStage": stage,
        "errorType": status,
        "errorSubtype": subtype,
        "rootCause": f"root cause for {subtype}",
        "evidence": ["signal one", "signal two"],
        "suspectedLocation": "solution.py:1",
        "repairSuggestion": "repair this code",
        "needRetrieval": False,
        "retrievalQuery": "",
        "confidence": 0.9,
    }
    analysis.update(analysis_overrides)
    return {
        "execution": {
            "success": False,
            "status": status,
            "failedStage": stage,
            "timeout": False,
            "exitCode": 1,
            "executionTimeMs": 20,
            "stdout": "large raw stdout must not be returned",
            "stderr": "large raw stderr must not be returned",
            "errorLog": "large raw error log must not be returned",
            "observation": {
                "shortSummary": f"SRP observed {status}",
                "importantSignals": ["signal"],
                "nextActionHint": "inspect the diagnosis",
            },
        },
        "analysis": analysis,
    }


def build_agent(tmp_path, client, outputs=None, extra_providers=None):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    providers = [BuiltinToolProvider(), SrpToolProvider(client)]
    providers.extend(extra_providers or [])
    return Pico(
        model_client=FakeModelClient(outputs or []),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        tool_providers=providers,
    )


@pytest.mark.parametrize(("enabled", "visible"), [("false", False), ("true", True)])
def test_cli_srp_setting_controls_tool_visibility(tmp_path, enabled, visible):
    workspace = WorkspaceContext.build(tmp_path)
    args = SimpleNamespace(mcp_config=None)
    with patch.dict("os.environ", {"PICO_SRP_ENABLED": enabled}, clear=False):
        providers = _build_tool_providers(args, workspace)
        agent = Pico(
            model_client=FakeModelClient([]),
            workspace=workspace,
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            tool_providers=providers,
        )

    assert ("execute_and_diagnose" in agent.tools) is visible
    assert {"list_files", "read_file", "search", "run_shell", "write_file", "patch_file"} <= set(
        agent.tools
    )


def test_srp_provider_does_not_interfere_with_mcp_tools(tmp_path):
    mcp_provider = MCPToolProvider("demo", FakeMcpClient(), read_only_tools={"echo"})
    agent = build_agent(
        tmp_path,
        FakeSrpClient(),
        extra_providers=[mcp_provider],
    )

    assert "execute_and_diagnose" in agent.tools
    assert "mcp.demo.echo" in agent.tools
    assert agent.tools["mcp.demo.echo"]["risky"] is False


@pytest.mark.parametrize("language", ["python", "python3", "py"])
def test_python_file_is_read_and_aliases_are_normalized(tmp_path, language):
    (tmp_path / "solution.py").write_text("print(2 + 3)\n", encoding="utf-8")
    client = FakeSrpClient()
    agent = build_agent(tmp_path, client)

    result = agent.execute_tool(
        "execute_and_diagnose",
        {
            "path": "solution.py",
            "problem": "add numbers",
            "language": language,
            "stdin": "input",
            "expected_output": "5",
            "benchmark": "unit",
        },
    )

    assert result.metadata["tool_status"] == "ok"
    assert client.calls == [
        {
            "problem": "add numbers",
            "language": "python",
            "code": "print(2 + 3)\n",
            "stdin": "input",
            "expected_output": "5",
            "benchmark": "unit",
        }
    ]


def test_java_file_is_accepted(tmp_path):
    (tmp_path / "Main.java").write_text("class Main {}\n", encoding="utf-8")
    client = FakeSrpClient()
    agent = build_agent(tmp_path, client)

    result = agent.execute_tool(
        "execute_and_diagnose", {"path": "Main.java", "language": "java"}
    )

    assert result.metadata["tool_status"] == "ok"
    assert client.calls[0]["language"] == "java"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"path": ""}, "path must not be empty"),
        ({"path": "missing.py"}, "path does not exist"),
        ({"path": "source", "language": "python"}, "path is not a file"),
        ({"path": "solution.py", "language": "ruby"}, "language must be one of"),
        ({"path": "solution.py", "language": "java"}, "requires language=python"),
        ({"path": "Main.java", "language": "python"}, "requires language=java"),
    ],
)
def test_invalid_tool_arguments_are_rejected_before_srp_call(tmp_path, args, message):
    (tmp_path / "source").mkdir()
    (tmp_path / "solution.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "Main.java").write_text("class Main {}\n", encoding="utf-8")
    client = FakeSrpClient()
    agent = build_agent(tmp_path, client)

    result = agent.execute_tool("execute_and_diagnose", args)

    assert message in result.content
    assert result.metadata["tool_error_code"] == "invalid_arguments"
    assert client.calls == []


@pytest.mark.parametrize("path_value", ["../outside.py", "C:\\outside.py"])
def test_workspace_escape_is_rejected_by_existing_path_guard(tmp_path, path_value):
    client = FakeSrpClient()
    agent = build_agent(tmp_path, client)

    result = agent.execute_tool("execute_and_diagnose", {"path": path_value})

    assert "path escapes workspace" in result.content
    assert result.metadata["security_event_type"] == "path_escape"
    assert client.calls == []


def test_success_observation_accepts_null_analysis_and_omits_raw_logs(tmp_path):
    (tmp_path / "solution.py").write_text("print(5)\n", encoding="utf-8")
    agent = build_agent(tmp_path, FakeSrpClient())

    result = agent.execute_tool(
        "execute_and_diagnose", {"path": "solution.py", "language": "python"}
    )
    content = json.loads(result.content)

    assert content["success"] is True
    assert content["executionStatus"] == "SUCCESS"
    assert content["failedStage"] == "NONE"
    assert "diagnosis" not in content
    assert not {"stdout", "stderr", "errorLog"} & set(content)
    assert result.metadata["execution_isolated"] is True
    assert result.metadata["read_only"] is True


@pytest.mark.parametrize(
    ("status", "stage", "subtype"),
    [
        ("COMPILE_ERROR", "COMPILE", "SYNTAX_ERROR"),
        ("RUNTIME_ERROR", "RUNTIME", "DIVIDE_BY_ZERO"),
        ("WRONG_ANSWER", "TEST", "ALGORITHM_ERROR"),
    ],
)
def test_failure_diagnosis_is_preserved_without_reclassification(
    tmp_path, status, stage, subtype
):
    (tmp_path / "solution.py").write_text("bad_code()\n", encoding="utf-8")
    response = failure_response(status, stage, subtype)
    agent = build_agent(tmp_path, FakeSrpClient(response))

    result = agent.execute_tool(
        "execute_and_diagnose", {"path": "solution.py", "language": "python"}
    )
    content = json.loads(result.content)

    assert content["executionStatus"] == status
    assert content["failedStage"] == stage
    assert content["diagnosis"]["errorType"] == status
    assert content["diagnosis"]["errorSubtype"] == subtype
    assert content["diagnosis"]["rootCause"] == f"root cause for {subtype}"
    assert content["diagnosis"]["repairSuggestion"] == "repair this code"
    assert "large raw stdout" not in result.content
    assert result.metadata["execution_status"] == status
    assert result.metadata["error_subtype"] == subtype


def test_need_retrieval_signal_is_preserved_without_retrieval_call(tmp_path):
    (tmp_path / "solution.py").write_text("import missing\n", encoding="utf-8")
    response = failure_response(
        "RUNTIME_ERROR",
        "RUNTIME",
        "DEPENDENCY_MISSING",
        needRetrieval=True,
        retrievalQuery="how to install missing",
    )
    agent = build_agent(tmp_path, FakeSrpClient(response))

    result = agent.execute_tool("execute_and_diagnose", {"path": "solution.py"})
    diagnosis = json.loads(result.content)["diagnosis"]

    assert diagnosis["needRetrieval"] is True
    assert diagnosis["retrievalQuery"] == "how to install missing"
    assert result.metadata["need_retrieval"] is True


@pytest.mark.parametrize(
    ("error", "error_code", "available"),
    [
        (SrpConnectionError("refused"), "srp_unavailable", False),
        (SrpTimeoutError("slow"), "srp_timeout", False),
        (SrpHttpError(503, "down"), "srp_http_error", True),
        (SrpResponseError("invalid JSON"), "srp_response_error", True),
    ],
)
def test_srp_service_failures_are_not_user_code_failures(
    tmp_path, error, error_code, available
):
    (tmp_path / "solution.py").write_text("pass\n", encoding="utf-8")
    agent = build_agent(tmp_path, FakeSrpClient(error=error))

    result = agent.execute_tool("execute_and_diagnose", {"path": "solution.py"})
    content = json.loads(result.content)

    assert content["tool_status"] == "error"
    assert content["tool_error_code"] == error_code
    assert "executionStatus" not in content
    assert result.metadata["tool_status"] == "error"
    assert result.metadata["tool_error_code"] == error_code
    assert result.metadata["srp_available"] is available
