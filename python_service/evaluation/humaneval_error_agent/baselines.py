from __future__ import annotations

import json
import re
from typing import Any

from app.config import settings


RAW_LOG_PROMPT = """
你是代码错误分析助手。请根据题目、代码和错误日志分析错误原因，并输出 JSON：
{
  "failedStage": "...",
  "errorType": "...",
  "errorSubtype": "...",
  "rootCause": "...",
  "evidence": [],
  "suspectedLocation": "...",
  "needRetrieval": false,
  "retrievalQuery": "",
  "repairSuggestion": "...",
  "confidence": 0.0
}
不要输出 Markdown，不要输出 JSON 之外的文字。
""".strip()


def analyze_rule_only(execution: dict) -> dict:
    error_log = _combined_error_log(execution)
    lowered = error_log.lower()

    if "syntaxerror" in lowered or "indentationerror" in lowered:
        return _result(
            "COMPILE",
            "COMPILE_ERROR",
            "SYNTAX_ERROR",
            "规则判断：检测到 SyntaxError 或 IndentationError，说明代码无法通过 Python 语法检查。",
            _evidence(error_log, ["SyntaxError", "IndentationError"]),
            "先修复语法或缩进错误。",
            0.85,
        )
    if "zerodivisionerror" in lowered or "division by zero" in lowered:
        return _result(
            "RUNTIME",
            "RUNTIME_ERROR",
            "DIVIDE_BY_ZERO",
            "规则判断：检测到 ZeroDivisionError，说明运行时发生除零。",
            _evidence(error_log, ["ZeroDivisionError", "division by zero"]),
            "检查除数是否可能为 0。",
            0.9,
        )
    if "assertionerror" in lowered:
        return _result(
            "TEST",
            "WRONG_ANSWER",
            "ALGORITHM_ERROR",
            "规则判断：检测到 AssertionError，说明 HumanEval 测试断言失败。",
            _evidence(error_log, ["AssertionError"]),
            "检查函数返回值是否符合 HumanEval 测试要求。",
            0.75,
        )
    if "time_limit_exceeded" in lowered or "timeout=true" in lowered or execution.get("timeout") is True:
        return _result(
            "RUNTIME",
            "TIME_LIMIT_EXCEEDED",
            "INFINITE_LOOP",
            "规则判断：检测到超时信号，可能存在无限循环或阻塞。",
            _evidence(error_log, ["TIME_LIMIT_EXCEEDED", "timeout=true", "timeout"]),
            "检查循环终止条件、输入读取和算法复杂度。",
            0.8,
        )
    if "modulenotfounderror" in lowered or "importerror" in lowered:
        return _result(
            "RUNTIME",
            "API_MISUSE",
            "DEPENDENCY_MISSING",
            "规则判断：检测到导入失败，可能缺少第三方依赖或模块名错误。",
            _evidence(error_log, ["ModuleNotFoundError", "ImportError"]),
            "确认依赖是否允许安装、模块名是否正确，必要时检索文档。",
            0.8,
            need_retrieval=True,
            retrieval_query="Python ModuleNotFoundError ImportError dependency usage",
        )
    if execution.get("status") == "WRONG_ANSWER":
        return _result(
            "TEST",
            "WRONG_ANSWER",
            "ALGORITHM_ERROR",
            "规则判断：执行反馈状态为 WRONG_ANSWER。",
            _evidence(error_log, ["WRONG_ANSWER", "expectedOutput", "actualOutput"]),
            "检查算法逻辑、边界条件和输出格式。",
            0.65,
        )
    if int(execution.get("exitCode") or 0) != 0:
        return _result(
            "RUNTIME",
            "RUNTIME_ERROR",
            "UNKNOWN",
            "规则判断：进程非 0 退出，但未命中更具体的内置规则。",
            [],
            "查看 stderr 和 errorLog 后进一步定位。",
            0.4,
        )
    return _result(
        "UNKNOWN",
        "UNKNOWN",
        "UNKNOWN",
        "规则判断：未检测到明确错误信号。",
        [],
        "补充执行日志或人工检查失败样本。",
        0.0,
    )


def analyze_llm_raw_log(problem: str, code: str, raw_error_log: str) -> dict:
    if not settings.dashscope_api_key:
        return _unknown("未配置 DASHSCOPE_API_KEY，跳过 raw-log LLM 对照组。")

    try:
        from openai import OpenAI
    except Exception as exc:
        return _unknown(f"openai 包不可用：{exc}")

    user_prompt = f"""
题目：
{problem}

代码：
{code}

错误日志：
{raw_error_log}
""".strip()

    try:
        client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.dashscope_base_url)
        response = client.chat.completions.create(
            model=settings.dashscope_model,
            messages=[
                {"role": "system", "content": RAW_LOG_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        return parse_analysis_json(content)
    except Exception as exc:
        return _unknown(f"raw-log LLM 调用失败：{exc}")


def parse_analysis_json(content: str) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return _unknown("模型输出不包含可解析 JSON。")
        try:
            data = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return _unknown("模型输出 JSON 解析失败。")
    return _normalize_analysis_shape(data)


def _normalize_analysis_shape(data: dict[str, Any]) -> dict:
    result = {
        "failedStage": data.get("failedStage") or "UNKNOWN",
        "errorType": data.get("errorType") or "UNKNOWN",
        "errorSubtype": data.get("errorSubtype") or "UNKNOWN",
        "rootCause": data.get("rootCause") or "",
        "evidence": data.get("evidence") if isinstance(data.get("evidence"), list) else [],
        "suspectedLocation": data.get("suspectedLocation") or "",
        "needRetrieval": bool(data.get("needRetrieval", False)),
        "retrievalQuery": data.get("retrievalQuery") or "",
        "repairSuggestion": data.get("repairSuggestion") or "",
        "confidence": _clamp_float(data.get("confidence", 0.0)),
    }
    result["json_valid"] = True
    return result


def _result(
    failed_stage: str,
    error_type: str,
    error_subtype: str,
    root_cause: str,
    evidence: list[str],
    repair_suggestion: str,
    confidence: float,
    need_retrieval: bool = False,
    retrieval_query: str = "",
) -> dict:
    return {
        "failedStage": failed_stage,
        "errorType": error_type,
        "errorSubtype": error_subtype,
        "rootCause": root_cause,
        "evidence": evidence,
        "suspectedLocation": _find_location(" ".join(evidence)),
        "needRetrieval": need_retrieval,
        "retrievalQuery": retrieval_query,
        "repairSuggestion": repair_suggestion,
        "confidence": confidence,
        "json_valid": True,
    }


def _unknown(root_cause: str) -> dict:
    return {
        "failedStage": "UNKNOWN",
        "errorType": "UNKNOWN",
        "errorSubtype": "UNKNOWN",
        "rootCause": root_cause,
        "evidence": [],
        "suspectedLocation": "",
        "needRetrieval": False,
        "retrievalQuery": "",
        "repairSuggestion": "",
        "confidence": 0.0,
        "json_valid": False,
    }


def _combined_error_log(execution: dict) -> str:
    return "\n".join(
        str(execution.get(key) or "")
        for key in ("errorLog", "stderr", "stdout", "status", "failedStage")
    )


def _evidence(text: str, needles: list[str]) -> list[str]:
    evidence = []
    for needle in needles:
        if needle.lower() in text.lower():
            evidence.append(needle)
    location = _find_location(text)
    if location:
        evidence.append(location)
    return evidence


def _find_location(text: str) -> str:
    match = re.search(r'(?:File "([^"]+)", line (\d+)|\b(Main\.py):(\d+))', text)
    if not match:
        return ""
    filename = match.group(1) or match.group(3)
    line = match.group(2) or match.group(4)
    return f"{filename}:{line}"


def _clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except Exception:
        return 0.0
    return min(1.0, max(0.0, number))
