package com.scut.agenttestdemo01.dto;

/**
 * 执行 + 错误分析的返回结果。
 * 如果 execution.success = true，说明代码通过，analysis 为 null。
 * 如果 execution.success = false，说明代码失败，analysis 会包含错误分析 Agent 的结果。
 */
public record ExecuteAndAnalyzeResult(
        Execution execution,
        ErrorAnalysisResult analysis
) {
    /**
     * 标准化执行反馈。
     *
     * @param success 整体是否成功。只有语法/编译成功、运行成功、输出匹配时才为 true
     * @param status 最终执行状态：
     *               SUCCESS / COMPILE_ERROR / RUNTIME_ERROR / WRONG_ANSWER /
     *               TIME_LIMIT_EXCEEDED / UNSUPPORTED_LANGUAGE / EMPTY_CODE /
     *               ENVIRONMENT_ERROR / SANDBOX_ERROR
     * @param failedStage 失败阶段：NONE / PRE_CHECK / COMPILE / RUNTIME / TEST / SANDBOX
     * @param compileSuccess 对 Java 表示 javac 是否通过；对 Python 表示 py_compile 语法检查是否通过
     * @param timeout 是否超时
     * @param exitCode 进程退出码。超时或沙箱内部错误时通常为 -1
     * @param stdout 标准输出
     * @param stderr 标准错误输出
     * @param errorLog 汇总后的错误日志，主要提供给错误分析 Agent
     * @param executionTimeMs 编译/语法检查或运行阶段耗时，单位毫秒
     * @param expectedOutput 期望输出，可为空
     * @param actualOutput 实际输出，通常等于 stdout
     */
    public record Execution(
            boolean success,
            String status,
            String failedStage,
            boolean compileSuccess,
            boolean timeout,
            int exitCode,
            String stdout,
            String stderr,
            String errorLog,
            long executionTimeMs,
            String expectedOutput,
            String actualOutput
    ) {
    }
}
