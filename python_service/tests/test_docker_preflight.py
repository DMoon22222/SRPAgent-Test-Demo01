import subprocess
from unittest.mock import call, patch

from app.sandbox.docker_sandbox import DockerSandbox, _check_docker
from app.schemas import ExecuteAndAnalyzeRequest


def completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def request():
    return ExecuteAndAnalyzeRequest(code="print('ok')", language="python")


@patch("app.sandbox.docker_sandbox.subprocess.run")
def test_docker_cli_missing_maps_to_environment_precheck(mock_run):
    mock_run.side_effect = FileNotFoundError("docker executable not found")

    result = DockerSandbox().run(request())

    assert result.success is False
    assert result.status == "ENVIRONMENT_ERROR"
    assert result.failedStage == "PRE_CHECK"
    assert "Docker CLI preflight failed" in result.errorLog


@patch("app.sandbox.docker_sandbox.subprocess.run")
def test_docker_version_failure_maps_to_environment_precheck(mock_run):
    mock_run.return_value = completed(
        ["docker", "--version"],
        returncode=1,
        stderr="invalid docker installation",
    )

    result = DockerSandbox().check_syntax(request())

    assert result.status == "ENVIRONMENT_ERROR"
    assert result.failedStage == "PRE_CHECK"
    assert "invalid docker installation" in result.stderr
    assert mock_run.call_count == 1


@patch("app.sandbox.docker_sandbox.subprocess.run")
def test_docker_info_failure_detects_unavailable_daemon(mock_run):
    mock_run.side_effect = [
        completed(["docker", "--version"], stdout="Docker version 28"),
        completed(
            ["docker", "info"],
            returncode=1,
            stderr="daemon is unavailable",
        ),
    ]

    result = DockerSandbox().run(request())

    assert result.status == "ENVIRONMENT_ERROR"
    assert result.failedStage == "PRE_CHECK"
    assert "Docker daemon preflight failed" in result.errorLog
    assert "daemon is unavailable" in result.errorLog


@patch("app.sandbox.docker_sandbox.subprocess.run")
def test_docker_cannot_connect_is_not_reported_as_compile_error(mock_run):
    mock_run.side_effect = [
        completed(["docker", "--version"], stdout="Docker version 28"),
        completed(
            ["docker", "info"],
            returncode=1,
            stderr="Cannot connect to the Docker daemon",
        ),
    ]

    result = DockerSandbox().check_syntax(request())

    assert result.status == "ENVIRONMENT_ERROR"
    assert result.status != "COMPILE_ERROR"
    assert result.failedStage == "PRE_CHECK"


@patch("app.sandbox.docker_sandbox.subprocess.run")
def test_docker_preflight_requires_cli_and_daemon_success(mock_run):
    mock_run.side_effect = [
        completed(["docker", "--version"], stdout="Docker version 28"),
        completed(["docker", "info"], stdout="Server Version: 28"),
    ]

    assert _check_docker() == ""
    assert mock_run.call_args_list == [
        call(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ),
        call(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ),
    ]
