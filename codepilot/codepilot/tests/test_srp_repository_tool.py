import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pico.integrations import SrpConnectionError, SrpHttpError, SrpToolProvider


class FakeClient:
    def __init__(self, result=None, error=None, enabled=True):
        self.enabled = enabled
        self.result = result or repository_response()
        self.error = error
        self.calls = []

    def execute_repository(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def repository_response(status="SUCCESS", analysis=None):
    success = status == "SUCCESS"
    return {
        "execution": {
            "success": success,
            "status": status,
            "failedStage": "NONE" if success else "TEST",
            "runner": "pytest",
            "timeout": status == "TIME_LIMIT_EXCEEDED",
            "exitCode": 0 if success else 1,
            "executionTimeMs": 24,
            "summary": {"total": 2, "passed": 1, "failed": 1, "skipped": 0},
            "failures": [
                {
                    "testId": "tests/test_demo.py::test_value",
                    "location": "tests/test_demo.py:7",
                    "message": "assert 4 == 5",
                    "excerpt": "X" * 2000,
                }
            ],
            "stdout": "RAW STDOUT MUST NOT LEAK",
            "stderr": "RAW STDERR MUST NOT LEAK",
            "observation": {
                "shortSummary": "one test failed",
                "importantSignals": ["assertion mismatch"],
                "failingTests": ["tests/test_demo.py::test_value"],
                "nextActionHint": "inspect failure",
            },
        },
        "analysis": analysis,
    }


def context(tmp_path):
    return SimpleNamespace(root=tmp_path.resolve())


def test_repository_tool_is_discovered_without_workspace_path_schema(tmp_path):
    tools = SrpToolProvider(FakeClient()).discover(context(tmp_path))
    spec = tools["execute_repository_and_diagnose"]
    assert set(spec["schema"]) == {"test_targets", "timeout_seconds", "benchmark"}
    assert "workspace" not in json.dumps(spec["schema"]).lower()


def test_disabled_srp_hides_both_tools(tmp_path):
    assert SrpToolProvider(FakeClient(enabled=False)).discover(context(tmp_path)) == {}


def test_repository_tool_passes_canonical_root_and_internal_pytest_contract(tmp_path):
    client = FakeClient()
    provider = SrpToolProvider(client)
    result = provider.execute_repository(
        context(tmp_path),
        {"test_targets": ["tests/test_demo.py"], "timeout_seconds": 33},
    )
    assert client.calls == [
        {
            "workspace_path": str(Path(tmp_path).resolve()),
            "test_targets": ["tests/test_demo.py"],
            "timeout_seconds": 33,
            "benchmark": "",
        }
    ]
    assert result.metadata["execution_status"] == "SUCCESS"


@pytest.mark.parametrize(
    "args,message",
    [
        ({"workspace_path": "C:/escape"}, "unsupported arguments"),
        ({"runner": "shell"}, "unsupported arguments"),
        ({"test_targets": "tests"}, "list of non-empty strings"),
        ({"test_targets": [""]}, "list of non-empty strings"),
        ({"timeout_seconds": True}, "must be an integer"),
        ({"timeout_seconds": 0}, "between 1 and 600"),
        ({"timeout_seconds": 601}, "between 1 and 600"),
        ({"benchmark": 123}, "must be a string"),
    ],
)
def test_repository_tool_validation_rejects_unsafe_or_invalid_args(args, message):
    with pytest.raises((TypeError, ValueError), match=message):
        SrpToolProvider.validate_repository(args)


def test_repository_failure_observation_is_compact_and_keeps_diagnosis(tmp_path):
    analysis = {
        "errorType": "WRONG_ANSWER",
        "errorSubtype": "ALGORITHM_ERROR",
        "rootCause": "incorrect result",
        "evidence": ["assert 4 == 5"],
        "suspectedLocation": "tests/test_demo.py:7",
        "repairSuggestion": "fix calculation",
        "needRetrieval": False,
        "retrievalQuery": "",
        "confidence": 0.9,
    }
    result = SrpToolProvider(
        FakeClient(repository_response("TEST_FAILED", analysis))
    ).execute_repository(context(tmp_path), {})
    body = json.loads(result.content)
    assert body["diagnosis"]["errorSubtype"] == "ALGORITHM_ERROR"
    assert body["failingTests"] == ["tests/test_demo.py::test_value"]
    assert len(body["failures"][0]["excerpt"]) < 600
    assert "RAW STDOUT" not in result.content
    assert "RAW STDERR" not in result.content
    assert result.metadata["diagnosis_available"] is True


def test_repository_timeout_is_normal_execution_with_diagnosis(tmp_path):
    analysis = {
        "errorType": "TIME_LIMIT_EXCEEDED",
        "errorSubtype": "INFINITE_LOOP",
        "needRetrieval": False,
    }
    result = SrpToolProvider(
        FakeClient(repository_response("TIME_LIMIT_EXCEEDED", analysis))
    ).execute_repository(context(tmp_path), {})
    body = json.loads(result.content)
    assert body["timeout"] is True
    assert body["diagnosis"]["errorSubtype"] == "INFINITE_LOOP"
    assert result.metadata.get("tool_status") is None


def test_repository_retrieval_signal_is_preserved_in_observation_and_metadata(tmp_path):
    analysis = {
        "errorType": "API_MISUSE",
        "errorSubtype": "DEPENDENCY_MISSING",
        "needRetrieval": True,
        "retrievalQuery": "install missing package",
    }
    result = SrpToolProvider(
        FakeClient(repository_response("TEST_FAILED", analysis))
    ).execute_repository(context(tmp_path), {})
    body = json.loads(result.content)
    assert body["diagnosis"]["needRetrieval"] is True
    assert body["diagnosis"]["retrievalQuery"] == "install missing package"
    assert result.metadata["need_retrieval"] is True


@pytest.mark.parametrize("status", ["ENVIRONMENT_ERROR", "SANDBOX_ERROR"])
def test_repository_infrastructure_status_is_not_a_diagnosis(tmp_path, status):
    result = SrpToolProvider(FakeClient(repository_response(status))).execute_repository(
        context(tmp_path), {}
    )
    body = json.loads(result.content)
    assert body["infrastructureFailure"] is True
    assert "diagnosis" not in body
    assert result.metadata["repository_infrastructure_failure"] is True
    assert result.metadata["diagnosis_available"] is False


def test_repository_transport_failure_uses_existing_service_error_shape(tmp_path):
    result = SrpToolProvider(
        FakeClient(error=SrpConnectionError("offline"))
    ).execute_repository(context(tmp_path), {})
    assert result.metadata["tool_status"] == "error"
    assert result.metadata["tool_error_code"] == "srp_unavailable"
    assert json.loads(result.content)["srp_available"] is False


def test_repository_http_failure_uses_existing_service_error_shape(tmp_path):
    result = SrpToolProvider(
        FakeClient(error=SrpHttpError(503, "unavailable"))
    ).execute_repository(context(tmp_path), {})
    assert result.metadata["tool_status"] == "error"
    assert result.metadata["tool_error_code"] == "srp_http_error"
    assert result.metadata["http_status"] == 503
