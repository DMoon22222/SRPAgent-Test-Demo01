from fastapi import FastAPI

from app.analyzer.error_analyzer import ErrorAnalyzer
from app.config import settings
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
)

app = FastAPI(title="SRP B Group Python Service")


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
