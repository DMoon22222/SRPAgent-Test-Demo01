package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Locale;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

final class SandboxExecutionSupport {

    private SandboxExecutionSupport() {
    }

    static ExecuteAndAnalyzeResult.Execution buildRunResult(
            String executorName,
            ExecuteAndAnalyzeRequest request,
            ProcessResult runResult,
            boolean compileSuccess,
            long timeoutMillis
    ) {
        if (runResult.timeout()) {
            return execution(false, "TIME_LIMIT_EXCEEDED", "RUNTIME", compileSuccess, true, -1,
                    runResult.stdout(), runResult.stderr(),
                    executorName + " 运行超时，超过限制 " + timeoutMillis + "ms。\n" + formatLog(runResult),
                    runResult.durationMs(), request.expectedOutput(), runResult.stdout());
        }

        if (runResult.exitCode() != 0) {
            return execution(false, "RUNTIME_ERROR", "RUNTIME", compileSuccess, false, runResult.exitCode(),
                    runResult.stdout(), runResult.stderr(),
                    executorName + " 运行失败，exitCode=" + runResult.exitCode() + "。\n" + formatLog(runResult),
                    runResult.durationMs(), request.expectedOutput(), runResult.stdout());
        }

        if (!expectedOutputMatched(runResult.stdout(), request.expectedOutput())) {
            String errorLog = executorName + " 输出结果与期望不一致。\n"
                    + "【期望输出】\n" + safe(request.expectedOutput()) + "\n"
                    + "【实际输出】\n" + safe(runResult.stdout()) + "\n"
                    + "【判断说明】\n程序可以正常通过语法/编译检查并运行，但 stdout 与 expectedOutput 标准化后不相等。";

            return execution(false, "WRONG_ANSWER", "TEST", compileSuccess, false, runResult.exitCode(),
                    runResult.stdout(), runResult.stderr(), errorLog,
                    runResult.durationMs(), request.expectedOutput(), runResult.stdout());
        }

        return execution(true, "SUCCESS", "NONE", compileSuccess, false, runResult.exitCode(),
                runResult.stdout(), runResult.stderr(), "",
                runResult.durationMs(), request.expectedOutput(), runResult.stdout());
    }

    static ExecuteAndAnalyzeResult.Execution execution(boolean success, String status, String failedStage,
                                                       boolean compileSuccess, boolean timeout, int exitCode,
                                                       String stdout, String stderr, String errorLog,
                                                       long executionTimeMs, String expectedOutput,
                                                       String actualOutput) {
        return new ExecuteAndAnalyzeResult.Execution(
                success, status, failedStage, compileSuccess, timeout, exitCode,
                safe(stdout), safe(stderr), safe(errorLog), executionTimeMs,
                safe(expectedOutput), safe(actualOutput)
        );
    }

    static String normalizeLanguage(String language) {
        String value = safe(language).trim().toLowerCase(Locale.ROOT);
        if (value.equals("java")) return "java";
        if (value.equals("python") || value.equals("python3") || value.equals("py")) return "python";
        return null;
    }

    static String formatLog(ProcessResult result) {
        return "【stdout】\n" + safe(result.stdout())
                + "\n【stderr】\n" + safe(result.stderr())
                + "\n【exitCode】\n" + result.exitCode()
                + "\n【timeout】\n" + result.timeout()
                + "\n【durationMs】\n" + result.durationMs();
    }

    static String readText(InputStream inputStream) throws IOException {
        return new String(inputStream.readAllBytes(), StandardCharsets.UTF_8);
    }

    static String getFutureResult(Future<String> future) {
        try {
            return future.get(1, TimeUnit.SECONDS);
        } catch (Exception e) {
            return "[读取进程输出失败：" + e.getMessage() + "]";
        }
    }

    static String safe(String text) {
        return text == null ? "" : text;
    }

    static void deleteDirectoryQuietly(Path dir) {
        if (dir == null || !Files.exists(dir)) return;
        try {
            Files.walk(dir).sorted(Comparator.reverseOrder()).forEach(path -> {
                try {
                    Files.deleteIfExists(path);
                } catch (IOException ignored) {
                }
            });
        } catch (IOException ignored) {
        }
    }

    private static boolean expectedOutputMatched(String stdout, String expectedOutput) {
        if (expectedOutput == null || expectedOutput.isBlank()) return true;
        return normalize(stdout).equals(normalize(expectedOutput));
    }

    private static String normalize(String text) {
        return safe(text).replace("\r\n", "\n").replace("\r", "\n").trim();
    }
}
