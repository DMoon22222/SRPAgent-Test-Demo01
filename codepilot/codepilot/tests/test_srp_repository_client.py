import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from pico.integrations import (
    SrpClient,
    SrpConnectionError,
    SrpHttpError,
    SrpResponseError,
    SrpTimeoutError,
)


class FakeResponse:
    def __init__(self, payload):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = 200

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def client():
    return SrpClient(base_url="http://srp.test", timeout_seconds=7, enabled=True)


def response(status="SUCCESS", analysis=None):
    return {
        "execution": {
            "success": status == "SUCCESS",
            "status": status,
            "failedStage": "NONE" if status == "SUCCESS" else "TEST",
        },
        "analysis": analysis,
    }


def test_execute_repository_uses_contract_and_returns_unmodified_response():
    payload = response()
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(payload),
    ) as urlopen:
        result = client().execute_repository(
            workspace_path=r"F:\repo",
            test_targets=["tests/test_demo.py::test_ok"],
            timeout_seconds=45,
            benchmark="phase44",
        )

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://srp.test/api/execute-repository"
    assert json.loads(request.data) == {
        "workspacePath": r"F:\repo",
        "runner": "pytest",
        "testTargets": ["tests/test_demo.py::test_ok"],
        "timeoutSeconds": 45,
        "benchmark": "phase44",
    }
    assert result == payload


@pytest.mark.parametrize(
    "status,analysis",
    [
        ("TEST_FAILED", {"errorType": "WRONG_ANSWER"}),
        ("TIME_LIMIT_EXCEEDED", {"errorType": "TIME_LIMIT_EXCEEDED"}),
        ("ENVIRONMENT_ERROR", None),
        ("SANDBOX_ERROR", None),
    ],
)
def test_execute_repository_accepts_all_structured_outcomes(status, analysis):
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(response(status, analysis)),
    ):
        assert client().execute_repository(workspace_path=r"F:\repo")["execution"][
            "status"
        ] == status


@pytest.mark.parametrize(
    "payload,message",
    [
        (b"not-json", "invalid JSON"),
        ([], "JSON object"),
        ({"analysis": None}, "missing execution"),
        ({"execution": []}, "execution must be an object"),
        ({"execution": {}, "analysis": []}, "analysis must be an object or null"),
    ],
)
def test_execute_repository_rejects_invalid_response(payload, message):
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(payload),
    ), pytest.raises(SrpResponseError, match=message):
        client().execute_repository(workspace_path=r"F:\repo")


def test_execute_repository_preserves_http_error_mapping():
    error = urllib.error.HTTPError(
        "http://srp.test", 422, "bad", {}, io.BytesIO(b'{"detail":"bad"}')
    )
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen", side_effect=error
    ), pytest.raises(SrpHttpError) as caught:
        client().execute_repository(workspace_path=r"F:\repo")
    assert caught.value.status_code == 422


@pytest.mark.parametrize(
    "error,expected",
    [
        (urllib.error.URLError(ConnectionRefusedError("refused")), SrpConnectionError),
        (TimeoutError("slow"), SrpTimeoutError),
    ],
)
def test_execute_repository_preserves_transport_error_mapping(error, expected):
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen", side_effect=error
    ), pytest.raises(expected):
        client().execute_repository(workspace_path=r"F:\repo")
