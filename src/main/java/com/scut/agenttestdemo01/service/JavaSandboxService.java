package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static com.scut.agenttestdemo01.service.SandboxExecutionSupport.*;

@Service
public class JavaSandboxService implements CodeSandbox {

    private static final long TIMEOUT_MILLIS = 5000;

    @Override
    public ExecuteAndAnalyzeResult.Execution run(ExecuteAndAnalyzeRequest request) {
        String language = normalizeLanguage(request.language());

        if (language == null) {
            return execution(false, "UNSUPPORTED_LANGUAGE", "PRE_CHECK", false, false, -1,
                    "", "",
                    "当前本地沙箱只支持 Java 和 Python。收到的 language=" + safe(request.language()),
                    0, request.expectedOutput(), "");
        }

        if (safe(request.code()).isBlank()) {
            return execution(false, "EMPTY_CODE", "PRE_CHECK", false, false, -1,
                    "", "", "代码为空，无法执行。", 0, request.expectedOutput(), "");
        }

        if ("java".equals(language)) {
            return runJava(request);
        }

        return runPython(request);
    }

    private ExecuteAndAnalyzeResult.Execution runJava(ExecuteAndAnalyzeRequest request) {
        Path tempDir = null;

        try {
            tempDir = Files.createTempDirectory("srp-java-sandbox-");
            Path sourceFile = tempDir.resolve("Main.java");
            Files.writeString(sourceFile, request.code(), StandardCharsets.UTF_8);

            ProcessResult compileResult = runProcess(
                    List.of(
                            javaTool("javac"),
                            "-J-Dfile.encoding=UTF-8",
                            "-J-Dstdout.encoding=UTF-8",
                            "-J-Dstderr.encoding=UTF-8",
                            "-encoding",
                            "UTF-8",
                            sourceFile.toString()
                    ),
                    tempDir,
                    ""
            );

            if (compileResult.timeout()) {
                return execution(false, "TIME_LIMIT_EXCEEDED", "COMPILE", false, true, -1,
                        compileResult.stdout(), compileResult.stderr(),
                        "Java 编译超时，超过限制 " + TIMEOUT_MILLIS + "ms。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            if (compileResult.exitCode() != 0) {
                return execution(false, "COMPILE_ERROR", "COMPILE", false, false, compileResult.exitCode(),
                        compileResult.stdout(), compileResult.stderr(),
                        "Java 编译失败。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            ProcessResult runResult = runProcess(
                    List.of(
                            javaTool("java"),
                            "-Dfile.encoding=UTF-8",
                            "-Dstdout.encoding=UTF-8",
                            "-Dstderr.encoding=UTF-8",
                            "-cp",
                            tempDir.toString(),
                            "Main"
                    ),
                    tempDir,
                    safe(request.stdin())
            );

            return buildRunResult("Java", request, runResult, true, TIMEOUT_MILLIS);
        } catch (Exception e) {
            return sandboxError("Java", e, request.expectedOutput());
        } finally {
            deleteDirectoryQuietly(tempDir);
        }
    }

    private ExecuteAndAnalyzeResult.Execution runPython(ExecuteAndAnalyzeRequest request) {
        List<String> pythonCommandPrefix = findPythonCommandPrefix();

        if (pythonCommandPrefix == null) {
            return execution(false, "ENVIRONMENT_ERROR", "PRE_CHECK", false, false, -1,
                    "", "",
                    "当前环境未找到可用的 Python 解释器。请确认命令行可以执行 python --version 或 python3 --version。",
                    0, request.expectedOutput(), "");
        }

        Path tempDir = null;

        try {
            tempDir = Files.createTempDirectory("srp-python-sandbox-");
            Path sourceFile = tempDir.resolve("Main.py");
            Files.writeString(sourceFile, request.code(), StandardCharsets.UTF_8);

            List<String> compileCommand = new ArrayList<>(pythonCommandPrefix);
            compileCommand.add("-m");
            compileCommand.add("py_compile");
            compileCommand.add(sourceFile.toString());

            ProcessResult compileResult = runProcess(compileCommand, tempDir, "");

            if (compileResult.timeout()) {
                return execution(false, "TIME_LIMIT_EXCEEDED", "COMPILE", false, true, -1,
                        compileResult.stdout(), compileResult.stderr(),
                        "Python 语法检查超时，超过限制 " + TIMEOUT_MILLIS + "ms。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            if (compileResult.exitCode() != 0) {
                return execution(false, "COMPILE_ERROR", "COMPILE", false, false, compileResult.exitCode(),
                        compileResult.stdout(), compileResult.stderr(),
                        "Python 语法检查失败。可能是 SyntaxError 或 IndentationError。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            List<String> runCommand = new ArrayList<>(pythonCommandPrefix);
            runCommand.add(sourceFile.toString());

            ProcessResult runResult = runProcess(runCommand, tempDir, safe(request.stdin()));

            return buildRunResult("Python", request, runResult, true, TIMEOUT_MILLIS);
        } catch (Exception e) {
            return sandboxError("Python", e, request.expectedOutput());
        } finally {
            deleteDirectoryQuietly(tempDir);
        }
    }

    private ProcessResult runProcess(List<String> command, Path workDir, String stdin)
            throws IOException, InterruptedException {
        long startTime = System.currentTimeMillis();

        ProcessBuilder processBuilder = new ProcessBuilder(command);
        processBuilder.directory(workDir.toFile());
        removeInheritedJavaToolOptions(processBuilder);
        processBuilder.environment().put("PYTHONIOENCODING", "UTF-8");

        Process process = processBuilder.start();

        ExecutorService executor = Executors.newFixedThreadPool(2);
        Future<String> stdoutFuture = executor.submit(() -> readText(process.getInputStream()));
        Future<String> stderrFuture = executor.submit(() -> readText(process.getErrorStream()));

        try (OutputStream outputStream = process.getOutputStream()) {
            if (stdin != null && !stdin.isEmpty()) {
                outputStream.write(stdin.getBytes(StandardCharsets.UTF_8));
                outputStream.flush();
            }
        }

        boolean finished = process.waitFor(TIMEOUT_MILLIS, TimeUnit.MILLISECONDS);

        if (!finished) {
            process.destroyForcibly();
            process.waitFor(1, TimeUnit.SECONDS);
        }

        long durationMs = System.currentTimeMillis() - startTime;
        String stdout = getFutureResult(stdoutFuture);
        String stderr = getFutureResult(stderrFuture);

        executor.shutdownNow();

        int exitCode = finished ? process.exitValue() : -1;
        return new ProcessResult(exitCode, stdout, stderr, !finished, durationMs);
    }

    private List<String> findPythonCommandPrefix() {
        List<List<String>> candidates = List.of(
                List.of("python"),
                List.of("python3"),
                List.of("py", "-3")
        );

        for (List<String> candidate : candidates) {
            if (isCommandAvailable(candidate)) {
                return candidate;
            }
        }

        return null;
    }

    private boolean isCommandAvailable(List<String> commandPrefix) {
        List<String> command = new ArrayList<>(commandPrefix);
        command.add("--version");

        try {
            ProcessBuilder processBuilder = new ProcessBuilder(command);
            processBuilder.environment().put("PYTHONIOENCODING", "UTF-8");
            Process process = processBuilder.start();
            boolean finished = process.waitFor(1500, TimeUnit.MILLISECONDS);

            if (!finished) {
                process.destroyForcibly();
                return false;
            }

            return process.exitValue() == 0;
        } catch (Exception e) {
            return false;
        }
    }

    private void removeInheritedJavaToolOptions(ProcessBuilder processBuilder) {
        processBuilder.environment().remove("JAVA_TOOL_OPTIONS");
        processBuilder.environment().remove("_JAVA_OPTIONS");
        processBuilder.environment().remove("JDK_JAVA_OPTIONS");
    }

    private String javaTool(String name) {
        boolean isWindows = System.getProperty("os.name")
                .toLowerCase(Locale.ROOT)
                .contains("win");

        String executable = isWindows ? name + ".exe" : name;
        Path pathInJavaHome = Paths.get(System.getProperty("java.home"), "bin", executable);

        if (Files.exists(pathInJavaHome)) {
            return pathInJavaHome.toString();
        }

        return executable;
    }

    private ExecuteAndAnalyzeResult.Execution sandboxError(String languageName, Exception e, String expectedOutput) {
        return execution(false, "SANDBOX_ERROR", "SANDBOX", false, false, -1,
                "", "", languageName + " 沙箱内部异常：" + e.getClass().getSimpleName() + ": " + e.getMessage(),
                0, expectedOutput, "");
    }
}