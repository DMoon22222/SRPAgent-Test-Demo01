from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from app.config import settings
from app.sandbox.base import CodeSandbox
from app.sandbox.support import build_run_result, execution, format_log, normalize_language, temporary_workspace
from app.schemas import ExecuteAndAnalyzeRequest, Execution


class LocalSandbox(CodeSandbox):
    def run(self, request: ExecuteAndAnalyzeRequest) -> Execution:
        language = normalize_language(request.language)
        if language is None:
            return _unsupported_language(request.language)

        with temporary_workspace("srp_local_") as workdir:
            if language == "java":
                return self._run_java(request, workdir)
            return self._run_python(request, workdir)

    def check_syntax(self, request: ExecuteAndAnalyzeRequest) -> Execution:
        language = normalize_language(request.language)
        if language is None:
            return _unsupported_language(request.language)

        with temporary_workspace("srp_local_check_") as workdir:
            if language == "java":
                source = workdir / "Main.java"
                source.write_text(request.code, encoding="utf-8")
                result = _run_process(["javac", "-encoding", "UTF-8", "Main.java"], workdir, "")
                return _syntax_result("java", request, result, "javac -encoding UTF-8 Main.java")

            source = workdir / "Main.py"
            source.write_text(request.code, encoding="utf-8")
            python_cmd = find_python_command()
            if python_cmd is None:
                return _environment_error("python", "PRE_CHECK", "未找到可用 Python 命令。", "python --version")
            command = python_cmd + ["-m", "py_compile", "Main.py"]
            result = _run_process(command, workdir, "")
            return _syntax_result("python", request, result, " ".join(command))

    def _run_java(self, request: ExecuteAndAnalyzeRequest, workdir: Path) -> Execution:
        (workdir / "Main.java").write_text(request.code, encoding="utf-8")
        compile_cmd = ["javac", "-encoding", "UTF-8", "Main.java"]
        compile_result = _run_process(compile_cmd, workdir, "")
        if compile_result["timeout"]:
            return execution(False, "TIME_LIMIT_EXCEEDED", "COMPILE", False, True, -1, compile_result["stdout"], compile_result["stderr"], "Java 编译超时。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], " ".join(compile_cmd), "java")
        if compile_result["exitCode"] != 0:
            return execution(False, "COMPILE_ERROR", "COMPILE", False, False, compile_result["exitCode"], compile_result["stdout"], compile_result["stderr"], "Java 编译失败。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], " ".join(compile_cmd), "java")

        run_cmd = ["java", "-Dfile.encoding=UTF-8", "Main"]
        run_result = _run_process(run_cmd, workdir, request.stdin)
        return build_run_result("java", request, run_result, True, " ".join(run_cmd))

    def _run_python(self, request: ExecuteAndAnalyzeRequest, workdir: Path) -> Execution:
        python_cmd = find_python_command()
        if python_cmd is None:
            return _environment_error("python", "PRE_CHECK", "未找到可用 Python 命令。", "python --version")

        (workdir / "Main.py").write_text(request.code, encoding="utf-8")
        compile_cmd = python_cmd + ["-m", "py_compile", "Main.py"]
        compile_result = _run_process(compile_cmd, workdir, "")
        if compile_result["timeout"]:
            return execution(False, "TIME_LIMIT_EXCEEDED", "COMPILE", False, True, -1, compile_result["stdout"], compile_result["stderr"], "Python 语法检查超时。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], " ".join(compile_cmd), "python")
        if compile_result["exitCode"] != 0:
            return execution(False, "COMPILE_ERROR", "COMPILE", False, False, compile_result["exitCode"], compile_result["stdout"], compile_result["stderr"], "Python 语法检查失败。\n" + format_log(compile_result), compile_result["durationMs"], request.expectedOutput, compile_result["stdout"], " ".join(compile_cmd), "python")

        run_cmd = python_cmd + ["Main.py"]
        run_result = _run_process(run_cmd, workdir, request.stdin)
        return build_run_result("python", request, run_result, True, " ".join(run_cmd))


def find_python_command() -> list[str] | None:
    candidates = [["python"], ["py", "-3"]] if os.name == "nt" else [["python3"], ["python"]]
    for candidate in candidates:
        if shutil.which(candidate[0]) is None:
            continue
        try:
            subprocess.run(candidate + ["--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
            return candidate
        except Exception:
            continue
    return None


def _run_process(command: list[str], workdir: Path, stdin: str) -> dict[str, object]:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.sandbox_timeout_ms / 1000,
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
    except FileNotFoundError as exc:
        return {
            "stdout": "",
            "stderr": str(exc),
            "exitCode": -1,
            "timeout": False,
            "durationMs": int((time.perf_counter() - start) * 1000),
        }


def _syntax_result(language: str, request: ExecuteAndAnalyzeRequest, result: dict[str, object], command: str) -> Execution:
    if result["timeout"]:
        return execution(False, "TIME_LIMIT_EXCEEDED", "COMPILE", False, True, -1, str(result["stdout"]), str(result["stderr"]), f"{language} 语法检查超时。\n" + format_log(result), int(result["durationMs"]), request.expectedOutput, str(result["stdout"]), command, language)
    if int(result["exitCode"]) != 0:
        return execution(False, "COMPILE_ERROR", "COMPILE", False, False, int(result["exitCode"]), str(result["stdout"]), str(result["stderr"]), f"{language} 语法检查失败。\n" + format_log(result), int(result["durationMs"]), request.expectedOutput, str(result["stdout"]), command, language)
    return execution(True, "SUCCESS", "NONE", True, False, 0, str(result["stdout"]), str(result["stderr"]), "", int(result["durationMs"]), request.expectedOutput, str(result["stdout"]), command, language)


def _unsupported_language(language: str) -> Execution:
    message = f"不支持的语言：{language}。仅支持 java、python、python3、py。"
    return execution(False, "ENVIRONMENT_ERROR", "PRE_CHECK", False, False, -1, "", message, message, 0, "", "", "language normalization", language)


def _environment_error(language: str, stage: str, message: str, command: str) -> Execution:
    return execution(False, "ENVIRONMENT_ERROR", stage, False, False, -1, "", message, message, 0, "", "", command, language)
