import re

from app.schemas import RuleDecision


SIGNAL_RULES: list[tuple[str, str, str]] = [
    ("SyntaxError", "SYNTAX_ERROR", "检测到 Python SyntaxError，倾向 COMPILE_ERROR / SYNTAX_ERROR。"),
    ("IndentationError", "INDENTATION_ERROR", "检测到 Python IndentationError，倾向 COMPILE_ERROR / INDENTATION_ERROR。"),
    ("ZeroDivisionError", "DIVIDE_BY_ZERO", "检测到 Python ZeroDivisionError，倾向 RUNTIME_ERROR / DIVIDE_BY_ZERO。"),
    ("IndexError", "INDEX_OUT_OF_BOUNDS", "检测到 Python IndexError，倾向 RUNTIME_ERROR / INDEX_OUT_OF_BOUNDS。"),
    ("KeyError", "KEY_ERROR", "检测到 Python KeyError，可能是字典键缺失。"),
    ("TypeError", "TYPE_MISMATCH", "检测到 Python TypeError，可能是类型或调用参数不匹配。"),
    ("NameError", "MISSING_SYMBOL", "检测到 Python NameError，可能是变量或函数未定义。"),
    ("ModuleNotFoundError", "DEPENDENCY_MISSING", "检测到 Python ModuleNotFoundError，可能缺少依赖或模块名错误。"),
    ("ImportError", "DEPENDENCY_MISSING", "检测到 Python ImportError，可能存在依赖或导入路径问题。"),
    ("MemoryError", "RESOURCE_LIMIT", "检测到 Python MemoryError，可能触发内存限制。"),
    ("RecursionError", "RESOURCE_LIMIT", "检测到 Python RecursionError，可能递归过深。"),
    ("AssertionError", "ALGORITHM_ERROR", "检测到 Python AssertionError；在 HumanEval/单元测试语义下通常表示测试断言失败，倾向 WRONG_ANSWER / TEST。"),
    ("Traceback", "TRACEBACK", "检测到 Python Traceback。"),
    ("';' expected", "SYNTAX_ERROR", "Java 编译日志提示缺少分号。"),
    ("cannot find symbol", "MISSING_SYMBOL", "Java 编译日志包含 cannot find symbol，可能是变量、方法或类名未定义。"),
    ("incompatible types", "TYPE_MISMATCH", "Java 编译日志包含 incompatible types，倾向类型不匹配。"),
    ("NullPointerException", "NULL_POINTER", "Java 运行日志包含 NullPointerException，可能访问了 null 对象。"),
    ("ArrayIndexOutOfBoundsException", "INDEX_OUT_OF_BOUNDS", "Java 运行日志包含 ArrayIndexOutOfBoundsException，可能数组下标越界。"),
    ("ArithmeticException", "DIVIDE_BY_ZERO", "Java 运行日志包含 ArithmeticException，常见原因是除零。"),
    ("ClassNotFoundException", "DEPENDENCY_MISSING", "Java 日志包含 ClassNotFoundException，可能缺少类或运行时依赖。"),
    ("NoClassDefFoundError", "DEPENDENCY_MISSING", "Java 日志包含 NoClassDefFoundError，可能缺少类或运行时依赖。"),
    ("TIME_LIMIT_EXCEEDED", "TIME_LIMIT", "检测到 TIME_LIMIT_EXCEEDED，优先考虑死循环、阻塞输入或复杂度过高。"),
    ("timeout=true", "TIME_LIMIT", "检测到 timeout=true，优先考虑死循环、阻塞输入或复杂度过高。"),
    ("Docker 不可用", "ENVIRONMENT_ERROR", "检测到 Docker 不可用，倾向 ENVIRONMENT_ERROR。"),
    ("ENVIRONMENT_ERROR", "ENVIRONMENT_ERROR", "检测到 ENVIRONMENT_ERROR，优先检查运行环境配置。"),
    ("actualOutput", "WRONG_ANSWER", "日志包含 actualOutput，可能存在输出不匹配。"),
    ("expectedOutput", "WRONG_ANSWER", "日志包含 expectedOutput，可能存在输出不匹配。"),
]

JAVA_LOCATION = re.compile(r"(\b\w+\.java):(\d+):")
PYTHON_LOCATION = re.compile(r'File "([^"]+)", line (\d+)')
SIMPLE_LOCATION = re.compile(r"\b(Main\.(?:py|java)):(\d+)")
MODULE_NAME = re.compile(r"No module named ['\"]([^'\"]+)['\"]")


def extract_signals(error_log: str) -> list[str]:
    log = error_log or ""
    signals: list[str] = []
    lowered = log.lower()

    for needle, signal, _ in SIGNAL_RULES:
        if needle.lower() in lowered:
            signals.append(signal)
            if needle not in signals:
                signals.append(needle)

    location = _find_location(log)
    if location:
        signals.append(location)

    return _dedupe(signals)


def summarize_error_signal(error_log: str) -> str:
    log = error_log or ""
    if not log.strip():
        return "【规则信号摘要】\n- 未从执行反馈中提取到明显错误信号。"

    hints: list[str] = []
    lowered = log.lower()
    for needle, _, hint in SIGNAL_RULES:
        if needle.lower() in lowered:
            hints.append(hint)

    location = _find_location(log)
    if location:
        hints.append(f"日志包含 {location}，疑似出错位置 {location}。")

    if not hints:
        hints.append("未命中内置规则，请主要依据原始 stdout、stderr、exitCode、failedStage 判断。")

    return "【规则信号摘要】\n" + "\n".join(f"- {hint}" for hint in _dedupe(hints))


def make_rule_decision(execution: dict | None = None, error_log: str = "", stderr: str = "") -> RuleDecision:
    execution = execution or {}
    combined = "\n".join(
        [
            str(execution.get("status") or ""),
            str(execution.get("failedStage") or ""),
            str(execution.get("errorLog") or ""),
            str(execution.get("stderr") or ""),
            str(execution.get("stdout") or ""),
            error_log or "",
            stderr or "",
        ]
    )
    lowered = combined.lower()
    evidence = extract_signals(combined)

    if _contains(lowered, ["docker 不可用", "environment_error", "docker: command not found", "cannot connect to docker daemon"]):
        return _decision("PRE_CHECK", "ENVIRONMENT_ERROR", "SANDBOX_INTERNAL_ERROR", False, evidence, 0.95, "规则层检测到运行环境或 Docker 不可用。")

    if "sandbox_error" in lowered:
        return _decision("SANDBOX", "SANDBOX_ERROR", "SANDBOX_INTERNAL_ERROR", False, evidence, 0.9, "规则层检测到沙箱内部错误。")

    if execution.get("timeout") is True or _contains(lowered, ["time_limit_exceeded", "timeout=true", "timeout: true", "timeout】\ntrue", "timed out", "timeoutexpired", "运行超时"]):
        return _decision("RUNTIME", "TIME_LIMIT_EXCEEDED", "INFINITE_LOOP", False, evidence or ["TIME_LIMIT_EXCEEDED"], 0.95, "规则层检测到超时，通常是无限循环、阻塞输入或复杂度过高。")

    if "indentationerror" in lowered:
        return _decision("COMPILE", "COMPILE_ERROR", "INDENTATION_ERROR", False, evidence or ["IndentationError"], 0.95, "规则层检测到 Python 缩进错误。")

    if "syntaxerror" in lowered:
        return _decision("COMPILE", "COMPILE_ERROR", "SYNTAX_ERROR", False, evidence or ["SyntaxError"], 0.95, "规则层检测到 Python 语法错误。")

    if _contains(lowered, ["cannot find symbol"]):
        return _decision("COMPILE", "COMPILE_ERROR", "MISSING_SYMBOL", False, evidence or ["cannot find symbol"], 0.9, "规则层检测到 Java 符号缺失编译错误。")

    if _contains(lowered, ["incompatible types"]):
        return _decision("COMPILE", "COMPILE_ERROR", "TYPE_MISMATCH", False, evidence or ["incompatible types"], 0.9, "规则层检测到 Java 类型不匹配编译错误。")

    if _contains(lowered, ["';' expected", "error:"]):
        failed_stage = str(execution.get("failedStage") or "").upper()
        if failed_stage == "COMPILE" or "javac" in lowered or ".java" in lowered:
            return _decision("COMPILE", "COMPILE_ERROR", "SYNTAX_ERROR", False, evidence, 0.75, "规则层检测到 Java 编译错误。")

    if "assertionerror" in lowered:
        return _decision("TEST", "WRONG_ANSWER", "ALGORITHM_ERROR", False, evidence or ["AssertionError"], 0.95, "规则层检测到 HumanEval/单元测试断言失败，属于测试阶段答案错误。")

    if "modulenotfounderror" in lowered or "importerror" in lowered or "no module named" in lowered or "cannot import name" in lowered:
        query = _dependency_query(combined)
        return _decision("RUNTIME", "API_MISUSE", "DEPENDENCY_MISSING", True, evidence or ["ModuleNotFoundError"], 0.9, "规则层检测到依赖缺失或导入失败。", query)

    if "zerodivisionerror" in lowered:
        return _decision("RUNTIME", "RUNTIME_ERROR", "DIVIDE_BY_ZERO", False, evidence or ["ZeroDivisionError"], 0.95, "规则层检测到 Python 除零异常。")

    if "indexerror" in lowered or "arrayindexoutofboundsexception" in lowered:
        return _decision("RUNTIME", "RUNTIME_ERROR", "INDEX_OUT_OF_BOUNDS", False, evidence, 0.85, "规则层检测到下标越界异常。")

    if "typeerror" in lowered or "incompatible types" in lowered:
        return _decision("RUNTIME", "RUNTIME_ERROR", "TYPE_MISMATCH", False, evidence, 0.8, "规则层检测到运行时类型错误。")

    if _contains(lowered, ["keyerror", "nameerror", "recursionerror", "memoryerror", "nullpointerexception", "arithmeticexception"]):
        subtype = "UNKNOWN"
        if "recursionerror" in lowered or "memoryerror" in lowered:
            subtype = "RESOURCE_LIMIT"
        if "nullpointerexception" in lowered:
            subtype = "NULL_POINTER"
        if "arithmeticexception" in lowered:
            subtype = "DIVIDE_BY_ZERO"
        if "nameerror" in lowered:
            subtype = "MISSING_SYMBOL"
        return _decision("RUNTIME", "RUNTIME_ERROR", subtype, False, evidence, 0.75, "规则层检测到运行时异常。")

    status = str(execution.get("status") or "").upper()
    if status == "WRONG_ANSWER" or "expectedoutput" in lowered or "actualoutput" in lowered:
        return _decision("TEST", "WRONG_ANSWER", "ALGORITHM_ERROR", False, evidence, 0.8, "规则层检测到实际输出与期望输出不一致。")

    return _decision("UNKNOWN", "UNKNOWN", "UNKNOWN", False, evidence, 0.0, "规则层未检测到明确错误类型。")


def _find_location(log: str) -> str:
    for pattern in (JAVA_LOCATION, PYTHON_LOCATION, SIMPLE_LOCATION):
        match = pattern.search(log)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
    return ""


def _contains(text: str, needles: list[str]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _decision(
    failed_stage: str,
    error_type: str,
    error_subtype: str,
    need_retrieval: bool,
    evidence: list[str],
    confidence: float,
    explanation: str,
    retrieval_query: str = "",
) -> RuleDecision:
    return RuleDecision(
        failedStage=failed_stage,
        errorType=error_type,
        errorSubtype=error_subtype,
        needRetrieval=need_retrieval,
        retrievalQuery=retrieval_query,
        evidence=_dedupe(evidence),
        confidence=confidence,
        decisionSource="RULE",
        explanation=explanation,
    )


def _dependency_query(text: str) -> str:
    match = MODULE_NAME.search(text)
    if match:
        return f"Python ModuleNotFoundError No module named {match.group(1)} dependency installation or import usage"
    return "Python ImportError ModuleNotFoundError dependency installation or import usage"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
