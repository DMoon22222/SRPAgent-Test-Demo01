import subprocess
from pathlib import Path
from unittest.mock import call, patch

import pytest

from app.config import settings
from app.repository.base import RepositoryRunSpec
from app.repository.docker_runner import (
    DockerPytestRepositoryRunner,
    _build_repository_docker_args,
    _check_repository_docker,
)
from app.repository.pytest_parser import PytestReport, PytestReportError
from app.schemas import RepositoryTestFailure, RepositoryTestSummary


def completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def make_snapshot(tmp_path: Path) -> Path:
    snapshot = tmp_path / "snapshot"
    (snapshot / "tests").mkdir(parents=True)
    (snapshot / "tests" / "test_x.py").write_text("pass\n", encoding="utf-8")
    return snapshot


def spec(*targets, timeout=37):
    return RepositoryRunSpec(
        runner="pytest",
        test_targets=tuple(targets),
        timeout_seconds=timeout,
    )


def parsed(total=1, passed=1, failed=0, failures=(), truncated=False):
    return PytestReport(
        summary=RepositoryTestSummary(
            total=total,
            passed=passed,
            failed=failed,
        ),
        failures=tuple(failures),
        failure_list_truncated=truncated,
    )


@patch("app.repository.docker_runner.parse_pytest_junit")
@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_success_maps_to_repository_execution(mock_check, mock_run, mock_parse, tmp_path):
    mock_run.return_value = completed([], stdout="1 passed")
    mock_parse.return_value = parsed()

    result = DockerPytestRepositoryRunner().run(make_snapshot(tmp_path), spec())

    assert result.success is True
    assert result.status == "SUCCESS"
    assert result.failedStage == "NONE"
    assert result.summary.passed == 1
    assert result.observation.shortSummary == "1 tests passed."
    mock_check.assert_called_once_with()


@patch("app.repository.docker_runner.parse_pytest_junit")
@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
@pytest.mark.parametrize("exit_code", [1, 2, 5])
def test_pytest_nonzero_exit_is_test_failed_not_sandbox_error(
    mock_check,
    mock_run,
    mock_parse,
    tmp_path,
    exit_code,
):
    failure = RepositoryTestFailure(testId="tests/test_x.py::test_x")
    mock_run.return_value = completed([], returncode=exit_code, stdout="1 failed")
    mock_parse.return_value = parsed(
        total=1,
        passed=0,
        failed=1,
        failures=(failure,),
    )

    result = DockerPytestRepositoryRunner().run(make_snapshot(tmp_path), spec())

    assert result.success is False
    assert result.status == "TEST_FAILED"
    assert result.failedStage == "TEST"
    assert result.exitCode == exit_code
    assert result.failures == [failure]
    assert result.observation.failingTests == [failure.testId]


@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_timeout_maps_and_force_removes_named_container(mock_check, mock_run, tmp_path):
    mock_run.side_effect = [
        subprocess.TimeoutExpired(["docker", "run"], timeout=3, output="partial"),
        completed(["docker", "rm", "-f", "container"]),
    ]

    result = DockerPytestRepositoryRunner().run(
        make_snapshot(tmp_path),
        spec(timeout=3),
    )

    assert result.status == "TIME_LIMIT_EXCEEDED"
    assert result.failedStage == "TEST"
    assert result.timeout is True
    assert result.stdout == "partial"
    run_call, cleanup_call = mock_run.call_args_list
    assert run_call.kwargs["timeout"] == 3
    container_name = run_call.args[0][run_call.args[0].index("--name") + 1]
    assert cleanup_call == call(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_docker_container_infrastructure_failure_maps_to_sandbox(
    mock_check,
    mock_run,
    tmp_path,
):
    mock_run.return_value = completed([], returncode=125, stderr="docker run failed")

    result = DockerPytestRepositoryRunner().run(make_snapshot(tmp_path), spec())

    assert result.status == "SANDBOX_ERROR"
    assert result.failedStage == "SANDBOX"
    assert result.exitCode == 125


@patch("app.repository.docker_runner.parse_pytest_junit")
@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_invalid_or_missing_junit_maps_to_sandbox_error(
    mock_check,
    mock_run,
    mock_parse,
    tmp_path,
):
    mock_run.return_value = completed([], returncode=1, stderr="collection stopped")
    mock_parse.side_effect = PytestReportError("pytest JUnit report is missing")

    result = DockerPytestRepositoryRunner().run(make_snapshot(tmp_path), spec())

    assert result.status == "SANDBOX_ERROR"
    assert "JUnit report is missing" in result.stderr


@patch("app.repository.docker_runner.parse_pytest_junit")
@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_stdout_stderr_and_failure_observation_are_bounded(
    mock_check,
    mock_run,
    mock_parse,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "sandbox_max_output_chars", 80)
    failure = RepositoryTestFailure(testId="tests/test_x.py::test_x")
    mock_run.return_value = completed([], returncode=1, stdout="o" * 500, stderr="e" * 500)
    mock_parse.return_value = parsed(
        total=8,
        passed=2,
        failed=6,
        failures=(failure,),
        truncated=True,
    )

    result = DockerPytestRepositoryRunner().run(make_snapshot(tmp_path), spec())

    assert len(result.stdout) <= 80
    assert len(result.stderr) <= 80
    assert result.observation.stdoutTruncated is True
    assert result.observation.stderrTruncated is True
    assert "failure list truncated" in result.observation.importantSignals


@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_nonexistent_target_is_rejected_before_docker_run(mock_check, mock_run, tmp_path):
    result = DockerPytestRepositoryRunner().run(
        make_snapshot(tmp_path),
        spec("tests/test_missing.py"),
    )

    assert result.status == "TEST_FAILED"
    assert "does not exist" in result.stderr
    mock_check.assert_not_called()
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    "preflight_error",
    [
        "Docker CLI is unavailable: missing",
        "Docker image is unavailable: srp-code-sandbox:latest",
        "pytest is unavailable in the Docker image",
    ],
)
def test_runner_preflight_errors_map_to_environment_precheck(
    preflight_error,
    tmp_path,
):
    with (
        patch(
            "app.repository.docker_runner._check_repository_docker",
            return_value=preflight_error,
        ),
        patch("app.repository.docker_runner.subprocess.run") as mock_run,
    ):
        result = DockerPytestRepositoryRunner().run(make_snapshot(tmp_path), spec())

    assert result.status == "ENVIRONMENT_ERROR"
    assert result.failedStage == "PRE_CHECK"
    assert preflight_error in result.stderr
    mock_run.assert_not_called()


def test_docker_args_only_mount_snapshot_and_keep_fixed_security_profile(tmp_path):
    snapshot = make_snapshot(tmp_path).resolve()
    original = (tmp_path / "original-repository").resolve()
    args = _build_repository_docker_args(
        snapshot_path=snapshot,
        test_targets=("tests/test_x.py::test_a", "tests/test_x.py::test_b"),
        container_name="srp-repo-test",
        junit_relative_path=".srp_test_results_test/junit.xml",
    )
    joined = " ".join(str(arg) for arg in args)

    assert str(snapshot) in joined
    assert str(original) not in joined
    assert [args[index + 1] for index, item in enumerate(args) if item == "--network"] == ["none"]
    for value in (
        "--memory",
        "--memory-swap",
        "--cpus",
        "--pids-limit",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--read-only",
    ):
        assert value in args
    assert "bash" not in args
    assert "-lc" not in args
    assert args[-2:] == ["tests/test_x.py::test_a", "tests/test_x.py::test_b"]


@patch("app.repository.docker_runner.parse_pytest_junit", return_value=parsed())
@patch("app.repository.docker_runner.subprocess.run")
@patch("app.repository.docker_runner._check_repository_docker", return_value="")
def test_subprocess_uses_argv_request_timeout_and_never_shell(
    mock_check,
    mock_run,
    mock_parse,
    tmp_path,
):
    mock_run.return_value = completed([])

    DockerPytestRepositoryRunner().run(
        make_snapshot(tmp_path),
        spec("tests/test_x.py::test_a", timeout=23),
    )

    args, kwargs = mock_run.call_args
    assert isinstance(args[0], list)
    assert kwargs["timeout"] == 23
    assert "shell" not in kwargs
    assert args[0][-1] == "tests/test_x.py::test_a"


@pytest.mark.parametrize(
    ("failure_index", "expected"),
    [
        (0, "Docker CLI is unavailable"),
        (1, "Docker daemon is unavailable"),
        (2, "Docker image is unavailable"),
        (3, "pytest is unavailable"),
    ],
)
@patch("app.repository.docker_runner.subprocess.run")
def test_preflight_failure_mapping(mock_run, failure_index, expected):
    results = [completed([], stdout="ok") for _ in range(4)]
    results[failure_index] = completed([], returncode=1, stderr="not available")
    mock_run.side_effect = results

    error = _check_repository_docker()

    assert expected in error
    assert "not available" in error


@patch("app.repository.docker_runner.subprocess.run")
def test_preflight_checks_image_and_pytest_without_network(mock_run):
    mock_run.side_effect = [completed([], stdout="ok") for _ in range(4)]

    assert _check_repository_docker() == ""

    commands = [item.args[0] for item in mock_run.call_args_list]
    assert commands[2][:3] == ["docker", "image", "inspect"]
    assert commands[3][-4:] == ["python3", "-m", "pytest", "--version"]
    assert commands[3][commands[3].index("--network") + 1] == "none"
