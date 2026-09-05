"""Tool Provider that exposes SRP diagnostics to the Pico agent."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from pico.integrations.srp_client import (
    SrpClient,
    SrpConnectionError,
    SrpHttpError,
    SrpResponseError,
    SrpTimeoutError,
)
from pico.tool_executor import ToolExecutionResult
from pico.tool_provider import ToolProvider
from pico.workspace import clip

EXECUTE_AND_DIAGNOSE = "execute_and_diagnose"
EXECUTE_REPOSITORY_AND_DIAGNOSE = "execute_repository_and_diagnose"
SUPPORTED_LANGUAGES = {"java", "py", "python", "python3"}

TOOL_SPEC = {
    "schema": {
        "path": "str",
        "problem": "str=''",
        "language": "str='python'",
        "stdin": "str=''",
        "expected_output": "str=''",
        "benchmark": "str=''",
    },
    "risky": False,
    "description": (
        "Execute a workspace code file inside the isolated SRP sandbox and "
        "return structured execution diagnostics. Use this for generated or "
        "modified code that needs safe compile, run, or test feedback."
    ),
    "execution_isolated": True,
}

REPOSITORY_TOOL_SPEC = {
    "schema": {
        "test_targets": "list[str]=[]",
        "timeout_seconds": "int=60",
        "benchmark": "str=''",
    },
    "risky": False,
    "description": (
        "Execute pytest for the current repository in an isolated SRP snapshot "
        "and return compact structured execution and diagnosis evidence."
    ),
    "execution_isolated": True,
}


class SrpToolProvider(ToolProvider):
    """Expose SRP as an optional, injectable Tool Provider."""

    name = "srp"

    def __init__(self, client: SrpClient):
        self.client = client

    def discover(self, context) -> dict[str, dict[str, Any]]:
        if not self.client.enabled:
            return {}
        return {
            EXECUTE_AND_DIAGNOSE: {
                **TOOL_SPEC,
                "provider": self.name,
                "validate": partial(self.validate, context),
                "run": partial(self.execute, context),
                "example": (
                    '<tool>{"name":"execute_and_diagnose","args":'
                    '{"path":"solution.py","language":"python"}}</tool>'
                ),
            },
            EXECUTE_REPOSITORY_AND_DIAGNOSE: {
                **REPOSITORY_TOOL_SPEC,
                "provider": self.name,
                "validate": self.validate_repository,
                "run": partial(self.execute_repository, context),
                "example": (
                    '<tool>{"name":"execute_repository_and_diagnose","args":'
                    '{"test_targets":[],"timeout_seconds":60}}</tool>'
                ),
            },
        }

    @staticmethod
    def validate(context, args: dict[str, Any]) -> None:
        path_value = str((args or {}).get("path", "")).strip()
        if not path_value:
            raise ValueError("path must not be empty")
        path = context.path(path_value)
        if not path.exists():
            raise ValueError("path does not exist")
        if not path.is_file():
            raise ValueError("path is not a file")

        language = _normalize_language((args or {}).get("language", "python"))
        suffix = path.suffix.lower()
        if suffix == ".py" and language != "python":
            raise ValueError("Python file requires language=python")
        if suffix == ".java" and language != "java":
            raise ValueError("Java file requires language=java")

    def execute(self, context, args: dict[str, Any]) -> ToolExecutionResult:
        path = context.path(str(args["path"]).strip())
        language = _normalize_language(args.get("language", "python"))
        code = path.read_text(encoding="utf-8", errors="replace")

        try:
            result = self.client.execute_and_analyze(
                problem=str(args.get("problem", "") or ""),
                language=language,
                code=code,
                stdin=str(args.get("stdin", "") or ""),
                expected_output=str(args.get("expected_output", "") or ""),
                benchmark=str(args.get("benchmark", "") or ""),
            )
        except SrpConnectionError as exc:
            return _service_failure("srp_unavailable", exc, available=False)
        except SrpTimeoutError as exc:
            return _service_failure("srp_timeout", exc, available=False)
        except SrpHttpError as exc:
            return _service_failure(
                "srp_http_error",
                exc,
                available=True,
                http_status=exc.status_code,
            )
        except SrpResponseError as exc:
            return _service_failure("srp_response_error", exc, available=True)

        observation = to_agent_observation(result)
        execution = result["execution"]
        analysis = result.get("analysis") or {}
        metadata = {
            "srp_enabled": True,
            "srp_available": True,
            "execution_isolated": True,
            "execution_status": execution.get("status", ""),
            "failed_stage": observation.get("failedStage", ""),
            "error_type": analysis.get("errorType", ""),
            "error_subtype": analysis.get("errorSubtype", ""),
            "need_retrieval": bool(analysis.get("needRetrieval", False)),
            "execution_time_ms": execution.get("executionTimeMs", 0),
        }
        return ToolExecutionResult(
            content=json.dumps(observation, ensure_ascii=False, indent=2),
            metadata=metadata,
        )

    @staticmethod
    def validate_repository(args: dict[str, Any]) -> None:
        args = args or {}
        unexpected = set(args) - {"test_targets", "timeout_seconds", "benchmark"}
        if unexpected:
            raise ValueError(f"unsupported arguments: {', '.join(sorted(unexpected))}")
        targets = args.get("test_targets", [])
        if not isinstance(targets, list) or any(
            not isinstance(item, str) or not item.strip() for item in targets
        ):
            raise ValueError("test_targets must be a list of non-empty strings")
        timeout = args.get("timeout_seconds", 60)
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise TypeError("timeout_seconds must be an integer")
        if not 1 <= timeout <= 600:
            raise ValueError("timeout_seconds must be between 1 and 600")
        if not isinstance(args.get("benchmark", ""), str):
            raise TypeError("benchmark must be a string")

    def execute_repository(
        self,
        context,
        args: dict[str, Any],
    ) -> ToolExecutionResult:
        workspace_path = str(Path(context.root).resolve())
        try:
            result = self.client.execute_repository(
                workspace_path=workspace_path,
                test_targets=list(args.get("test_targets", [])),
                timeout_seconds=args.get("timeout_seconds", 60),
                benchmark=str(args.get("benchmark", "") or ""),
            )
        except SrpConnectionError as exc:
            return _service_failure("srp_unavailable", exc, available=False)
        except SrpTimeoutError as exc:
            return _service_failure("srp_timeout", exc, available=False)
        except SrpHttpError as exc:
            return _service_failure(
                "srp_http_error",
                exc,
                available=True,
                http_status=exc.status_code,
            )
        except SrpResponseError as exc:
            return _service_failure("srp_response_error", exc, available=True)

        observation = to_repository_agent_observation(result)
        execution = result["execution"]
        analysis = result.get("analysis") or {}
        status = str(execution.get("status", ""))
        infrastructure_failure = status in {"ENVIRONMENT_ERROR", "SANDBOX_ERROR"}
        metadata = {
            "srp_enabled": True,
            "srp_available": True,
            "execution_isolated": True,
            "execution_status": status,
            "failed_stage": observation.get("failedStage", ""),
            "error_type": analysis.get("errorType", ""),
            "error_subtype": analysis.get("errorSubtype", ""),
            "need_retrieval": bool(analysis.get("needRetrieval", False)),
            "diagnosis_available": bool(analysis),
            "execution_time_ms": execution.get("executionTimeMs", 0),
            "repository_infrastructure_failure": infrastructure_failure,
        }
        if infrastructure_failure:
            metadata["tool_error_code"] = f"repository_{status.lower()}"
        return ToolExecutionResult(
            content=json.dumps(observation, ensure_ascii=False, indent=2),
            metadata=metadata,
        )


def to_agent_observation(result: dict[str, Any]) -> dict[str, Any]:
    """Compress an SRP response without reclassifying its diagnosis."""
    execution = result["execution"]
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    native_observation = execution.get("observation")
    if not isinstance(native_observation, dict):
        native_observation = {}

    status = str(execution.get("status", "") or "UNKNOWN")
    success = bool(execution.get("success", False))
    failed_stage = str(
        execution.get("failedStage")
        or analysis.get("failedStage")
        or native_observation.get("stage")
        or "NONE"
    )
    short_summary = _short_text(native_observation.get("shortSummary"), 240)
    if not short_summary:
        short_summary = "程序执行成功。" if success else f"程序执行结果：{status}。"

    observation: dict[str, Any] = {
        "executionStatus": status,
        "failedStage": failed_stage,
        "success": success,
        "timeout": bool(execution.get("timeout", False)),
        "exitCode": execution.get("exitCode"),
        "executionTimeMs": execution.get("executionTimeMs", 0),
        "summary": short_summary,
        "shortSummary": short_summary,
        "importantSignals": _short_list(
            native_observation.get("importantSignals"), limit=3, item_limit=160
        ),
        "nextActionHint": _short_text(
            native_observation.get("nextActionHint"), 240
        ),
    }

    if analysis:
        diagnosis_limits = {
            "errorType": None,
            "errorSubtype": None,
            "rootCause": 500,
            "suspectedLocation": 240,
            "repairSuggestion": 500,
            "retrievalQuery": 240,
            "confidence": None,
            "needRetrieval": None,
        }
        diagnosis = {}
        for key, limit in diagnosis_limits.items():
            if key not in analysis:
                continue
            value = analysis[key]
            diagnosis[key] = _short_text(value, limit) if limit else value
        diagnosis["evidence"] = _short_list(
            analysis.get("evidence"), limit=3, item_limit=240
        )
        observation["diagnosis"] = diagnosis

    return observation


def to_repository_agent_observation(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Compress repository results and deliberately omit raw stdout/stderr."""
    execution = result["execution"]
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    native = execution.get("observation")
    if not isinstance(native, dict):
        native = {}
    summary = execution.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    failures = execution.get("failures")
    if not isinstance(failures, list):
        failures = []

    status = str(execution.get("status") or "UNKNOWN")
    compact_failures = []
    for failure in failures[:5]:
        if not isinstance(failure, dict):
            continue
        compact_failures.append(
            {
                "testId": _short_text(failure.get("testId"), 240),
                "location": _short_text(failure.get("location"), 240),
                "message": _short_text(failure.get("message"), 500),
                "excerpt": _short_text(failure.get("excerpt"), 500),
            }
        )
    failing_tests = _short_list(
        native.get("failingTests"), limit=5, item_limit=240
    )
    if not failing_tests:
        failing_tests = [
            item["testId"] for item in compact_failures if item["testId"]
        ]

    observation: dict[str, Any] = {
        "executionStatus": status,
        "failedStage": str(execution.get("failedStage") or "NONE"),
        "success": bool(execution.get("success", False)),
        "timeout": bool(execution.get("timeout", False)),
        "exitCode": execution.get("exitCode"),
        "executionTimeMs": execution.get("executionTimeMs", 0),
        "summary": {
            key: int(summary.get(key, 0) or 0)
            for key in ("total", "passed", "failed", "skipped")
        },
        "shortSummary": _short_text(
            native.get("shortSummary") or f"Repository execution result: {status}.",
            240,
        ),
        "importantSignals": _short_list(
            native.get("importantSignals"), limit=5, item_limit=160
        ),
        "failingTests": failing_tests,
        "failures": compact_failures,
        "nextActionHint": _short_text(native.get("nextActionHint"), 240),
    }
    if status in {"ENVIRONMENT_ERROR", "SANDBOX_ERROR"}:
        observation["infrastructureFailure"] = True
    if analysis:
        diagnosis = {
            "errorType": analysis.get("errorType", ""),
            "errorSubtype": analysis.get("errorSubtype", ""),
            "rootCause": _short_text(analysis.get("rootCause"), 500),
            "evidence": _short_list(
                analysis.get("evidence"), limit=5, item_limit=240
            ),
            "suspectedLocation": _short_text(
                analysis.get("suspectedLocation"), 240
            ),
            "repairSuggestion": _short_text(
                analysis.get("repairSuggestion"), 500
            ),
            "needRetrieval": bool(analysis.get("needRetrieval", False)),
            "retrievalQuery": _short_text(
                analysis.get("retrievalQuery"), 240
            ),
            "confidence": analysis.get("confidence", 0),
        }
        observation["diagnosis"] = diagnosis
    return observation


def _normalize_language(value: Any) -> str:
    language = str(value or "").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            "language must be one of: java, py, python, python3"
        )
    return "python" if language in {"py", "python3"} else language


def _short_text(value: Any, limit: int | None) -> Any:
    if value is None:
        return ""
    if limit is None:
        return value
    return clip(str(value), limit)


def _short_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clip(str(item), item_limit) for item in value[:limit]]


def _service_failure(
    error_code: str,
    error: Exception,
    *,
    available: bool,
    http_status: int | None = None,
) -> ToolExecutionResult:
    content = {
        "tool_status": "error",
        "tool_error_code": error_code,
        "srp_available": available,
        "message": clip(str(error), 500),
    }
    metadata = {
        "tool_status": "error",
        "tool_error_code": error_code,
        "srp_enabled": True,
        "srp_available": available,
        "execution_isolated": True,
    }
    if http_status is not None:
        content["http_status"] = http_status
        metadata["http_status"] = http_status
    return ToolExecutionResult(
        content=json.dumps(content, ensure_ascii=False, indent=2),
        metadata=metadata,
    )
