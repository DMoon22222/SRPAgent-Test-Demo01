"""Fixed-profile Docker pytest runner for disposable repository snapshots."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.repository.base import RepositoryRunner, RepositoryRunSpec
from app.repository.pytest_parser import PytestReportError, parse_pytest_junit
from app.repository.target_validation import (
    RepositoryTargetError,
    validate_test_targets,
)
from app.sandbox.support import safe, truncate_output
from app.schemas import (
    RepositoryExecution,
    RepositoryObservation,
    RepositoryTestFailure,
    RepositoryTestSummary,
)

CONTAINER_NAME_PREFIX = "srp-repo-"
RESULT_DIRECTORY_PREFIX = ".srp_test_results_"
CONTAINER_WORKSPACE = "/workspace"
PREFLIGHT_TIMEOUT_SECONDS = 10


class DockerPytestRepositoryRunner(RepositoryRunner):
    """Run a fixed pytest command with only a writable snapshot mounted."""

    def run(
        self,
        snapshot_path: Path,
        spec: RepositoryRunSpec,
    ) -> RepositoryExecution:
        started = time.perf_counter()
        snapshot = snapshot_path.resolve(strict=True)
        if spec.runner != "pytest":
            return _execution_error(
                status="ENVIRONMENT_ERROR",
                failed_stage="PRE_CHECK",
                message="Unsupported repository runner profile.",
                execution_time_ms=_elapsed_ms(started),
            )

        try:
            targets = validate_test_targets(snapshot, spec.test_targets)
        except RepositoryTargetError as exc:
            return _execution_error(
                status="TEST_FAILED",
                failed_stage="TEST",
                message=str(exc),
                execution_time_ms=_elapsed_ms(started),
            )

        preflight_error = _check_repository_docker()
        if preflight_error:
            return _execution_error(
                status="ENVIRONMENT_ERROR",
                failed_stage="PRE_CHECK",
                message=preflight_error,
                execution_time_ms=_elapsed_ms(started),
            )

        result_directory = snapshot / f"{RESULT_DIRECTORY_PREFIX}{uuid4().hex}"
        result_directory.mkdir()
        report_path = result_directory / "junit.xml"
        container_name = f"{CONTAINER_NAME_PREFIX}{uuid4().hex}"
        command = _build_repository_docker_args(
            snapshot_path=snapshot,
            test_targets=targets,
            container_name=container_name,
            junit_relative_path=f"{result_directory.name}/junit.xml",
        )

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=spec.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _remove_timed_out_container(container_name)
            shutil.rmtree(result_directory, ignore_errors=True)
            return _execution_result(
                success=False,
                status="TIME_LIMIT_EXCEEDED",
                failed_stage="TEST",
                timeout=True,
                exit_code=-1,
                execution_time_ms=_elapsed_ms(started),
                summary=RepositoryTestSummary(),
                failures=(),
                stdout=_timeout_text(exc.stdout),
                stderr=_timeout_text(exc.stderr),
            )
        except OSError as exc:
            shutil.rmtree(result_directory, ignore_errors=True)
            return _execution_error(
                status="SANDBOX_ERROR",
                failed_stage="SANDBOX",
                message=f"Docker repository execution failed: {exc}",
                execution_time_ms=_elapsed_ms(started),
            )
        finally:
            if not report_path.exists():
                shutil.rmtree(result_directory, ignore_errors=True)

        stdout = safe(completed.stdout)
        stderr = safe(completed.stderr)
        if completed.returncode >= 125:
            shutil.rmtree(result_directory, ignore_errors=True)
            return _execution_result(
                success=False,
                status="SANDBOX_ERROR",
                failed_stage="SANDBOX",
                timeout=False,
                exit_code=completed.returncode,
                execution_time_ms=_elapsed_ms(started),
                summary=RepositoryTestSummary(),
                failures=(),
                stdout=stdout,
                stderr=stderr or "Docker container infrastructure failed.",
            )

        try:
            report = parse_pytest_junit(report_path)
        except PytestReportError as exc:
            return _execution_result(
                success=False,
                status="SANDBOX_ERROR",
                failed_stage="SANDBOX",
                timeout=False,
                exit_code=completed.returncode,
                execution_time_ms=_elapsed_ms(started),
                summary=RepositoryTestSummary(),
                failures=(),
                stdout=stdout,
                stderr=_join_error(stderr, str(exc)),
            )
        finally:
            shutil.rmtree(result_directory, ignore_errors=True)

        success = completed.returncode == 0 and report.summary.failed == 0
        status = "SUCCESS" if success else "TEST_FAILED"
        signals = []
        if report.failure_list_truncated:
            signals.append("failure list truncated")
        return _execution_result(
            success=success,
            status=status,
            failed_stage="NONE" if success else "TEST",
            timeout=False,
            exit_code=completed.returncode,
            execution_time_ms=_elapsed_ms(started),
            summary=report.summary,
            failures=report.failures,
            stdout=stdout,
            stderr=stderr,
            extra_signals=signals,
        )


def _build_repository_docker_args(
    *,
    snapshot_path: Path,
    test_targets: tuple[str, ...],
    container_name: str,
    junit_relative_path: str,
) -> list[str]:
    """Build argv directly; no shell command or client-controlled options."""
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--memory",
        settings.sandbox_docker_memory,
        "--memory-swap",
        settings.sandbox_docker_memory,
        "--cpus",
        settings.sandbox_docker_cpus,
        "--pids-limit",
        settings.sandbox_docker_pids_limit,
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=64m",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONUNBUFFERED=1",
        "--env",
        "PYTHONNOUSERSITE=1",
        "--mount",
        f"type=bind,source={snapshot_path},target={CONTAINER_WORKSPACE}",
        "--workdir",
        CONTAINER_WORKSPACE,
        settings.sandbox_docker_image,
        "python3",
        "-m",
        "pytest",
        "-q",
        "--color=no",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        f"--junitxml={CONTAINER_WORKSPACE}/{junit_relative_path}",
        *test_targets,
    ]


def _check_repository_docker() -> str:
    checks = (
        (["docker", "--version"], "Docker CLI is unavailable"),
        (["docker", "info"], "Docker daemon is unavailable"),
        (
            ["docker", "image", "inspect", settings.sandbox_docker_image],
            f"Docker image is unavailable: {settings.sandbox_docker_image}",
        ),
        (_pytest_preflight_args(), "pytest is unavailable in the Docker image"),
    )
    for command, label in checks:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=PREFLIGHT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{label}: {exc}"
        if completed.returncode != 0:
            detail = safe(completed.stderr or completed.stdout).strip()
            return f"{label}: {detail or 'preflight command failed'}"
    return ""


def _pytest_preflight_args() -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=16m",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        settings.sandbox_docker_image,
        "python3",
        "-m",
        "pytest",
        "--version",
    ]


def _remove_timed_out_container(container_name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _execution_error(
    *,
    status: str,
    failed_stage: str,
    message: str,
    execution_time_ms: int,
) -> RepositoryExecution:
    return _execution_result(
        success=False,
        status=status,
        failed_stage=failed_stage,
        timeout=False,
        exit_code=-1,
        execution_time_ms=execution_time_ms,
        summary=RepositoryTestSummary(),
        failures=(),
        stdout="",
        stderr=message,
    )


def _execution_result(
    *,
    success: bool,
    status: str,
    failed_stage: str,
    timeout: bool,
    exit_code: int,
    execution_time_ms: int,
    summary: RepositoryTestSummary,
    failures: tuple[RepositoryTestFailure, ...],
    stdout: str,
    stderr: str,
    extra_signals: list[str] | None = None,
) -> RepositoryExecution:
    max_chars = settings.sandbox_max_output_chars
    bounded_stdout, stdout_truncated = truncate_output(stdout, max_chars)
    bounded_stderr, stderr_truncated = truncate_output(stderr, max_chars)
    signals = _summary_signals(summary)
    signals.extend(extra_signals or [])
    failing_tests = [failure.testId for failure in failures]
    return RepositoryExecution(
        success=success,
        status=status,
        failedStage=failed_stage,
        runner="pytest",
        timeout=timeout,
        exitCode=exit_code,
        executionTimeMs=max(0, execution_time_ms),
        summary=summary,
        failures=list(failures),
        stdout=bounded_stdout,
        stderr=bounded_stderr,
        observation=RepositoryObservation(
            observationId=str(uuid4()),
            runner="pytest",
            status=status,
            shortSummary=_short_summary(status, summary),
            importantSignals=signals,
            failingTests=failing_tests,
            stdoutTruncated=stdout_truncated,
            stderrTruncated=stderr_truncated,
            nextActionHint=_next_action_hint(status),
        ),
    )


def _short_summary(status: str, summary: RepositoryTestSummary) -> str:
    if status == "SUCCESS":
        return f"{summary.passed} tests passed."
    if status == "TEST_FAILED":
        return f"{summary.failed} tests failed, {summary.passed} passed."
    if status == "TIME_LIMIT_EXCEEDED":
        return "Repository tests exceeded the configured timeout."
    if status == "ENVIRONMENT_ERROR":
        return "Repository test environment is unavailable."
    return "Repository sandbox execution failed."


def _summary_signals(summary: RepositoryTestSummary) -> list[str]:
    signals = []
    if summary.failed:
        signals.append(f"{summary.failed} failed")
    if summary.passed:
        signals.append(f"{summary.passed} passed")
    if summary.skipped:
        signals.append(f"{summary.skipped} skipped")
    return signals


def _next_action_hint(status: str) -> str:
    if status == "TEST_FAILED":
        return "Inspect the failing tests and relevant source code."
    if status == "TIME_LIMIT_EXCEEDED":
        return "Inspect tests for blocking calls, infinite loops, or excessive work."
    if status == "ENVIRONMENT_ERROR":
        return "Check Docker availability and the configured sandbox image."
    if status == "SANDBOX_ERROR":
        return "Inspect the Docker runner output and sandbox configuration."
    return "No further execution action is required."


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _timeout_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return safe(value)


def _join_error(stderr: str, message: str) -> str:
    return f"{stderr.rstrip()}\n{message}".strip()
