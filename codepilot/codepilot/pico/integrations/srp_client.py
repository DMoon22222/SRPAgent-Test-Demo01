"""HTTP client for the SRP Execution & Diagnosis service."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from typing import Any

from pico.config import provider_env

DEFAULT_SRP_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_SRP_TIMEOUT_SECONDS = 60.0
SRP_USER_AGENT = "pico-srp/0.1"


class SrpClientError(RuntimeError):
    """Base error for failures in the SRP communication boundary."""


class SrpConnectionError(SrpClientError):
    """Raised when the SRP service cannot be reached."""


class SrpTimeoutError(SrpClientError):
    """Raised when an SRP request exceeds its configured timeout."""


class SrpHttpError(SrpClientError):
    """Raised when SRP returns a non-successful HTTP status."""

    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body
        detail = f": {body}" if body else ""
        super().__init__(f"SRP request failed with HTTP {status_code}{detail}")


class SrpResponseError(SrpClientError):
    """Raised when an SRP response violates the communication contract."""


class SrpClient:
    """Small, runtime-independent client for the SRP FastAPI service."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
    ):
        configured_url = base_url or provider_env(
            "PICO_SRP_BASE_URL", default=DEFAULT_SRP_BASE_URL
        )
        self.base_url = configured_url.rstrip("/")
        if not self.base_url:
            raise ValueError("SRP base URL must not be empty")

        configured_timeout = timeout_seconds
        if configured_timeout is None:
            raw_timeout = provider_env(
                "PICO_SRP_TIMEOUT_SECONDS",
                default=str(DEFAULT_SRP_TIMEOUT_SECONDS),
            )
            try:
                configured_timeout = float(raw_timeout)
            except ValueError as exc:
                raise ValueError("PICO_SRP_TIMEOUT_SECONDS must be a number") from exc
        if configured_timeout <= 0:
            raise ValueError("SRP timeout must be greater than zero")
        self.timeout_seconds = configured_timeout

        if enabled is None:
            raw_enabled = provider_env("PICO_SRP_ENABLED", default="false")
            enabled = raw_enabled.strip().lower() in {"1", "true", "yes", "on"}
        self.enabled = enabled

    def ping(self) -> bool:
        """Return True for a reachable SRP ping endpoint; failures are explicit."""
        self._request("GET", "/api/ping")
        return True

    def execute_and_analyze(
        self,
        *,
        problem: str,
        language: str,
        code: str,
        stdin: str = "",
        expected_output: str = "",
        benchmark: str = "",
    ) -> dict[str, Any]:
        """Execute code through SRP and return its unmodified JSON object."""
        payload = {
            "problem": problem,
            "language": language,
            "code": code,
            "stdin": stdin,
            "expectedOutput": expected_output,
            "benchmark": benchmark,
        }
        body = self._request("POST", "/api/execute-and-analyze", payload)
        return _decode_execution_result(body)

    def execute_repository(
        self,
        *,
        workspace_path: str,
        test_targets: list[str] | None = None,
        timeout_seconds: int = 60,
        benchmark: str = "",
    ) -> dict[str, Any]:
        """Execute repository tests through SRP and return its JSON object."""
        payload = {
            "workspacePath": workspace_path,
            "runner": "pytest",
            "testTargets": list(test_targets or []),
            "timeoutSeconds": timeout_seconds,
            "benchmark": benchmark,
        }
        body = self._request("POST", "/api/execute-repository", payload)
        return _decode_execution_result(body)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> bytes:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": SRP_USER_AGENT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read()
                status = getattr(response, "status", None)
                if status is not None and not 200 <= status < 300:
                    raise SrpHttpError(status, _decode_error_body(body))
                return body
        except urllib.error.HTTPError as exc:
            body = _decode_error_body(exc.read())
            raise SrpHttpError(exc.code, body) from exc
        except TimeoutError as exc:
            raise SrpTimeoutError(
                f"SRP request timed out after {self.timeout_seconds:g}s"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise SrpTimeoutError(
                    f"SRP request timed out after {self.timeout_seconds:g}s"
                ) from exc
            raise SrpConnectionError(
                f"Could not reach SRP service at {self.base_url}: {exc.reason}"
            ) from exc
        except (ConnectionError, RemoteDisconnected, OSError) as exc:
            raise SrpConnectionError(
                f"Could not reach SRP service at {self.base_url}: {exc}"
            ) from exc


def _decode_execution_result(body: bytes) -> dict[str, Any]:
    """Validate the response envelope shared by both execution endpoints."""
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SrpResponseError("SRP returned invalid JSON") from exc

    if not isinstance(result, dict):
        raise SrpResponseError("SRP response must be a JSON object")
    execution = result.get("execution")
    if execution is None:
        raise SrpResponseError("SRP response is missing execution")
    if not isinstance(execution, dict):
        raise SrpResponseError("SRP response execution must be an object")
    analysis = result.get("analysis")
    if analysis is not None and not isinstance(analysis, dict):
        raise SrpResponseError("SRP response analysis must be an object or null")
    return result


def _decode_error_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")[:2000]
