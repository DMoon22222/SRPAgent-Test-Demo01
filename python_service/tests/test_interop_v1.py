from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import settings
from app.analyzer.error_analyzer import ErrorAnalyzer
from app.contracts.v1 import DiagnosticRequest, DiagnosticResult
from app.main import app
from app.sandbox.support import build_run_result, expected_output_matched
from app.schemas import ExecuteAndAnalyzeRequest
from app.services.diagnosis_service import DiagnosisService, ServiceError


def diagnostic_payload(operation="diagnose_error", code="print(10 / 0)\n"):
    payload = {
        "schemaVersion": "1.0", "operation": operation,
        "workflow": {"workflowId": "workflow-1", "requestId": "request-1", "iteration": 0, "producerAgentId": "generator"},
        "problem": {"description": "Handle division by zero."},
        "code": {"artifactId": "code-1", "revision": "r0", "language": "python", "entryPoint": "Main.py",
                 "files": [{"path": "Main.py", "content": code}]},
    }
    if operation == "diagnose_error":
        payload["feedback"] = {"runId": "run-1", "source": "EXTERNAL", "codeArtifactId": "code-1", "codeRevision": "r0",
                               "status": "RUNTIME_ERROR", "failedStage": "RUNTIME", "exitCode": 1,
                               "stderr": "ZeroDivisionError: division by zero"}
    elif operation == "execute_and_diagnose":
        payload["tests"] = {"suiteId": "tests-1", "revision": "r0", "origin": "PROVIDED",
                            "kind": "STDIO", "cases": [{"caseId": "empty", "stdin": "", "expectedOutput": ""}]}
    return payload


@pytest.fixture(autouse=True)
def no_external_model(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    monkeypatch.setattr(settings, "interop_api_token", "")
    monkeypatch.setattr(settings, "a2a_store_path", str(tmp_path / "tasks.sqlite3"))


@pytest.mark.parametrize("change", [
    lambda p: p.update(schemaVersion="2.0"),
    lambda p: p.update(command="arbitrary shell"),
    lambda p: p["code"]["files"][0].update(path="../Main.py"),
    lambda p: p["code"].update(entryPoint="Other.py"),
    lambda p: p["workflow"].update(iteration=True),
    lambda p: p["feedback"].update(source="B_SANDBOX"),
])
def test_reject_invalid_contract(change):
    payload = diagnostic_payload()
    change(payload)
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate(payload)


def test_test_suite_requires_expected_output_and_at_least_one_case():
    payload = diagnostic_payload("execute_and_diagnose")
    del payload["tests"]["cases"][0]["expectedOutput"]
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate(payload)
    payload["tests"]["cases"] = []
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate(payload)


def test_digest_preserves_exact_newlines_but_excludes_artifact_identity():
    request = DiagnosticRequest.model_validate(diagnostic_payload())
    other = request.code.model_copy(deep=True)
    other.artifactId = "other"
    assert other.digest() == request.code.digest()
    other.files[0].content = other.files[0].content.replace("\n", "\r\n")
    assert other.digest() != request.code.digest()


@pytest.mark.parametrize("field,value,code", [
    ("codeRevision", "r1", "CODE_VERSION_CONFLICT"),
    ("codeDigest", "sha256:" + "0" * 64, "CODE_DIGEST_CONFLICT"),
])
def test_reject_stale_feedback(field, value, code):
    payload = diagnostic_payload()
    payload["feedback"][field] = value
    with pytest.raises(ServiceError) as exc:
        DiagnosisService().process(DiagnosticRequest.model_validate(payload))
    assert exc.value.code == code


def test_rule_first_external_diagnosis_and_retrieval():
    payload = diagnostic_payload()
    result = DiagnosisService().process(DiagnosticRequest.model_validate(payload))
    assert result.diagnosis.analysisMode == "RULE_ONLY"
    assert result.diagnosis.errorSubtype == "DIVIDE_BY_ZERO"
    assert result.diagnosis.retrieval.decision == "NOT_REQUIRED"
    assert result.nextAction == "REPAIR"
    assert result.warnings
    assert result.diagnosis.suspectedLocations == []
    payload["feedback"]["stderr"] = "ModuleNotFoundError: No module named 'requests'"
    result = DiagnosisService().process(DiagnosticRequest.model_validate(payload))
    assert result.diagnosis.retrieval.decision == "REQUIRED"
    assert result.diagnosis.retrieval.query
    assert result.nextAction == "RETRIEVE_THEN_REPAIR"


def test_unknown_feedback_is_not_false_retrieval_decision():
    payload = diagnostic_payload()
    payload["feedback"].update(status="UNKNOWN", failedStage="UNKNOWN", stderr="", exitCode=-1)
    result = DiagnosisService().process(DiagnosticRequest.model_validate(payload))
    assert result.diagnosis.diagnosisStatus == "INSUFFICIENT_CONTEXT"
    assert result.diagnosis.retrieval.decision == "UNDETERMINED"
    assert result.nextAction == "PROVIDE_CONTEXT"


def fake_run(stdout="", stderr="", exit_code=0):
    def run(request):
        return build_run_result("python", request, {"stdout": stdout, "stderr": stderr, "exitCode": exit_code,
                                                    "timeout": False, "durationMs": 1}, True, "python Main.py")
    return run


def test_empty_expected_output_compared_without_changing_legacy():
    assert expected_output_matched("unexpected", "")
    assert not expected_output_matched("unexpected", "", required=True)
    payload = diagnostic_payload("execute_and_diagnose", "print('unexpected')")
    sandbox = Mock()
    sandbox.run.side_effect = fake_run(stdout="unexpected\n")
    result = DiagnosisService(sandbox=sandbox).process(DiagnosticRequest.model_validate(payload))
    assert result.execution.status == "WRONG_ANSWER"
    assert result.execution.summary.failed == 1
    assert result.nextAction == "REPAIR"


def test_success_and_syntax_only_have_distinct_next_actions():
    sandbox = Mock()
    sandbox.run.side_effect = fake_run()
    sandbox.check_syntax.return_value = fake_run()(ExecuteAndAnalyzeRequest(code="pass"))
    service = DiagnosisService(sandbox=sandbox)
    result = service.process(DiagnosticRequest.model_validate(diagnostic_payload("execute_and_diagnose", "pass")))
    assert result.nextAction == "ACCEPT"
    assert result.execution.summary.total == 1
    result = service.process(DiagnosticRequest.model_validate(diagnostic_payload("check_syntax", "pass")))
    assert result.nextAction == "RUN_TESTS"
    assert result.execution.validationScope == "SYNTAX_ONLY"
    assert result.execution.summary.total == 0


def test_test_digest_and_version_conflicts():
    payload = diagnostic_payload()
    payload["tests"] = diagnostic_payload("execute_and_diagnose")["tests"]
    payload["feedback"].update(testSuiteId="tests-1", testRevision="r0", testDigest="sha256:" + "0" * 64)
    with pytest.raises(ServiceError, match="test digest"):
        DiagnosisService().process(DiagnosticRequest.model_validate(payload))


def test_v1_http_error_and_legacy_compatibility():
    with TestClient(app) as client:
        response = client.post("/api/v1/diagnose", json=diagnostic_payload())
        assert response.status_code == 200
        DiagnosticResult.model_validate(response.json())
        assert client.get("/api/ping").status_code == 200
        assert client.post("/api/analyze-error", json={"errorLog": "ZeroDivisionError: division by zero"}).status_code == 200
        payload = diagnostic_payload()
        payload["feedback"]["codeRevision"] = "r1"
        response = client.post("/api/v1/diagnose", json=payload)
        assert response.status_code == 409
        assert response.json()["requestId"] == "request-1"
        assert response.json()["code"] == "CODE_VERSION_CONFLICT"
        payload["command"] = "private input not echoed"
        response = client.post("/api/v1/diagnose", json=payload)
        assert response.status_code == 422
        assert "private input" not in response.text
        assert client.get("/health/ready").json()["a2aTaskStoreReady"]
        assert "/api/v1/diagnose" in client.get("/openapi.json").json()["paths"]


def test_auth_and_remote_default_denial(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(settings, "interop_api_token", "test-token")
        assert client.post("/api/v1/diagnose", json=diagnostic_payload()).status_code == 401
        assert client.post("/api/v1/diagnose", json=diagnostic_payload(), headers={"Authorization": "Bearer test-token"}).status_code == 200
        assert client.get("/.well-known/agent-card.json").json()["securitySchemes"]
    monkeypatch.setattr(settings, "interop_api_token", "")
    with TestClient(app, client=("192.0.2.1", 1234)) as client:
        assert client.post("/api/v1/diagnose", json=diagnostic_payload()).status_code == 403
        assert client.post("/api/analyze-error", json={}).status_code == 403


def test_request_size_limit():
    with TestClient(app) as client:
        response = client.post("/api/v1/diagnose", content=b"x" * 1048577)
        assert response.status_code == 413


def test_local_execution_requires_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_mode", "local")
    monkeypatch.setattr(settings, "interop_allow_local_execution", False)
    with pytest.raises(ServiceError) as exc:
        DiagnosisService().process(DiagnosticRequest.model_validate(diagnostic_payload("check_syntax")))
    assert exc.value.code == "LOCAL_EXECUTION_DISABLED"


def test_real_local_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sandbox_mode", "local")
    monkeypatch.setattr(settings, "interop_allow_local_execution", True)
    monkeypatch.setenv("SANDBOX_TEMP_DIR", str(tmp_path))
    service = DiagnosisService()
    result = service.process(DiagnosticRequest.model_validate(diagnostic_payload("execute_and_diagnose", "print('unexpected')")))
    assert result.execution.status == "WRONG_ANSWER"
    result = service.process(DiagnosticRequest.model_validate(diagnostic_payload("check_syntax", "pass")))
    assert result.nextAction == "RUN_TESTS"


def test_cross_request_revision_and_test_freeze(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_mode", "local")
    monkeypatch.setattr(settings, "interop_allow_local_execution", True)
    with TestClient(app) as client:
        payload = diagnostic_payload("execute_and_diagnose", "pass")
        assert client.post("/api/v1/execute-and-diagnose", json=payload).status_code == 200
        payload["code"]["files"][0]["content"] = "print(1)"
        response = client.post("/api/v1/execute-and-diagnose", json=payload)
        assert response.status_code == 409
        assert response.json()["code"] == "CODE_REVISION_REUSED"
        payload["code"]["revision"] = "r1"
        payload["tests"]["cases"][0]["expectedOutput"] = "1"
        response = client.post("/api/v1/execute-and-diagnose", json=payload)
        assert response.status_code == 409
        assert response.json()["code"] == "TEST_SUITE_CHANGED"


def test_report_reference_checked_and_ids_not_idempotent():
    with TestClient(app) as client:
        payload = diagnostic_payload()
        first = client.post("/api/v1/diagnose", json=payload).json()
        second = client.post("/api/v1/diagnose", json=payload).json()
        assert first["diagnosis"]["reportId"] != second["diagnosis"]["reportId"]
        payload["workflow"]["previousReportId"] = first["diagnosis"]["reportId"]
        assert client.post("/api/v1/diagnose", json=payload).status_code == 200
        payload["workflow"]["workflowId"] = "another-workflow"
        response = client.post("/api/v1/diagnose", json=payload)
        assert response.status_code == 409
        assert response.json()["code"] == "REPORT_REFERENCE_CONFLICT"


def test_llm_fallback_mode_does_not_leak_sdk_errors(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "test-only")
    monkeypatch.setattr(ErrorAnalyzer, "_call_llm", lambda *args: {"rootCause": "SDK error containing private configuration"})
    result = DiagnosisService().process(DiagnosticRequest.model_validate(diagnostic_payload()))
    assert result.diagnosis.analysisMode == "RULE_ONLY"
    assert "private configuration" not in result.model_dump_json()
    monkeypatch.setattr(ErrorAnalyzer, "_call_llm", lambda *args: {"_llmSucceeded": True, "rootCause": "A zero divisor was used."})
    result = DiagnosisService().process(DiagnosticRequest.model_validate(diagnostic_payload()))
    assert result.diagnosis.analysisMode == "LLM_ASSISTED"
    assert result.diagnosis.errorSubtype == "DIVIDE_BY_ZERO"


def test_generated_examples_and_schemas_are_current():
    import json
    from pathlib import Path
    from app.contracts.export import examples
    root = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "v1"
    for filename, expected in examples().items():
        assert json.loads((root / filename).read_text(encoding="utf-8")) == expected
    schema = json.loads((root / "DiagnosticRequest.schema.json").read_text(encoding="utf-8"))
    schema.pop("$schema")
    assert schema == DiagnosticRequest.model_json_schema()
