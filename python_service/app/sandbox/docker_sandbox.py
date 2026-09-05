from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.config import settings
from app.sandbox.base import CodeSandbox
from app.sandbox.support import (
    build_run_result,
    execution,
    format_log,
    normalize_language,
    temporary_workspace,
)
from app.schemas import ExecuteAndAnalyzeRequest, Execution


class DockerSandbox(CodeSandbox):
    def run(self, request: ExecuteAndAnalyzeRequest) -> Execution:
        language = normalize_language(request.language)
        if language is None:
            return _unsupported_language(request.language)

        docker_error = _check_docker()
        if docker_error:
            return _docker_environment_error(docker_error)

        with temporary_workspace("srp_docker_") as workdir:
            workdir = workdir.resolve()
            if language == "java":
                return self._run_java(request, workdir)
            return self._run_python(request, workdir)

    def check_syntax(self, request: ExecuteAndAnalyzeRequest) -> Execution:
        language = normalize_language(request.language)
        if language is None:
            return _unsupported_language(request.language)

        docker_error = _check_docker()
        if docker_error:
            return _docker_environment_error(docker_error)

        with temporary_workspace("srp_docker_check_") as workdir:
            workdir = workdir.resolve()
            if language == "java":
                (workdir / "Main.java").write_text(request.code, encoding="utf-8")
                command = "javac -encoding UTF-8 Main.java"
            else:
                (workdir / "Main.py").write_text(request.code, encoding="utf-8")
                command = "python3 -m py_compile Main.py"

            result = _docker_run(workdir, command, "")
            return _syntax_result(language, request, result, command)

    def _run_java(self, request: ExecuteAndAnalyzeRequest, workdir: Path) -> Execution:
        (workdir / "Main.java").write_text(request.code, encoding="utf-8")
        compile_command = "javac -encoding UTF-8 Main.java"
        compile_result = _docker_run(workdir, compile_command, "")
        if compile_result["timeout"]:
            return execution(False, "TIME_LIMIT_EXCEEDED", "COMPILE", False, True, -1, compile_result["stdout"], compile_result["stderr"], "Java Docker 编译超时。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], compile_command, "java")
        if compile_result["exitCode"] != 0:
            return execution(False, "COMPILE_ERROR", "COMPILE", False, False, compile_result["exitCode"], compile_result["stdout"], compile_result["stderr"], "Java Docker 编译失败。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], compile_command, "java")

        run_command = "java -Dfile.encoding=UTF-8 Main"
        run_result = _docker_run(workdir, run_command, request.stdin)
        return build_run_result("java", request, run_result, True, run_command)

    def _run_python(self, request: ExecuteAndAnalyzeRequest, workdir: Path) -> Execution:
        (workdir / "Main.py").write_text(request.code, encoding="utf-8")
        compile_command = "python3 -m py_compile Main.py"
        compile_result = _docker_run(workdir, compile_command, "")
        if compile_result["timeout"]:
            return execution(False, "TIME_LIMIT_EXCEEDED", "COMPILE", False, True, -1, compile_result["stdout"], compile_result["stderr"], "Python Docker 语法检查超时。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], compile_command, "python")
        if compile_result["exitCode"] != 0:
            return execution(False, "COMPILE_ERROR", "COMPILE", False, False, compile_result["exitCode"], compile_result["stdout"], compile_result["stderr"], "Python Docker 语法检查失败。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], compile_command, "python")

        run_command = "python3 Main.py"
        run_result = _docker_run(workdir, run_command, request.stdin)
        return build_run_result("python", request, run_result, True, run_command)


def _docker_base_args(workdir: Path) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-i",
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
        "--mount",
        f"type=bind,source={workdir},target=/workspace",
        "--workdir",
        "/workspace",
        settings.sandbox_docker_image,
        "bash",
        "-lc",
    ]


def _docker_run(workdir: Path, shell_command: str, stdin: str) -> dict[str, object]:
    command = _docker_base_args(workdir) + [shell_command]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.sandbox_timeout_ms / 1000,
            check=False,
        )
        return {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exitCode": completed.returncode,
            "timeout": False,
            "durationMs": int((time.perf_counter() - start) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "exitCode": -1,
            "timeout": True,
            "durationMs": int((time.perf_counter() - start) * 1000),
        }


def _check_docker() -> str:
    try:
        version = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Docker CLI preflight failed: {exc}"
    if version.returncode != 0:
        detail = version.stderr or version.stdout or "unknown docker --version error"
        return f"Docker CLI preflight failed: {detail}"

    try:
        daemon = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Docker daemon preflight failed: {exc}"
    if daemon.returncode != 0:
        detail = daemon.stderr or daemon.stdout or "unknown docker info error"
        return f"Docker daemon preflight failed: {detail}"
    return ""


def _syntax_result(language: str, request: ExecuteAndAnalyzeRequest, result: dict[str, object], command: str) -> Execution:
    if result["timeout"]:
        return execution(False, "TIME_LIMIT_EXCEEDED", "COMPILE", False, True, -1, str(result["stdout"]), str(result["stderr"]), f"{language} Docker 语法检查超时。\n" + format_log(result), int(result["durationMs"]), request.expectedOutput, str(result["stdout"]), command, language)
    if int(result["exitCode"]) != 0:
        return execution(False, "COMPILE_ERROR", "COMPILE", False, False, int(result["exitCode"]), str(result["stdout"]), str(result["stderr"]), f"{language} Docker 语法检查失败。\n" + format_log(result), int(result["durationMs"]), request.expectedOutput, str(result["stdout"]), command, language)
    return execution(True, "SUCCESS", "NONE", True, False, 0, str(result["stdout"]), str(result["stderr"]), "", int(result["durationMs"]), request.expectedOutput, str(result["stdout"]), command, language)


def _docker_environment_error(detail: str) -> Execution:
    message = (
        "Docker 不可用。请确认 Docker CLI 已安装、Docker Desktop 已启动，"
        "并且 docker info 可以连接 daemon。\n"
        + detail
    )
    return execution(
        False,
        "ENVIRONMENT_ERROR",
        "PRE_CHECK",
        False,
        False,
        -1,
        "",
        message,
        message,
        0,
        "",
        "",
        "docker --version; docker info",
        "docker",
    )


def _unsupported_language(language: str) -> Execution:
    message = f"不支持的语言：{language}。仅支持 java、python、python3、py。"
    return execution(False, "ENVIRONMENT_ERROR", "PRE_CHECK", False, False, -1, "", message, message, 0, "", "", "language normalization", language)
