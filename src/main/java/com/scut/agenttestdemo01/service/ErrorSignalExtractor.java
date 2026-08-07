package com.scut.agenttestdemo01.service;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class ErrorSignalExtractor {

    private static final Pattern JAVA_LOCATION = Pattern.compile("(\\b\\w+\\.java):(\\d+):");
    private static final Pattern PYTHON_LOCATION = Pattern.compile("File \\\"([^\\\"]+)\\\", line (\\d+)");

    private ErrorSignalExtractor() {
    }

    static String summarize(String errorLog) {
        String log = errorLog == null ? "" : errorLog;
        if (log.isBlank()) {
            return "未从执行反馈中提取到明显错误信号。";
        }

        List<String> hints = new ArrayList<>();
        addIfPresent(hints, log, "status=TIME_LIMIT_EXCEEDED", "检测到超时状态，优先考虑死循环、阻塞输入或复杂度过高。", true);
        addIfPresent(hints, log, "timeout=true", "检测到 timeout=true，优先考虑死循环、阻塞输入或复杂度过高。", true);
        addIfPresent(hints, log, "cannot find symbol", "Java 编译日志包含 cannot find symbol，可能是变量、方法、类名未定义或拼写错误。", false);
        addIfPresent(hints, log, "';' expected", "Java 编译日志提示缺少分号。", false);
        addIfPresent(hints, log, "')' expected", "Java 编译日志提示缺少右括号。", false);
        addIfPresent(hints, log, "SyntaxError", "Python 日志包含 SyntaxError，属于语法错误。", false);
        addIfPresent(hints, log, "IndentationError", "Python 日志包含 IndentationError，属于缩进错误。", false);
        addIfPresent(hints, log, "NullPointerException", "Java 运行日志包含 NullPointerException，可能访问了 null 对象。", false);
        addIfPresent(hints, log, "IndexOutOfBoundsException", "Java 运行日志包含 IndexOutOfBoundsException，可能存在下标越界。", false);
        addIfPresent(hints, log, "ArrayIndexOutOfBoundsException", "Java 运行日志包含 ArrayIndexOutOfBoundsException，可能存在数组下标越界。", false);
        addIfPresent(hints, log, "ArithmeticException: / by zero", "Java 运行日志包含除零异常。", false);
        addIfPresent(hints, log, "ZeroDivisionError", "Python 运行日志包含 ZeroDivisionError，属于除零异常。", false);
        addIfPresent(hints, log, "ModuleNotFoundError", "Python 日志包含 ModuleNotFoundError，可能缺少依赖或模块名错误。", false);
        addIfPresent(hints, log, "NoClassDefFoundError", "Java 日志包含 NoClassDefFoundError，可能缺少类或运行时依赖。", false);
        addIfPresent(hints, log, "ClassNotFoundException", "Java 日志包含 ClassNotFoundException，可能缺少类或运行时依赖。", false);
        addIfPresent(hints, log, "输出结果与期望不一致", "程序正常结束但输出不匹配，优先考虑逻辑错误、格式错误或边界条件错误。", false);

        String location = findLocation(log);
        if (!location.isBlank()) {
            hints.add("疑似位置：" + location + "。");
        }

        if (hints.isEmpty()) {
            return "未命中内置规则，请主要依据原始 stdout/stderr、exitCode、failedStage 判断。";
        }

        return String.join("\n", hints);
    }

    private static void addIfPresent(List<String> hints, String log, String needle, String hint, boolean ignoreCase) {
        boolean matched = ignoreCase
                ? log.toLowerCase().contains(needle.toLowerCase())
                : log.contains(needle);
        if (matched) {
            hints.add(hint);
        }
    }

    private static String findLocation(String log) {
        Matcher javaMatcher = JAVA_LOCATION.matcher(log);
        if (javaMatcher.find()) {
            return javaMatcher.group(1) + ":" + javaMatcher.group(2);
        }

        Matcher pythonMatcher = PYTHON_LOCATION.matcher(log);
        if (pythonMatcher.find()) {
            return pythonMatcher.group(1) + ":" + pythonMatcher.group(2);
        }

        return "";
    }
}
