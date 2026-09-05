"""Rule-first diagnosis adapter for structured repository executions."""

from __future__ import annotations

from app.analyzer.error_analyzer import ErrorAnalyzer
from app.analyzer.error_signal_extractor import make_rule_decision
from app.sandbox.support import truncate_output
from app.schemas import (
    AnalyzeRequest,
    ErrorAnalysisResult,
    RepositoryExecution,
    RepositoryTestFailure,
    RuleDecision,
)

DIAGNOSABLE_REPOSITORY_STATUSES = frozenset(
    {"TEST_FAILED", "TIME_LIMIT_EXCEEDED"}
)
MAX_REPOSITORY_DIAGNOSTIC_CONTEXT_CHARS = 8000
MAX_DIAGNOSTIC_STDERR_CHARS = 2000
MAX_DIAGNOSTIC_STDOUT_CHARS = 1000
MAX_EVIDENCE_VALUE_CHARS = 1000


def diagnose_repository_execution(
    execution: RepositoryExecution,
    *,
    analyzer: ErrorAnalyzer | None = None,
) -> ErrorAnalysisResult | None:
    """Diagnose code/test failures without reading repository source files."""
    if execution.status not in DIAGNOSABLE_REPOSITORY_STATUSES:
        return None

    context = build_repository_diagnostic_context(execution)
    rule = make_rule_decision(
        execution=execution.model_dump(),
        error_log=context,
    )
    rule = _normalize_repository_rule(execution, rule)
    request = AnalyzeRequest(
        problem="Repository pytest execution failed.",
        language="python",
        code="",
        errorLog=context,
    )
    analysis = (analyzer or ErrorAnalyzer()).analyze(request, rule_decision=rule)
    structured_location = _structured_location(execution.failures)
    if structured_location:
        analysis = analysis.model_copy(
            update={"suspectedLocation": structured_location}
        )
    return analysis


def build_repository_diagnostic_context(execution: RepositoryExecution) -> str:
    """Build bounded evidence from the existing compact execution result."""
    summary = execution.summary
    lines = [
        f"Repository status: {execution.status}",
        f"Failed stage: {execution.failedStage}",
        f"Runner: {execution.runner}",
        "Summary:",
        f"{summary.total} total",
        f"{summary.passed} passed",
        f"{summary.failed} failed",
        f"{summary.skipped} skipped",
    ]
    for index, failure in enumerate(execution.failures, start=1):
        lines.extend(
            [
                f"Failure {index}:",
                f"testId: {failure.testId}",
                f"location: {failure.location}",
                f"message: {failure.message}",
                f"excerpt: {failure.excerpt}",
            ]
        )
    stderr, _ = truncate_output(execution.stderr, MAX_DIAGNOSTIC_STDERR_CHARS)
    stdout, _ = truncate_output(execution.stdout, MAX_DIAGNOSTIC_STDOUT_CHARS)
    if stderr:
        lines.extend(["stderr:", stderr])
    if stdout:
        lines.extend(["stdout:", stdout])
    context, _ = truncate_output(
        "\n".join(lines),
        MAX_REPOSITORY_DIAGNOSTIC_CONTEXT_CHARS,
    )
    return context


def _normalize_repository_rule(
    execution: RepositoryExecution,
    rule: RuleDecision,
) -> RuleDecision:
    evidence = list(rule.evidence)
    _append_unique(evidence, f"Repository execution status: {execution.status}")
    for failure in execution.failures:
        _append_unique(evidence, failure.testId, 240)
        _append_unique(evidence, failure.location, 240)
        _append_unique(evidence, failure.message, 500)
        _append_unique(evidence, failure.excerpt)

    updates: dict[str, object] = {
        "failedStage": execution.failedStage,
        "evidence": evidence,
    }
    if execution.status == "TEST_FAILED" and rule.errorType == "UNKNOWN":
        updates.update(
            {
                "errorType": "WRONG_ANSWER",
                "errorSubtype": "ALGORITHM_ERROR",
                "confidence": max(rule.confidence, 0.8),
                "explanation": (
                    "Repository pytest reported a test failure without a more "
                    "specific exception signal."
                ),
            }
        )
    return rule.model_copy(update=updates)


def _structured_location(failures: list[RepositoryTestFailure]) -> str:
    for failure in failures:
        if failure.location.strip():
            return failure.location.strip()
    for failure in failures:
        if failure.testId.strip():
            return failure.testId.strip()
    return ""


def _append_unique(
    items: list[str],
    value: str,
    limit: int = MAX_EVIDENCE_VALUE_CHARS,
) -> None:
    text = str(value or "").strip()
    text, _ = truncate_output(text, limit)
    if text and text not in items:
        items.append(text)
