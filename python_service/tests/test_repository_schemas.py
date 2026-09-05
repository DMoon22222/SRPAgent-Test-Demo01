import pytest
from pydantic import ValidationError

from app.schemas import (
    RepositoryExecuteAndAnalyzeResult,
    RepositoryExecution,
    RepositoryExecutionRequest,
    RepositoryObservation,
    RepositoryTestFailure,
    RepositoryTestSummary,
)


def test_repository_request_accepts_contract_defaults():
    request = RepositoryExecutionRequest(workspacePath=r"F:\temp\project")

    assert request.workspacePath == r"F:\temp\project"
    assert request.runner == "pytest"
    assert request.testTargets == []
    assert request.timeoutSeconds == 60
    assert request.benchmark == ""


@pytest.mark.parametrize("timeout", [0, 601])
def test_repository_request_rejects_timeout_outside_contract(timeout):
    with pytest.raises(ValidationError):
        RepositoryExecutionRequest(
            workspacePath=r"F:\temp\project",
            timeoutSeconds=timeout,
        )


@pytest.mark.parametrize("workspace_path", ["", "   "])
def test_repository_request_rejects_empty_workspace_path(workspace_path):
    with pytest.raises(ValidationError):
        RepositoryExecutionRequest(workspacePath=workspace_path)


def test_repository_request_rejects_unsupported_runner():
    with pytest.raises(ValidationError):
        RepositoryExecutionRequest(
            workspacePath=r"F:\temp\project",
            runner="maven",
        )


def test_repository_request_rejects_arbitrary_command_field():
    with pytest.raises(ValidationError):
        RepositoryExecutionRequest(
            workspacePath=r"F:\temp\project",
            command="pytest && remove-files",
        )


@pytest.mark.parametrize(
    "target",
    ["", "-p", "../test_x.py", r"C:\secret\test.py", "/secret/test.py"],
)
def test_repository_request_rejects_unsafe_test_target(target):
    with pytest.raises(ValidationError):
        RepositoryExecutionRequest(
            workspacePath=r"F:\temp\project",
            testTargets=[target],
        )


def test_repository_failure_contract_is_compact():
    failure = RepositoryTestFailure(
        testId="tests/test_math.py::test_divide",
        message="assert 4 == 5",
        location="tests/test_math.py:18",
        excerpt="E assert 4 == 5",
    )

    assert failure.testId.endswith("test_divide")
    assert failure.excerpt == "E assert 4 == 5"
    assert not hasattr(failure, "traceback")


def test_repository_observation_contract_tracks_failing_tests():
    observation = RepositoryObservation(
        observationId="repo-observation-1",
        runner="pytest",
        status="TEST_FAILED",
        shortSummary="2 tests failed, 47 passed",
        importantSignals=["ASSERTION_FAILURE"],
        failingTests=["tests/test_math.py::test_divide"],
        nextActionHint="Inspect the failing assertion.",
    )

    assert observation.failingTests == ["tests/test_math.py::test_divide"]
    assert observation.stdoutTruncated is False
    assert observation.stderrTruncated is False


def test_repository_execution_and_result_contract_are_valid():
    failure = RepositoryTestFailure(testId="tests/test_math.py::test_divide")
    execution = RepositoryExecution(
        success=False,
        status="TEST_FAILED",
        failedStage="TEST",
        runner="pytest",
        timeout=False,
        exitCode=1,
        executionTimeMs=125,
        summary=RepositoryTestSummary(total=2, passed=1, failed=1),
        failures=[failure],
        observation=RepositoryObservation(
            runner="pytest",
            status="TEST_FAILED",
            failingTests=[failure.testId],
        ),
    )
    result = RepositoryExecuteAndAnalyzeResult(execution=execution)

    assert result.execution.summary.total == 2
    assert result.execution.summary.skipped == 0
    assert result.execution.failures == [failure]
    assert result.analysis is None
    assert not hasattr(result.execution, "expectedOutput")
    assert not hasattr(result.execution, "actualOutput")
