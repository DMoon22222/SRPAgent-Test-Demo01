from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from starlette.routing import Route

from app.adapters.a2a.server import ContextBuilder, DiagnosisHandler, agent_card
from app.adapters.mcp.server import McpEndpoint, ToolAdapter, create_http_app, create_server
from app.api.security import InteropBoundary
from app.api.v1 import error_response, router as v1_router
from app.services.diagnosis_service import DiagnosisService
from app.tasks.store import TaskStore

from app.analyzer.error_analyzer import ErrorAnalyzer
from app.config import settings
from app.repository.base import RepositoryRunSpec
from app.repository.diagnosis import diagnose_repository_execution
from app.repository.docker_runner import (
    DockerPytestRepositoryRunner,
    _execution_error,
)
from app.repository.workspace import (
    RepositoryWorkspaceError,
    RepositoryWorkspaceManager,
)
from app.sandbox.docker_sandbox import DockerSandbox
from app.sandbox.local_sandbox import LocalSandbox
from app.schemas import (
    AnalyzeRequest,
    BatchCaseResult,
    BatchExecuteAndAnalyzeRequest,
    BatchExecuteAndAnalyzeResult,
    BatchSummary,
    ErrorAnalysisResult,
    ExecuteAndAnalyzeRequest,
    ExecuteAndAnalyzeResult,
    Execution,
    RepositoryExecuteAndAnalyzeResult,
    RepositoryExecutionRequest,
)

@asynccontextmanager
async def lifespan(application):
    store = TaskStore(settings.a2a_store_path)
    service = DiagnosisService(registry=store)
    handler = DiagnosisHandler(service=service, store=store)
    await handler.start()
    application.state.a2a_handler = handler
    application.state.diagnosis_service = service
    application.state.a2a_dispatcher = JsonRpcDispatcher(handler, ContextBuilder())
    adapter = ToolAdapter(service.process, workers=settings.mcp_workers)
    server = create_server(adapter)
    application.state.mcp_http_app = create_http_app(server)
    try:
        async with server.session_manager.run():
            yield
    finally:
        adapter.close()
        await handler.close()


app = FastAPI(title="SRP B Group Python Service", lifespan=lifespan)
app.add_middleware(InteropBoundary)
app.include_router(v1_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith("/api/v1/"):
        return await request_validation_exception_handler(request, exc)
    body = exc.body if isinstance(exc.body, dict) else {}
    workflow = body.get("workflow", {})
    request_id = workflow.get("requestId") if isinstance(workflow, dict) else None
    if not isinstance(request_id, str):
        request_id = None
    details = [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()][:32]
    return error_response(request_id, "INVALID_REQUEST", "Request does not match the v1 contract", 422, details=details)


@app.get("/.well-known/agent-card.json", tags=["A2A"])
def get_agent_card():
    return agent_card_to_dict(agent_card())


# The SDK dispatcher resolves the lifespan-created handler for each request.
async def a2a_endpoint(request):
    return await request.app.state.a2a_dispatcher.handle_requests(request)


app.router.routes.append(Route("/a2a", a2a_endpoint, methods=["POST"]))
app.router.routes.append(Route("/mcp", McpEndpoint()))


@app.get("/api/ping")
def ping() -> str:
    return "srp-b-group-python-demo is running"


@app.post("/api/analyze-error", response_model=ErrorAnalysisResult)
def analyze_error(request: AnalyzeRequest) -> ErrorAnalysisResult:
    return ErrorAnalyzer().analyze(request)


@app.post("/api/execute-and-analyze", response_model=ExecuteAndAnalyzeResult)
def execute_and_analyze(request: ExecuteAndAnalyzeRequest) -> ExecuteAndAnalyzeResult:
    sandbox = _select_sandbox()
    execution = sandbox.run(request)
    analysis = None
    if not execution.success:
        analysis = ErrorAnalyzer().analyze(
            AnalyzeRequest(
                problem=request.problem,
                language=request.language,
                code=request.code,
                errorLog=execution.errorLog,
            )
        )
    return ExecuteAndAnalyzeResult(execution=execution, analysis=analysis)


@app.post(
    "/api/execute-repository",
    response_model=RepositoryExecuteAndAnalyzeResult,
)
def execute_repository(
    request: RepositoryExecutionRequest,
) -> RepositoryExecuteAndAnalyzeResult:
    manager = RepositoryWorkspaceManager()
    runner = DockerPytestRepositoryRunner()
    return _execute_repository_request(request, manager, runner)


def _execute_repository_request(request, manager, runner):
    spec = RepositoryRunSpec(
        runner=request.runner,
        test_targets=tuple(request.testTargets),
        timeout_seconds=request.timeoutSeconds,
        benchmark=request.benchmark,
    )
    try:
        with manager.snapshot_workspace(request.workspacePath) as snapshot:
            execution = runner.run(snapshot.snapshot_path, spec)
    except RepositoryWorkspaceError as exc:
        execution = _execution_error(
            status="ENVIRONMENT_ERROR",
            failed_stage="PRE_CHECK",
            message=str(exc),
            execution_time_ms=0,
        )
    analysis = diagnose_repository_execution(execution)
    return RepositoryExecuteAndAnalyzeResult(execution=execution, analysis=analysis)


@app.post("/api/check-syntax", response_model=Execution)
def check_syntax(request: ExecuteAndAnalyzeRequest) -> Execution:
    return _select_sandbox().check_syntax(request)


@app.post("/api/execute-batch", response_model=BatchExecuteAndAnalyzeResult)
def execute_batch(request: BatchExecuteAndAnalyzeRequest) -> BatchExecuteAndAnalyzeResult:
    sandbox = _select_sandbox()
    case_results: list[BatchCaseResult] = []

    for index, test_case in enumerate(request.testCases, start=1):
        case_id = test_case.caseId or f"case-{index}"
        single_request = ExecuteAndAnalyzeRequest(
            problem=request.problem,
            language=request.language,
            code=request.code,
            stdin=test_case.stdin,
            expectedOutput=test_case.expectedOutput,
        )
        case_results.append(BatchCaseResult(caseId=case_id, execution=sandbox.run(single_request)))

    total = len(case_results)
    passed = sum(1 for item in case_results if item.execution.success)
    timed_out = sum(1 for item in case_results if item.execution.timeout)
    failed = total - passed
    summary = BatchSummary(
        total=total,
        passed=passed,
        failed=failed,
        timedOut=timed_out,
        passRate=passed / total if total else 0.0,
    )

    analysis = None
    first_failure = next((item for item in case_results if not item.execution.success), None)
    if first_failure:
        analysis = ErrorAnalyzer().analyze(
            AnalyzeRequest(
                problem=request.problem,
                language=request.language,
                code=request.code,
                errorLog=first_failure.execution.errorLog,
            )
        )

    return BatchExecuteAndAnalyzeResult(summary=summary, caseResults=case_results, analysis=analysis)


def _select_sandbox():
    if settings.sandbox_mode.strip().lower() == "local":
        return LocalSandbox()
    return DockerSandbox()
