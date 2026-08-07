import re


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


def _find_location(log: str) -> str:
    for pattern in (JAVA_LOCATION, PYTHON_LOCATION, SIMPLE_LOCATION):
        match = pattern.search(log)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
    return ""


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
