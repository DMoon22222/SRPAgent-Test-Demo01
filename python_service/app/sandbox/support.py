from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.analyzer.error_signal_extractor import extract_signals
from app.config import settings
from app.schemas import AgentObservation, ExecuteAndAnalyzeRequest, Execution


def safe(text: str | None) -> str:
    return "" if text is None else str(text)


def normalize_language(language: str) -> str | None:
    value = safe(language).strip().lower()
    if value == "java":
        return "java"
    if value in {"python", "python3", "py"}:
        return "python"
    return None


def normalize_output(text: str) -> str:
    return safe(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def expected_output_matched(stdout: str, expected_output: str) -> bool:
    if not safe(expected_output).strip():
        return True
    return normalize_output(stdout) == normalize_output(expected_output)


def truncate_output(text: str, max_chars: int) -> tuple[str, bool]:
    value = safe(text)
    if max_chars <= 0 or len(value) <= max_chars:
        return value, False

    marker = f"\n... [TRUNCATED: original length = {len(value)} chars] ...\n"
    keep = max(0, max_chars - len(marker))
    if keep <= 0:
        return marker[:max_chars], True
    head = keep // 2
    tail = keep - head
    tail_text = value[-tail:] if tail > 0 else ""
    return value[:head] + marker + tail_text, True


def format_log(result: dict[str, Any]) -> str:
    return (
        "【stdout】\n"
        + safe(result.get("stdout"))
        + "\n【stderr】\n"
        + safe(result.get("stderr"))
        + "\n【exitCode】\n"
        + str(result.get("exitCode", result.get("exit_code", -1)))
        + "\n【timeout】\n"
        + str(result.get("timeout", False)).lower()
        + "\n【durationMs】\n"
        + str(result.get("durationMs", result.get("duration_ms", 0)))
    )


@contextmanager
def temporary_workspace(prefix: str):
    root = Path(os.environ.get("SANDBOX_TEMP_DIR", Path.cwd() / ".sandbox_tmp"))
    root.mkdir(parents=True, exist_ok=True)
    workdir = root / f"{prefix}{uuid4().hex}"
    workdir.mkdir()
    try:
        yield workdir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def build_run_result(
    language_name: str,
    request: ExecuteAndAnalyzeRequest,
    run_result: dict[str, Any],
    compile_success: bool,
    command: str,
) -> Execution:
    timeout = bool(run_result.get("timeout", False))
    exit_code = int(run_result.get("exitCode", run_result.get("exit_code", -1)))
    stdout = safe(run_result.get("stdout"))
    stderr = safe(run_result.get("stderr"))
    duration_ms = int(run_result.get("durationMs", run_result.get("duration_ms", 0)))

    if timeout:
        error_log = f"{language_name} 运行超时，超过限制 {settings.sandbox_timeout_ms}ms。\n" + format_log(run_result)
        return execution(False, "TIME_LIMIT_EXCEEDED", "RUNTIME", compile_success, True, -1, stdout, stderr, error_log, duration_ms, request.expectedOutput, stdout, command, language_name)

    if exit_code != 0:
        error_log = f"{language_name} 运行失败，exitCode={exit_code}。\n" + format_log(run_result)
        if _is_humaneval_assertion_failure(request, stderr, error_log):
            return execution(False, "WRONG_ANSWER", "TEST", compile_success, False, exit_code, stdout, stderr, error_log, duration_ms, request.expectedOutput, stdout, command, language_name)
        return execution(False, "RUNTIME_ERROR", "RUNTIME", compile_success, False, exit_code, stdout, stderr, error_log, duration_ms, request.expectedOutput, stdout, command, language_name)

    if not expected_output_matched(stdout, request.expectedOutput):
        error_log = (
            f"{language_name} 输出结果与期望不一致。\n"
            "【expectedOutput】\n"
            + safe(request.expectedOutput)
            + "\n【actualOutput】\n"
            + stdout
            + "\n【判断说明】\n程序可以正常通过语法/编译检查并运行，但 stdout 与 expectedOutput 标准化后不相等。"
        )
        return execution(False, "WRONG_ANSWER", "TEST", compile_success, False, exit_code, stdout, stderr, error_log, duration_ms, request.expectedOutput, stdout, command, language_name)

    return execution(True, "SUCCESS", "NONE", compile_success, False, exit_code, stdout, stderr, "", duration_ms, request.expectedOutput, stdout, command, language_name)


def _is_humaneval_assertion_failure(request: ExecuteAndAnalyzeRequest, stderr: str, error_log: str) -> bool:
    benchmark = safe(getattr(request, "benchmark", "")).strip().lower()
    if benchmark != "humaneval":
        return False
    return "AssertionError" in stderr or "AssertionError" in error_log


def execution(
    success: bool,
    status: str,
    failed_stage: str,
    compile_success: bool,
    timeout: bool,
    exit_code: int,
    stdout: str,
    stderr: str,
    error_log: str,
    execution_time_ms: int,
    expected_output: str,
    actual_output: str,
    command: str = "",
    language: str = "",
) -> Execution:
    max_chars = settings.sandbox_max_output_chars
    truncated_stdout, stdout_truncated = truncate_output(stdout, max_chars)
    truncated_stderr, stderr_truncated = truncate_output(stderr, max_chars)
    truncated_error_log, _ = truncate_output(error_log, max_chars)

    return Execution(
        success=success,
        status=status,
        failedStage=failed_stage,
        compileSuccess=compile_success,
        timeout=timeout,
        exitCode=exit_code,
        stdout=truncated_stdout,
        stderr=truncated_stderr,
        errorLog=truncated_error_log,
        executionTimeMs=execution_time_ms,
        expectedOutput=safe(expected_output),
        actualOutput=safe(actual_output),
        observation=make_observation(
            command=command,
            language=language,
            stage=failed_stage,
            status=status,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            error_log=truncated_error_log or truncated_stderr,
        ),
    )


def make_observation(
    command: str,
    language: str,
    stage: str,
    status: str,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    error_log: str = "",
) -> AgentObservation:
    signals = extract_signals(error_log)
    return AgentObservation(
        observationId=str(uuid4()),
        command=command,
        language=normalize_language(language) or safe(language),
        stage=stage,
        status=status,
        shortSummary=_summary(stage, status, signals),
        importantSignals=signals,
        stdoutTruncated=stdout_truncated,
        stderrTruncated=stderr_truncated,
        nextActionHint=_next_action_hint(status, signals),
    )


def _summary(stage: str, status: str, signals: list[str]) -> str:
    if status == "SUCCESS":
        return "程序执行成功，当前用例通过。"
    if status == "WRONG_ANSWER":
        return "程序运行结束，但实际输出与期望输出不一致。"
    if status == "TIME_LIMIT_EXCEEDED":
        return "程序执行超时，可能存在死循环、阻塞输入或复杂度过高。"
    if signals:
        return f"程序在 {stage} 阶段失败，检测到关键信号：{', '.join(signals[:3])}。"
    return f"程序在 {stage} 阶段失败，状态为 {status}。"


def _next_action_hint(status: str, signals: list[str]) -> str:
    joined = " ".join(signals)
    if "DIVIDE_BY_ZERO" in joined or "ZeroDivisionError" in joined:
        return "检查除数是否可能为 0，必要时在除法前增加保护判断。"
    if "SYNTAX_ERROR" in joined or status == "COMPILE_ERROR":
        return "先修复语法或编译错误，再重新运行语法检查接口。"
    if status == "WRONG_ANSWER":
        return "对照 expectedOutput 和 actualOutput，检查输出格式、边界条件和核心算法。"
    if status == "TIME_LIMIT_EXCEEDED":
        return "检查循环终止条件、输入读取逻辑和算法复杂度。"
    if status == "ENVIRONMENT_ERROR":
        return "检查运行环境、Docker Desktop、镜像名称和命令行可用性。"
    return "优先查看 stderr、errorLog 和 importantSignals 后再决定修复策略。"
