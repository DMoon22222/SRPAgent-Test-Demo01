from unittest.mock import patch

import pytest

from app.analyzer.error_analyzer import ErrorAnalyzer
from app.config import settings
from app.repository.diagnosis import (
    MAX_REPOSITORY_DIAGNOSTIC_CONTEXT_CHARS,
    build_repository_diagnostic_context,
    diagnose_repository_execution,
)
from app.schemas import (
    RepositoryExecution,
    RepositoryTestFailure,
    RepositoryTestSummary,
)


def execution(
    status="TEST_FAILED",
    *,
    failure_text="plain assertion mismatch",
    location="tests/test_calc.py:7",
):
    success = status == "SUCCESS"
    timeout = status == "TIME_LIMIT_EXCEEDED"
    stage = "NONE" if success else (
        "PRE_CHECK" if status == "ENVIRONMENT_ERROR" else (
            "SANDBOX" if status == "SANDBOX_ERROR" else "TEST"
        )
    )
    failures = [] if success or timeout else [
        RepositoryTestFailure(
            testId="tests/test_calc.py::test_add",
            location=location,
            message=failure_text,
            excerpt=failure_text,
        )
    ]
    return RepositoryExecution(
        success=success,
        status=status,
        failedStage=stage,
        runner="pytest",
        timeout=timeout,
        exitCode=0 if success else -1 if timeout else 1,
        executionTimeMs=12,
        summary=RepositoryTestSummary(
            total=1,
            passed=1 if success else 0,
            failed=0 if success or timeout else 1,
        ),
        failures=failures,
        stderr=failure_text,
    )


@pytest.fixture(autouse=True)
def no_llm_key(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "")


def test_assertion_failure_is_rule_first_wrong_answer():
    analysis = diagnose_repository_execution(
        execution(failure_text="AssertionError: assert -1 == 5")
    )

    assert analysis is not None
    assert analysis.failedStage == "TEST"
    assert analysis.errorType == "WRONG_ANSWER"
    assert analysis.errorSubtype == "ALGORITHM_ERROR"
    assert analysis.suspectedLocation == "tests/test_calc.py:7"
    assert "tests/test_calc.py::test_add" in analysis.evidence


def test_dependency_missing_preserves_specific_rule_and_retrieval():
    analysis = diagnose_repository_execution(
        execution(failure_text="ModuleNotFoundError: No module named 'requests'")
    )

    assert analysis.failedStage == "TEST"
    assert analysis.errorType == "API_MISUSE"
    assert analysis.errorSubtype == "DEPENDENCY_MISSING"
    assert analysis.needRetrieval is True
    assert "requests" in analysis.retrievalQuery


def test_divide_by_zero_preserves_runtime_type_but_test_stage():
    analysis = diagnose_repository_execution(
        execution(failure_text="ZeroDivisionError: division by zero")
    )

    assert analysis.failedStage == "TEST"
    assert analysis.errorType == "RUNTIME_ERROR"
    assert analysis.errorSubtype == "DIVIDE_BY_ZERO"


def test_timeout_uses_test_stage_and_existing_timeout_subtype():
    analysis = diagnose_repository_execution(
        execution("TIME_LIMIT_EXCEEDED", failure_text="timed out")
    )

    assert analysis.failedStage == "TEST"
    assert analysis.errorType == "TIME_LIMIT_EXCEEDED"
    assert analysis.errorSubtype == "INFINITE_LOOP"


def test_generic_pytest_failure_uses_deterministic_fallback():
    analysis = diagnose_repository_execution(execution())

    assert analysis.failedStage == "TEST"
    assert analysis.errorType == "WRONG_ANSWER"
    assert analysis.errorSubtype == "ALGORITHM_ERROR"
    assert analysis.ruleDecision.decisionSource == "RULE"


@pytest.mark.parametrize(
    "status",
    ["SUCCESS", "ENVIRONMENT_ERROR", "SANDBOX_ERROR"],
)
def test_non_code_failure_statuses_do_not_generate_analysis(status):
    assert diagnose_repository_execution(execution(status)) is None


def test_no_llm_key_still_returns_deterministic_fallback():
    analysis = diagnose_repository_execution(execution())

    assert "未配置 DASHSCOPE_API_KEY" in analysis.rootCause
    assert analysis.repairSuggestion
    assert analysis.classificationSource == "RULE_FIRST_LLM_EXPLAIN"


def test_llm_cannot_override_repository_rule_labels(monkeypatch):
    monkeypatch.setattr(settings, "dashscope_api_key", "configured-for-test")
    conflicting = {
        "failedStage": "COMPILE",
        "errorType": "COMPILE_ERROR",
        "errorSubtype": "SYNTAX_ERROR",
        "rootCause": "Explanation only.",
        "suspectedLocation": "invented.py:99",
    }
    with patch.object(ErrorAnalyzer, "_call_llm", return_value=conflicting):
        analysis = diagnose_repository_execution(
            execution(failure_text="ZeroDivisionError: division by zero")
        )

    assert analysis.failedStage == "TEST"
    assert analysis.errorType == "RUNTIME_ERROR"
    assert analysis.errorSubtype == "DIVIDE_BY_ZERO"
    assert analysis.suspectedLocation == "tests/test_calc.py:7"
    assert analysis.llmOverrodeRule is False


def test_diagnostic_context_is_bounded_and_uses_execution_only():
    result = execution(failure_text="x" * 20_000)

    context = build_repository_diagnostic_context(result)

    assert len(context) <= MAX_REPOSITORY_DIAGNOSTIC_CONTEXT_CHARS
    assert "Repository status: TEST_FAILED" in context
    assert "tests/test_calc.py::test_add" in context
