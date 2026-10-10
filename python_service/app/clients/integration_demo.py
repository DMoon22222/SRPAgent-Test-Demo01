"""A protocol smoke workflow with mock generation/repair, not real external agents."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import httpx2
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import a2a_pb2 as pb
from google.protobuf.json_format import ParseDict
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.adapters.a2a.server import data_to_contract
from app.adapters.mcp.stdio import service_url
from app.config import settings
from app.contracts.v1 import DiagnosticRequest, DiagnosticResult


def workflow_requests():
    workflow_id = "smoke-" + uuid4().hex
    return DiagnosticRequest.model_validate({
        "schemaVersion": "1.0", "operation": "execute_and_diagnose",
        "workflow": {"workflowId": workflow_id, "requestId": uuid4().hex, "iteration": 0, "producerAgentId": "mock-generator"},
        "problem": {"description": "Print the sum of two input integers."},
        "code": {"artifactId": "demo-code", "revision": "r0", "kind": "snippet", "language": "python", "entryPoint": "Main.py",
                 "files": [{"path": "Main.py", "content": "a, b = map(int, input().split())\nprint(a - b)\n"}]},
        "tests": {"suiteId": "demo-tests", "revision": "r0", "kind": "STDIO", "origin": "PROVIDED", "cases": [
            {"caseId": "positive", "stdin": "2 3\n", "expectedOutput": "5\n"},
            {"caseId": "negative", "stdin": "-2 3\n", "expectedOutput": "1\n"},
        ]},
    })


def repaired_request(original, report):
    repaired = original.model_copy(deep=True)
    repaired.workflow.requestId = uuid4().hex
    repaired.workflow.producerAgentId = "mock-repair-agent"
    repaired.workflow.iteration = 1
    repaired.workflow.previousReportId = report.reportId
    repaired.code.revision = "r1"
    repaired.code.files[0].content = "a, b = map(int, input().split())\nprint(a + b)\n"
    return repaired


@asynccontextmanager
async def connection(url, token, protocol):
    headers = {"Authorization": "Bearer " + token} if token else {}
    if protocol == "mcp":
        async with httpx2.AsyncClient(headers=headers, timeout=300, trust_env=False) as http:
            transport = streamable_http_client(url + "/mcp", http_client=http)
            async with Client(transport, read_timeout_seconds=300, cache=None) as client:
                async def call(request):
                    result = await client.call_tool(request.operation, request.model_dump(mode="json"))
                    if result.is_error:
                        raise RuntimeError("MCP tool failed: " + "; ".join(item.text for item in result.content if item.type == "text"))
                    return DiagnosticResult.model_validate(result.structured_content)
                yield call
    else:
        async with httpx.AsyncClient(headers=headers, timeout=300, follow_redirects=False, trust_env=False) as http:
            if protocol == "rest":
                async def call(request):
                    response = await http.post(url + "/api/v1/execute-and-diagnose", json=request.model_dump(mode="json"))
                    if response.status_code != 200:
                        raise RuntimeError(f"REST rejected request with HTTP {response.status_code}: {response.text[:4096]}")
                    return DiagnosticResult.model_validate(response.json())
            else:
                http.headers["A2A-Version"] = "1.0"
                response = await http.get(url + "/.well-known/agent-card.json")
                response.raise_for_status()
                card = ParseDict(response.json(), pb.AgentCard())
                client = JsonRpcTransport(http, card, url + "/a2a")
                context_id = None

                async def call(request):
                    nonlocal context_id
                    message = {"messageId": uuid4().hex, "role": "ROLE_USER",
                               "parts": [{"mediaType": "application/json", "data": request.model_dump(mode="json")}]}
                    if context_id:
                        message["contextId"] = context_id
                    sent = await client.send_message(ParseDict({"message": message, "configuration": {"returnImmediately": True}}, pb.SendMessageRequest()))
                    if not sent.HasField("task"):
                        raise RuntimeError("A2A did not return a task")
                    task = sent.task
                    context_id = task.context_id
                    deadline = asyncio.get_running_loop().time() + 300
                    while task.status.state in {pb.TASK_STATE_SUBMITTED, pb.TASK_STATE_WORKING}:
                        if asyncio.get_running_loop().time() >= deadline:
                            raise RuntimeError("A2A polling timed out; task may still be running. No resubmission was made")
                        await asyncio.sleep(0.1)
                        task = await client.get_task(pb.GetTaskRequest(id=task.id))
                    if task.status.state != pb.TASK_STATE_COMPLETED or not task.artifacts:
                        raise RuntimeError("A2A did not complete the diagnostic operation: " + pb.TaskState.Name(task.status.state))
                    return data_to_contract(task.artifacts[0].parts[0].data, DiagnosticResult)
            yield call


async def run(url, token, protocol):
    original = workflow_requests()
    async with connection(service_url(url), token, protocol) as call:
        first = await call(original)
        if not first.diagnosis or first.execution.status != "WRONG_ANSWER":
            raise RuntimeError("Mock faulty source did not produce the expected diagnosed output mismatch")
        repaired = repaired_request(original, first.diagnosis)
        second = await call(repaired)
        if (second.nextAction != "ACCEPT" or second.execution.summary.passed != 2
                or second.testDigest != first.testDigest or second.codeDigest == first.codeDigest):
            raise RuntimeError("Repair did not pass the original fixed test suite")
        return {
            "protocol": protocol, "workflowId": original.workflow.workflowId, "mockAgents": True,
            "rounds": [{"revision": first.codeRevision, "status": first.execution.status, "nextAction": first.nextAction},
                       {"revision": second.codeRevision, "status": second.execution.status, "nextAction": second.nextAction}],
            "testSuiteUnchanged": True, "testsPassed": second.execution.summary.passed,
        }


def main():
    parser = argparse.ArgumentParser(description="Mock generation/repair round trip through the real B Agent service")
    parser.add_argument("--url", type=service_url, default="http://127.0.0.1:8000")
    parser.add_argument("--protocol", choices=("rest", "a2a", "mcp"), default="rest")
    args = parser.parse_args()
    token = os.environ.get("B_AGENT_API_TOKEN", settings.interop_api_token)
    print(json.dumps(asyncio.run(run(args.url, token, args.protocol)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
