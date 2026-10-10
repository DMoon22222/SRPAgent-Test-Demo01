import asyncio
import time
from threading import Event
from uuid import uuid4

import httpx
import pytest
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.server.context import ServerCallContext
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import TaskNotFoundError
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict, ParseDict

from app.adapters.a2a.server import DiagnosisHandler, agent_card, data_to_contract
from app.config import settings
from app.contracts.v1 import DiagnosticResult
from app.main import app
from app.tasks.store import TaskStore
from test_interop_v1 import diagnostic_payload


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    monkeypatch.setattr(settings, "interop_api_token", "")
    monkeypatch.setattr(settings, "a2a_store_path", str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(settings, "a2a_workers", 1)
    with TestClient(app) as client:
        yield client


def rpc(client, method, params, *, version="1.0"):
    return client.post("/a2a", headers={"A2A-Version": version}, json={
        "jsonrpc": "2.0", "id": "rpc-1", "method": method, "params": params,
    }).json()


def send_params(payload=None, immediate=False, task_id=None, context_id=None):
    params = {"message": {"messageId": str(uuid4()), "role": "ROLE_USER",
                          "parts": [{"data": payload or diagnostic_payload(), "mediaType": "application/json"}]},
              "configuration": {"returnImmediately": immediate}}
    if task_id:
        params["message"]["taskId"] = task_id
    if context_id:
        params["message"]["contextId"] = context_id
    # Official SDK parsing validates that the example uses the actual 1.0 wire format.
    ParseDict(params, pb.SendMessageRequest())
    return params


def test_agent_card_and_blocking_send_result(client):
    data = client.get("/.well-known/agent-card.json").json()
    card = ParseDict(data, pb.AgentCard())
    assert card.supported_interfaces[0].protocol_version == "1.0"
    assert not card.capabilities.streaming
    assert not card.capabilities.push_notifications
    assert len(card.skills) == 3
    response = rpc(client, "SendMessage", send_params())
    assert "error" not in response, response
    result = ParseDict(response["result"], pb.SendMessageResponse())
    assert result.task.status.state == pb.TASK_STATE_COMPLETED
    assert result.task.id != "workflow-1"
    assert not result.task.history
    artifact = MessageToDict(result.task.artifacts[0].parts[0].data)
    assert artifact["nextAction"] == "REPAIR"
    assert artifact["execution"]["status"] == "RUNTIME_ERROR"
    fetched = rpc(client, "GetTask", {"id": result.task.id})["result"]
    assert fetched["artifacts"] == response["result"]["task"]["artifacts"]


@pytest.mark.parametrize("method,params,code", [
    ("GetTask", {"id": "missing"}, -32001),
    ("SubscribeToTask", {"id": "missing"}, -32004),
    ("GetExtendedAgentCard", {}, -32007),
    ("GetTaskPushNotificationConfig", {"taskId": "missing", "id": "one"}, -32003),
    ("message/send", {}, -32601),
])
def test_standard_errors(client, method, params, code):
    response = rpc(client, method, params)
    assert response["error"]["code"] == code, response


def test_wrong_version_and_invalid_payload(client):
    assert rpc(client, "SendMessage", send_params(), version="0.3")["error"]["code"] == -32009
    params = send_params()
    params["message"]["parts"][0] = {"text": "free text is not a DiagnosticRequest"}
    assert rpc(client, "SendMessage", params)["error"]["code"] == -32005
    params = send_params()
    params["message"]["parts"][0]["data"]["schemaVersion"] = "unknown"
    assert rpc(client, "SendMessage", params)["error"]["code"] == -32602


def test_input_required_continuation_and_terminal_immutability(client):
    payload = diagnostic_payload()
    payload["feedback"].update(status="UNKNOWN", failedStage="UNKNOWN", stderr="", exitCode=-1)
    task = rpc(client, "SendMessage", send_params(payload))["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    task = rpc(client, "SendMessage", send_params(task_id=task["id"], context_id=task["contextId"]))["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert rpc(client, "SendMessage", send_params(task_id=task["id"]))["error"]["code"] == -32004
    assert rpc(client, "CancelTask", {"id": task["id"]})["error"]["code"] == -32002
    repaired = diagnostic_payload(code="print(1)\n")
    repaired["code"]["revision"] = repaired["feedback"]["codeRevision"] = "r1"
    next_task = rpc(client, "SendMessage", send_params(repaired, context_id=task["contextId"]))["result"]["task"]
    assert next_task["id"] != task["id"]
    assert next_task["contextId"] == task["contextId"]


def test_task_pagination_and_filters(client):
    tasks = [rpc(client, "SendMessage", send_params())["result"]["task"] for _ in range(3)]
    listing = rpc(client, "ListTasks", {"pageSize": 2, "includeArtifacts": True})["result"]
    assert listing["totalSize"] == 3
    assert len(listing["tasks"]) == 2
    more = rpc(client, "ListTasks", {"pageSize": 2, "pageToken": listing["nextPageToken"]})["result"]
    assert len(more["tasks"]) == 1
    assert not more["tasks"][0].get("artifacts")
    filtered = rpc(client, "ListTasks", {"contextId": tasks[0]["contextId"]})["result"]
    assert len(filtered["tasks"]) == 1
    assert rpc(client, "ListTasks", {"pageToken": "broken"})["error"]["code"] == -32602


def test_async_poll_and_queued_cancel_without_stopping_running_thread(client, monkeypatch):
    entered, release = Event(), Event()
    original = app.state.a2a_handler.service.process
    calls = []

    def slow(request, owner):
        calls.append(request.workflow.requestId)
        entered.set()
        assert release.wait(5)
        return original(request, owner)

    monkeypatch.setattr(app.state.a2a_handler.service, "process", slow)
    try:
        first = rpc(client, "SendMessage", send_params(immediate=True))["result"]["task"]
        assert entered.wait(2)
        assert rpc(client, "GetTask", {"id": first["id"]})["result"]["status"]["state"] == "TASK_STATE_WORKING"
        assert rpc(client, "CancelTask", {"id": first["id"]})["error"]["code"] == -32002
        second = rpc(client, "SendMessage", send_params(immediate=True))["result"]["task"]
        canceled = rpc(client, "CancelTask", {"id": second["id"]})["result"]
        assert canceled["status"]["state"] == "TASK_STATE_CANCELED"
    finally:
        release.set()
    for _ in range(100):
        completed = rpc(client, "GetTask", {"id": first["id"]})["result"]
        if completed["status"]["state"] == "TASK_STATE_COMPLETED":
            break
        time.sleep(0.01)
    assert completed["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(calls) == 1
    assert rpc(client, "GetTask", {"id": second["id"]})["result"]["status"]["state"] == "TASK_STATE_CANCELED"


def test_restart_preserves_results_and_marks_interrupted_jobs_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    path = tmp_path / "persistent.sqlite3"
    store = TaskStore(path)
    store.open()
    task = pb.Task(id="interrupted", context_id="ctx", status=pb.TaskStatus(state=pb.TASK_STATE_WORKING))
    store.insert(task, "owner", "{}")
    store.close()

    async def scenario():
        handler = DiagnosisHandler(store=TaskStore(path))
        await handler.start()
        try:
            assert handler.store.get("interrupted", "owner")[0].status.state == pb.TASK_STATE_FAILED
            with pytest.raises(TaskNotFoundError):
                await handler.on_get_task(pb.GetTaskRequest(id="interrupted"), ServerCallContext(state={"principal": "other"}))
        finally:
            await handler.close()
    asyncio.run(scenario())


def test_completed_artifacts_survive_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    path = tmp_path / "completed.sqlite3"
    context = ServerCallContext(state={"principal": "owner"})

    async def scenario():
        first = DiagnosisHandler(store=TaskStore(path))
        await first.start()
        try:
            task = await first.on_message_send(ParseDict(send_params(), pb.SendMessageRequest()), context)
        finally:
            await first.close()
        second = DiagnosisHandler(store=TaskStore(path))
        await second.start()
        try:
            restored = await second.on_get_task(pb.GetTaskRequest(id=task.id), context)
            assert restored.status.state == pb.TASK_STATE_COMPLETED
            assert restored.artifacts == task.artifacts
        finally:
            await second.close()
    asyncio.run(scenario())


def test_official_sdk_client_can_call_and_poll(client):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"A2A-Version": "1.0"}) as http:
            transport = JsonRpcTransport(http, agent_card(), "http://testserver/a2a")
            response = await transport.send_message(ParseDict(send_params(), pb.SendMessageRequest()))
            assert response.task.status.state == pb.TASK_STATE_COMPLETED
            business = data_to_contract(response.task.artifacts[0].parts[0].data, DiagnosticResult)
            assert business.nextAction == "REPAIR"
            fetched = await transport.get_task(pb.GetTaskRequest(id=response.task.id))
            assert fetched.artifacts[0] == response.task.artifacts[0]
            tasks = await transport.list_tasks(pb.ListTasksRequest(include_artifacts=True))
            assert tasks.total_size == 1
    asyncio.run(scenario())
