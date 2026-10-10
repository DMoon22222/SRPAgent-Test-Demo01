"""Generate language-neutral schemas and validated integration examples."""
import json
from pathlib import Path

from a2a.types import a2a_pb2 as pb
from google.protobuf.json_format import ParseDict

from app.contracts.v1 import (
    ApiError, CodeArtifact, DiagnosticRequest, DiagnosticResult, DiagnosisReport,
    ExecutionFeedback, TestSuite,
)
from app.adapters.mcp.server import tool_definitions


def examples():
    common = {
        "schemaVersion": "1.0",
        "workflow": {"workflowId": "srp-demo-001", "requestId": "request-001", "iteration": 0, "producerAgentId": "generation-agent"},
        "problem": {"description": "Print the sum of two input integers.", "constraints": [], "acceptanceCriteria": []},
        "code": {"artifactId": "code-001", "revision": "r0", "kind": "snippet", "language": "python", "entryPoint": "Main.py",
                 "files": [{"path": "Main.py", "content": "a, b = map(int, input().split())\nprint(a - b)\n"}]},
    }
    suite = {"suiteId": "suite-001", "revision": "r0", "origin": "PROVIDED", "kind": "STDIO",
             "cases": [{"caseId": "sum-positive", "stdin": "2 3\n", "expectedOutput": "5\n"}]}
    execution = {**common, "operation": "execute_and_diagnose", "tests": suite}
    syntax = {**common, "operation": "check_syntax"}
    diagnosis = {**common, "operation": "diagnose_error", "tests": suite, "feedback": {
        "runId": "run-001", "source": "EXTERNAL", "codeArtifactId": "code-001", "codeRevision": "r0",
        "codeDigest": CodeArtifact.model_validate(common["code"]).digest(),
        "testSuiteId": "suite-001", "testRevision": "r0", "testDigest": TestSuite.model_validate(suite).digest(),
        "status": "WRONG_ANSWER", "failedStage": "TEST", "exitCode": 0, "validationScope": "STDIO",
        "summary": {"total": 1, "passed": 0, "failed": 1, "timedOut": 0},
        "stdout": "-1\n", "stderr": "", "errorLog": "expectedOutput: 5; actualOutput: -1; output mismatch",
    }}
    for value in (execution, syntax, diagnosis):
        DiagnosticRequest.model_validate(value)
    a2a = {"jsonrpc": "2.0", "id": "rpc-001", "method": "SendMessage", "params": {
        "message": {"messageId": "message-001", "role": "ROLE_USER", "parts": [{"data": diagnosis, "mediaType": "application/json"}]},
        "configuration": {"returnImmediately": True},
    }}
    ParseDict(a2a["params"], pb.SendMessageRequest())
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "integration-client", "version": "1.0"},
            "io.modelcontextprotocol/clientCapabilities": {}}
    mcp_call = {"jsonrpc": "2.0", "id": "mcp-001", "method": "tools/call",
                "params": {"name": "diagnose_error", "arguments": diagnosis, "_meta": meta}}
    mcp_list = {"jsonrpc": "2.0", "id": "mcp-002", "method": "tools/list", "params": {"_meta": meta}}
    return {"diagnose-request.json": diagnosis, "execute-request.json": execution,
            "syntax-request.json": syntax, "a2a-send-message.json": a2a,
            "mcp-call-tool.json": mcp_call, "mcp-list-tools.json": mcp_list}


def main():
    root = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "v1"
    root.mkdir(parents=True, exist_ok=True)
    values = {model.__name__ + ".schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", **model.model_json_schema()}
              for model in (DiagnosticRequest, DiagnosticResult, CodeArtifact, TestSuite, ExecutionFeedback, DiagnosisReport, ApiError)}
    values.update(examples())
    values["mcp-tools.json"] = {"tools": [tool.model_dump(by_alias=True, mode="json", exclude_none=True) for tool in tool_definitions()]}
    for name, value in values.items():
        (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(values)} contract files to {root}")


if __name__ == "__main__":
    main()
