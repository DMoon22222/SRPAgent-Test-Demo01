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
    def __init__(self, payload, status=200):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def build_client():
    return SrpClient(base_url="http://srp.test", timeout_seconds=7)


def execution(status, *, success=False, failed_stage="RUNTIME"):
    return {
        "success": success,
        "status": status,
        "failedStage": failed_stage,
    }


def test_configuration_uses_srp_environment_variables():
    env = {
        "PICO_SRP_ENABLED": "true",
        "PICO_SRP_BASE_URL": "http://localhost:9000/",
        "PICO_SRP_TIMEOUT_SECONDS": "12.5",
    }
    with patch.dict("os.environ", env, clear=False):
        client = SrpClient()

    assert client.enabled is True
    assert client.base_url == "http://localhost:9000"
    assert client.timeout_seconds == 12.5


def test_ping_success():
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse("srp is running"),
    ) as urlopen:
        assert build_client().ping() is True

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://srp.test/api/ping"
    assert request.get_method() == "GET"


def test_ping_connection_refused_is_explicit():
    error = urllib.error.URLError(ConnectionRefusedError("refused"))
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen", side_effect=error
    ), pytest.raises(SrpConnectionError, match="Could not reach SRP"):
        build_client().ping()


def test_execute_success_uses_real_srp_request_contract():
    response = {"execution": execution("SUCCESS", success=True), "analysis": None}
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(response),
    ) as urlopen:
        result = build_client().execute_and_analyze(
            problem="add two numbers",
            language="python",
            code="print(2 + 3)",
            stdin="",
            expected_output="5",
            benchmark="smoke",
        )

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://srp.test/api/execute-and-analyze"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {
        "problem": "add two numbers",
        "language": "python",
        "code": "print(2 + 3)",
        "stdin": "",
        "expectedOutput": "5",
        "benchmark": "smoke",
    }
    assert result == response


def test_compile_error_is_returned_without_reclassification():
    response = {
        "execution": execution("COMPILE_ERROR", failed_stage="COMPILE"),
        "analysis": {"errorType": "COMPILE_ERROR"},
    }
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(response),
    ):
        assert build_client().execute_and_analyze(
            problem="", language="python", code="bad code"
        ) == response


def test_runtime_error_details_are_returned_unchanged():
    response = {
        "execution": execution("RUNTIME_ERROR"),
        "analysis": {
            "errorType": "RUNTIME_ERROR",
            "errorSubtype": "DIVIDE_BY_ZERO",
            "rootCause": "ZeroDivisionError",
        },
    }
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(response),
    ):
        assert build_client().execute_and_analyze(
            problem="", language="python", code="1 / 0"
        ) == response


def test_wrong_answer_stage_is_returned_unchanged():
    response = {
        "execution": execution("WRONG_ANSWER", failed_stage="TEST"),
        "analysis": {"errorType": "WRONG_ANSWER", "failedStage": "TEST"},
    }
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(response),
    ):
        result = build_client().execute_and_analyze(
            problem="", language="python", code="print(4)"
        )

    assert result == response


def test_need_retrieval_is_not_modified():
    analysis = {
        "errorSubtype": "DEPENDENCY_MISSING",
        "needRetrieval": True,
        "retrievalQuery": "install missing package",
    }
    response = {"execution": execution("RUNTIME_ERROR"), "analysis": analysis}
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(response),
    ):
        result = build_client().execute_and_analyze(
            problem="", language="python", code="import missing"
        )

    assert result["analysis"] == analysis
    assert result["analysis"]["needRetrieval"] is True


def test_timeout_is_distinct_from_connection_and_execution_errors():
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        side_effect=TimeoutError("slow"),
    ), pytest.raises(SrpTimeoutError, match="timed out after 7s"):
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )


def test_http_500_exposes_status_and_body():
    error = urllib.error.HTTPError(
        "http://srp.test/api/execute-and-analyze",
        500,
        "Internal Server Error",
        {},
        io.BytesIO(b"sandbox unavailable"),
    )
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen", side_effect=error
    ), pytest.raises(SrpHttpError, match="HTTP 500") as caught:
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )

    assert caught.value.status_code == 500
    assert caught.value.body == "sandbox unavailable"


def test_http_400_is_distinct_from_server_errors():
    error = urllib.error.HTTPError(
        "http://srp.test/api/execute-and-analyze",
        400,
        "Bad Request",
        {},
        io.BytesIO(b"invalid request"),
    )
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen", side_effect=error
    ), pytest.raises(SrpHttpError, match="HTTP 400") as caught:
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )

    assert caught.value.status_code == 400


def test_invalid_json_is_rejected():
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse(b"not-json"),
    ), pytest.raises(SrpResponseError, match="invalid JSON"):
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )


def test_non_object_json_is_rejected():
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse([]),
    ), pytest.raises(SrpResponseError, match="must be a JSON object"):
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )


def test_missing_execution_is_rejected():
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse({"analysis": None}),
    ), pytest.raises(SrpResponseError, match="missing execution"):
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )


def test_invalid_execution_type_is_rejected():
    with patch(
        "pico.integrations.srp_client.urllib.request.urlopen",
        return_value=FakeResponse({"execution": "SUCCESS", "analysis": None}),
    ), pytest.raises(SrpResponseError, match="execution must be an object"):
        build_client().execute_and_analyze(
            problem="", language="python", code="pass"
        )
