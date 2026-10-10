import argparse
import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

import httpx
import httpx2
import mcp_types as types
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from app.adapters.mcp.server import ToolAdapter
from app.adapters.mcp.stdio import RestBridge, service_url
from app.config import settings
from app.contracts.v1 import DiagnosticRequest, DiagnosticResult
from app.main import app
from app.services.diagnosis_service import DiagnosisService
from test_interop_v1 import diagnostic_payload


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    monkeypatch.setattr(settings, "interop_api_token", "")
    monkeypatch.setattr(settings, "a2a_store_path", str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(settings, "sandbox_mode", "local")
    monkeypatch.setattr(settings, "interop_allow_local_execution", True)
    monkeypatch.setenv("SANDBOX_TEMP_DIR", str(tmp_path / "sandbox"))
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield client


def modern_rpc(client, method, params=None, *, headers=None):
    params = dict(params or {})
    params.setdefault("_meta", {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    })
    request_headers = {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method, "Accept": "application/json, text/event-stream"}
    if "name" in params:
        request_headers["Mcp-Name"] = params["name"]
    request_headers.update(headers or {})
    return client.post("/mcp", headers=request_headers, json={"jsonrpc": "2.0", "id": "mcp-1", "method": method, "params": params})


def tool_call(client, payload):
    return modern_rpc(client, "tools/call", {"name": payload["operation"], "arguments": payload})


def test_modern_discovery_and_business_schemas(client):
    response = modern_rpc(client, "server/discover")
    assert response.status_code == 200, response.text
    assert "2026-07-28" in response.json()["result"]["supportedVersions"]
    listing = modern_rpc(client, "tools/list").json()["result"]
    assert {tool["name"] for tool in listing["tools"]} == {"diagnose_error", "execute_and_diagnose", "check_syntax"}
    for tool in listing["tools"]:
        Draft202012Validator.check_schema(tool["inputSchema"])
        Draft202012Validator.check_schema(tool["outputSchema"])
        assert tool["inputSchema"]["properties"]["operation"]["const"] == tool["name"]
        assert tool["outputSchema"] == DiagnosticResult.model_json_schema()


def test_code_failure_is_successful_tool_result_and_shares_rest_registry(client):
    payload = diagnostic_payload()
    rest = client.post("/api/v1/diagnose", json=payload).json()
    payload["workflow"]["previousReportId"] = rest["diagnosis"]["reportId"]
    response = tool_call(client, payload)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False
    data = DiagnosticResult.model_validate(result["structuredContent"])
    assert data.codeDigest == rest["codeDigest"]
    assert data.diagnosis.errorSubtype == "DIVIDE_BY_ZERO"
    assert data.nextAction == "REPAIR"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    schema = modern_rpc(client, "tools/list").json()["result"]["tools"][0]["outputSchema"]
    Draft202012Validator(schema).validate(result["structuredContent"])


def test_real_execution_failure_and_syntax_scope(client):
    result = tool_call(client, diagnostic_payload("execute_and_diagnose")).json()["result"]
    assert not result["isError"]
    assert result["structuredContent"]["execution"]["status"] == "RUNTIME_ERROR"
    payload = diagnostic_payload("check_syntax", "pass")
    payload["workflow"]["workflowId"] = "syntax-workflow"
    result = tool_call(client, payload).json()["result"]
    assert not result["isError"]
    assert result["structuredContent"]["nextAction"] == "RUN_TESTS"
    assert result["structuredContent"]["execution"]["summary"]["total"] == 0


def test_insufficient_context_is_business_result_not_mrtr(client):
    payload = diagnostic_payload()
    payload["feedback"].update(status="UNKNOWN", failedStage="UNKNOWN", stderr="", exitCode=-1)
    result = tool_call(client, payload).json()["result"]
    assert result["resultType"] == "complete"
    assert not result["isError"]
    assert result["structuredContent"]["nextAction"] == "PROVIDE_CONTEXT"


def test_environment_and_version_conflict_are_tool_errors(client, monkeypatch):
    monkeypatch.setattr(settings, "interop_allow_local_execution", False)
    result = tool_call(client, diagnostic_payload("check_syntax")).json()["result"]
    assert result["isError"]
    assert not result.get("structuredContent")
    assert json.loads(result["content"][0]["text"])["code"] == "LOCAL_EXECUTION_DISABLED"
    payload = diagnostic_payload()
    payload["feedback"]["codeRevision"] = "r1"
    result = tool_call(client, payload).json()["result"]
    assert result["isError"]
    assert json.loads(result["content"][0]["text"])["code"] == "CODE_VERSION_CONFLICT"


def test_validation_and_unknown_tool_are_protocol_errors(client):
    response = modern_rpc(client, "tools/call", {"name": "not-a-tool", "arguments": {}})
    assert response.json()["error"]["code"] == types.INVALID_PARAMS
    payload = diagnostic_payload()
    payload["command"] = "private input must not be echoed"
    response = tool_call(client, payload)
    assert response.json()["error"]["code"] == types.INVALID_PARAMS
    assert "private input" not in response.text
    response = modern_rpc(client, "tools/call", {"name": "check_syntax", "arguments": diagnostic_payload()})
    assert response.json()["error"]["code"] == types.INVALID_PARAMS
    assert modern_rpc(client, "nonexistent/method").json()["error"]["code"] == types.METHOD_NOT_FOUND


def test_mcp_auth_origin_host_and_size_limits(client, monkeypatch):
    monkeypatch.setattr(settings, "interop_api_token", "test-token")
    assert modern_rpc(client, "tools/list").status_code == 401
    good = {"Authorization": "Bearer test-token"}
    assert modern_rpc(client, "tools/list", headers=good).status_code == 200
    assert modern_rpc(client, "tools/list", headers={**good, "Origin": "https://untrusted.example"}).status_code == 403
    assert modern_rpc(client, "tools/list", headers={**good, "Host": "untrusted.example"}).status_code == 421
    assert client.post("/mcp", content=b"x" * 1048577, headers=good).status_code == 413
    monkeypatch.setattr(settings, "interop_api_token", "")
    remote = TestClient(app, client=("192.0.2.1", 1234), base_url="http://localhost:8000")
    try:
        assert modern_rpc(remote, "tools/list").status_code == 403
    finally:
        remote.close()


def test_modern_header_body_mismatch_rejected(client):
    assert modern_rpc(client, "tools/list", headers={"Mcp-Method": "tools/call"}).status_code == 400
    params = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2025-06-18",
                       "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1.0"},
                       "io.modelcontextprotocol/clientCapabilities": {}}}
    assert modern_rpc(client, "tools/list", params).status_code == 400


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25"])
def test_http_legacy_handshake_and_call(client, version):
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": version}
    response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "legacy-test", "version": "1.0"}}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["protocolVersion"] == version
    response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202
    response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "diagnose_error", "arguments": diagnostic_payload()}})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result["isError"]
    assert json.loads(result["content"][0]["text"])["nextAction"] == "REPAIR"


@pytest.mark.parametrize("mode", ["auto", "legacy", "2026-07-28"])
def test_official_sdk_streamable_http_client(client, mode):
    async def scenario():
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8000") as http:
            transport = streamable_http_client("http://localhost:8000/mcp", http_client=http)
            async with Client(transport, mode=mode, cache=None, read_timeout_seconds=5) as mcp:
                tools = await mcp.list_tools()
                assert len(tools.tools) == 3
                result = await mcp.call_tool("diagnose_error", diagnostic_payload())
                assert not result.is_error
                assert DiagnosticResult.model_validate(result.structured_content).nextAction == "REPAIR"
    client.portal.call(scenario)


def test_cancellation_keeps_worker_slot_until_work_stops(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    entered, release = Event(), Event()

    def slow(request, owner):
        entered.set()
        assert release.wait(5)
        return DiagnosisService().process(request)

    async def scenario():
        adapter = ToolAdapter(slow, workers=1, owner_resolver=lambda context: "test")
        params = types.CallToolRequestParams(name="diagnose_error", arguments=diagnostic_payload())
        try:
            job = asyncio.create_task(adapter.call_tool(None, params))
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set()
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
            busy = await adapter.call_tool(None, params)
            assert busy.is_error
            assert json.loads(busy.content[0].text)["code"] == "SERVICE_BUSY"
        finally:
            release.set()
            adapter.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("url", ["http://untrusted.example", "https://user:secret@host", "https://host/path", "https://host/?token=secret"])
def test_bridge_rejects_unsafe_service_origins(url):
    with pytest.raises(argparse.ArgumentTypeError):
        service_url(url)


def test_bridge_timeouts_are_not_retried():
    bridge = RestBridge("http://127.0.0.1:8000")
    bridge.client.close()
    count = []

    def timeout(request):
        count.append(request)
        raise httpx.ReadTimeout("sensitive upstream exception")

    bridge.client = httpx.Client(transport=httpx.MockTransport(timeout))
    try:
        adapter = ToolAdapter(bridge.process, owner_resolver=lambda context: "bridge")
        try:
            params = types.CallToolRequestParams(name="diagnose_error", arguments=diagnostic_payload())
            result = asyncio.run(adapter.call_tool(None, params))
            assert result.is_error
            assert json.loads(result.content[0].text)["code"] == "UPSTREAM_TIMEOUT"
            assert "sensitive upstream" not in result.content[0].text
            assert len(count) == 1
        finally:
            adapter.close()
    finally:
        bridge.close()


@pytest.fixture
def live_rest_service(tmp_path):
    directory = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "DASHSCOPE_API_KEY": "", "LLM_API_KEY": "", "INTEROP_API_TOKEN": "test-bridge-token",
           "A2A_STORE_PATH": str(tmp_path / "live.sqlite3"), "INTEROP_PUBLIC_URL": url,
           "SANDBOX_MODE": "local", "INTEROP_ALLOW_LOCAL_EXECUTION": "true", "SANDBOX_TEMP_DIR": str(tmp_path / "sandbox")}
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=directory, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        for _ in range(150):
            if process.poll() is not None:
                pytest.fail("Test HTTP service exited before becoming ready")
            try:
                if httpx.get(url + "/health/ready", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("Test HTTP service startup timed out")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_actual_codepilot_stdio_client(live_rest_service, monkeypatch):
    # Import the existing minimal client, not Pico's unrelated CLI/runtime dependencies.
    path = Path(__file__).resolve().parents[2] / "codepilot" / "codepilot" / "pico" / "mcp" / "client.py"
    spec = importlib.util.spec_from_file_location("srp_test_codepilot_mcp_client", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("B_AGENT_API_TOKEN", "test-bridge-token")
    directory = Path(__file__).resolve().parents[1]
    config = module.MCPServerConfig(command=[sys.executable, "-m", "app.adapters.mcp.stdio", "--url", live_rest_service],
                                   cwd=str(directory), timeout_seconds=20)
    client = module.MCPClient(config)
    try:
        assert len(client.list_tools()) == 3
        assert client.protocol_version == "2025-06-18"
        result = client.call_tool("diagnose_error", diagnostic_payload())
        assert DiagnosticResult.model_validate(result["structuredContent"]).nextAction == "REPAIR"
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
        payload = diagnostic_payload("check_syntax", "pass")
        payload["workflow"]["workflowId"] = "stdio-syntax-workflow"
        result = client.call_tool("check_syntax", payload)
        assert result["structuredContent"]["nextAction"] == "RUN_TESTS"
    finally:
        client.close()


def test_codepilot_configuration_contains_no_credentials():
    from app.adapters.mcp.codepilot_config import build_config
    config = build_config("https://diagnosis.example")
    server = config["servers"]["srp_b"]
    assert Path(server["cwd"]).is_dir()
    assert Path(server["command"][0]).is_file()
    assert server["read_only_tools"] == []
    assert server["timeout_seconds"] == 300
    assert "env" not in server
    assert "token" not in json.dumps(config).lower()


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_official_sdk_stdio_client(live_rest_service, mode):
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "app.adapters.mcp.stdio", "--url", live_rest_service],
        cwd=str(Path(__file__).resolve().parents[1]), env={"B_AGENT_API_TOKEN": "test-bridge-token", "PYTHONUTF8": "1"})

    async def scenario():
        async with Client(params, mode=mode, cache=None, read_timeout_seconds=10) as client:
            assert len((await client.list_tools()).tools) == 3
            result = await client.call_tool("diagnose_error", diagnostic_payload())
            assert not result.is_error
            assert DiagnosticResult.model_validate(result.structured_content).nextAction == "REPAIR"
    asyncio.run(scenario())


@pytest.mark.parametrize("protocol", ["rest", "a2a", "mcp"])
def test_mock_generation_diagnosis_repair_round_trip(live_rest_service, protocol):
    from app.clients.integration_demo import run
    result = asyncio.run(run(live_rest_service, "test-bridge-token", protocol))
    assert result["mockAgents"]
    assert result["rounds"][0]["status"] == "WRONG_ANSWER"
    assert result["rounds"][1]["nextAction"] == "ACCEPT"
    assert result["testSuiteUnchanged"]
    assert result["testsPassed"] == 2
