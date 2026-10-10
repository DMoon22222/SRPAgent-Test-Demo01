import logging
import shutil
import subprocess
from threading import BoundedSemaphore

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.adapters.mcp.server import HTTP_PROTOCOL_VERSIONS, STDIO_PROTOCOL_VERSIONS
from app.contracts.v1 import ApiError, DiagnosticRequest, DiagnosticResult
from app.services.diagnosis_service import ServiceError

router = APIRouter(tags=["Agent Interoperability v1"])
slots = BoundedSemaphore(settings.a2a_workers)
logger = logging.getLogger(__name__)


def error_response(request_id, code, message, status=409, retryable=False, details=None):
    return JSONResponse(status_code=status, content=ApiError(
        requestId=request_id, code=code, message=message, retryable=retryable,
        details=details or [],
    ).model_dump())


def invoke(body, expected_operation, request):
    if body.operation != expected_operation:
        return error_response(body.workflow.requestId, "OPERATION_MISMATCH", "Operation does not match endpoint", 422)
    if not slots.acquire(blocking=False):
        return error_response(body.workflow.requestId, "SERVICE_BUSY", "All REST execution slots are busy", 503, True)
    try:
        handler = getattr(request.app.state, "a2a_handler", None)
        if not handler or not handler.started:
            return error_response(body.workflow.requestId, "SERVICE_NOT_READY", "Service is not ready", 503, True)
        return request.app.state.diagnosis_service.process(body, request.state.principal)
    except ServiceError as exc:
        return error_response(body.workflow.requestId, exc.code, str(exc), exc.status, exc.retryable)
    except Exception:
        logger.exception("Diagnosis failed for request %s", body.workflow.requestId)
        return error_response(body.workflow.requestId, "INTERNAL_ERROR", "Diagnosis service failed", 500, True)
    finally:
        slots.release()


error_models = {status: {"model": ApiError} for status in (401, 403, 409, 413, 422, 500, 503)}


@router.post("/api/v1/diagnose", response_model=DiagnosticResult, responses=error_models)
def diagnose(body: DiagnosticRequest, request: Request):
    return invoke(body, "diagnose_error", request)


@router.post("/api/v1/execute-and-diagnose", response_model=DiagnosticResult, responses=error_models)
def execute_and_diagnose(body: DiagnosticRequest, request: Request):
    return invoke(body, "execute_and_diagnose", request)


@router.post("/api/v1/check-syntax", response_model=DiagnosticResult, responses=error_models)
def check_syntax(body: DiagnosticRequest, request: Request):
    return invoke(body, "check_syntax", request)


@router.get("/api/v1/capabilities")
def capabilities():
    return {
        "schemaVersions": ["1.0"], "operations": ["diagnose_error", "execute_and_diagnose", "check_syntax"],
        "languages": ["python", "java"], "artifactKinds": ["snippet"], "testKinds": ["STDIO"],
        "limits": {"sourceFiles": 1, "sourceChars": 200000, "testCases": 20, "logChars": 12000, "requestBytes": 1048576},
        "outputComparison": "Normalize CRLF/CR to LF and trim outer whitespace; empty expected output is compared.",
        "protocols": {"rest": "1.0", "a2a": "1.0", "mcp": "2026-07-28"},
        "mcp": {"httpPath": "/mcp", "httpTransport": "streamable-http", "httpProtocolVersions": list(HTTP_PROTOCOL_VERSIONS),
                "stdioProtocolVersions": list(STDIO_PROTOCOL_VERSIONS), "tasks": False, "workers": settings.mcp_workers},
        "a2a": {"streaming": False, "pushNotifications": False, "cancel": "queued-only", "persistence": "sqlite", "singleProcess": True},
        "externalFeedbackReproduced": False, "requestIdIdempotent": False,
        "workflowTestSuiteFrozen": True, "codeRevisionImmutable": True,
        "authentication": "Shared bearer-token principal, or loopback-only trusted development",
        "repositoryArtifacts": False, "localExecutionOptIn": settings.interop_allow_local_execution,
    }


def sandbox_readiness():
    mode = settings.sandbox_mode.strip().lower()
    if mode == "local":
        return {"mode": mode, "enabled": settings.interop_allow_local_execution,
                "pythonAvailable": bool(shutil.which("python3") or shutil.which("python") or shutil.which("py")),
                "javaAvailable": bool(shutil.which("java") and shutil.which("javac"))}
    try:
        probe = subprocess.run(["docker", "image", "inspect", settings.sandbox_docker_image],
                               capture_output=True, timeout=3, check=False)
        return {"mode": "docker", "available": probe.returncode == 0}
    except (OSError, subprocess.SubprocessError):
        return {"mode": "docker", "available": False}


@router.get("/health/ready")
def ready(request: Request):
    manager = getattr(request.app.state, "a2a_handler", None)
    task_store_ready = bool(manager and manager.started)
    return JSONResponse(status_code=200 if task_store_ready else 503, content={
        "ready": task_store_ready, "diagnosisAvailable": True,
        "analysisMode": "LLM_CONFIGURED_WITH_RULE_FALLBACK" if settings.dashscope_api_key else "RULE_ONLY",
        "modelConnectivityProbed": False, "a2aTaskStoreReady": task_store_ready,
        "sandbox": sandbox_readiness(),
    })
