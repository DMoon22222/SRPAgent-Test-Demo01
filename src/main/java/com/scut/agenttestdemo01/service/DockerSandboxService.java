package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static com.scut.agenttestdemo01.service.SandboxExecutionSupport.*;

@Service
public class DockerSandboxService implements CodeSandbox {

    private final SandboxProperties properties;

    public DockerSandboxService(SandboxProperties properties) {
        this.properties = properties;
    }

    @Override
    public ExecuteAndAnalyzeResult.Execution run(ExecuteAndAnalyzeRequest request) {
        String language = normalizeLanguage(request.language());

        if (language == null) {
            return execution(false, "UNSUPPORTED_LANGUAGE", "PRE_CHECK", false, false, -1,
                    "", "",
                    "当前 Docker 沙箱只支持 Java 和 Python。收到的 language=" + safe(request.language()),
                    0, request.expectedOutput(), "");
        }

        if (safe(request.code()).isBlank()) {
            return execution(false, "EMPTY_CODE", "PRE_CHECK", false, false, -1,
                    "", "", "代码为空，无法执行。", 0, request.expectedOutput(), "");
        }

        if (!isDockerAvailable()) {
            return execution(false, "ENVIRONMENT_ERROR", "PRE_CHECK", false, false, -1,
                    "", "",
                    "Docker 不可用。请确认 Docker Desktop 已启动，并且命令行可以执行 docker --version。",
                    0, request.expectedOutput(), "");
        }

        if ("java".equals(language)) {
            return runJavaInDocker(request);
        }

        return runPythonInDocker(request);
    }

    private ExecuteAndAnalyzeResult.Execution runJavaInDocker(ExecuteAndAnalyzeRequest request) {
        Path tempDir = null;

        try {
            tempDir = Files.createTempDirectory("srp-docker-java-");
            Files.writeString(tempDir.resolve("Main.java"), request.code(), StandardCharsets.UTF_8);

            ProcessResult compileResult = runDockerCommand(tempDir, "javac -encoding UTF-8 Main.java", "");

            if (compileResult.timeout()) {
                return execution(false, "TIME_LIMIT_EXCEEDED", "COMPILE", false, true, -1,
                        compileResult.stdout(), compileResult.stderr(),
                        "Docker Java 编译超时，超过限制 " + timeoutMillis() + "ms。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            if (compileResult.exitCode() != 0) {
                return execution(false, "COMPILE_ERROR", "COMPILE", false, false, compileResult.exitCode(),
                        compileResult.stdout(), compileResult.stderr(),
                        "Docker Java 编译失败。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            ProcessResult runResult = runDockerCommand(tempDir, "java -Dfile.encoding=UTF-8 Main", safe(request.stdin()));
            return buildRunResult("Docker Java", request, runResult, true, timeoutMillis());
        } catch (Exception e) {
            return sandboxException(e, request.expectedOutput());
        } finally {
            deleteDirectoryQuietly(tempDir);
        }
    }

    private ExecuteAndAnalyzeResult.Execution runPythonInDocker(ExecuteAndAnalyzeRequest request) {
        Path tempDir = null;

        try {
            tempDir = Files.createTempDirectory("srp-docker-python-");
            Files.writeString(tempDir.resolve("Main.py"), request.code(), StandardCharsets.UTF_8);

            ProcessResult compileResult = runDockerCommand(tempDir, "python3 -m py_compile Main.py", "");

            if (compileResult.timeout()) {
                return execution(false, "TIME_LIMIT_EXCEEDED", "COMPILE", false, true, -1,
                        compileResult.stdout(), compileResult.stderr(),
                        "Docker Python 语法检查超时，超过限制 " + timeoutMillis() + "ms。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            if (compileResult.exitCode() != 0) {
                return execution(false, "COMPILE_ERROR", "COMPILE", false, false, compileResult.exitCode(),
                        compileResult.stdout(), compileResult.stderr(),
                        "Docker Python 语法检查失败。\n" + formatLog(compileResult),
                        compileResult.durationMs(), request.expectedOutput(), compileResult.stdout());
            }

            ProcessResult runResult = runDockerCommand(tempDir, "python3 Main.py", safe(request.stdin()));
            return buildRunResult("Docker Python", request, runResult, true, timeoutMillis());
        } catch (Exception e) {
            return sandboxException(e, request.expectedOutput());
        } finally {
            deleteDirectoryQuietly(tempDir);
        }
    }

    private ProcessResult runDockerCommand(Path workDir, String innerCommand, String stdin)
            throws IOException, InterruptedException {
        List<String> command = new ArrayList<>();

        command.add("docker");
        command.add("run");
        command.add("--rm");
        command.add("-i");
        command.add("--network");
        command.add("none");
        command.add("--memory");
        command.add(dockerProperties().getMemory());
        command.add("--memory-swap");
        command.add(dockerProperties().getMemory());
        command.add("--cpus");
        command.add(dockerProperties().getCpus());
        command.add("--pids-limit");
        command.add(dockerProperties().getPidsLimit());
        command.add("--security-opt");
        command.add("no-new-privileges");
        command.add("--cap-drop");
        command.add("ALL");
        command.add("--read-only");
        command.add("--tmpfs");
        command.add("/tmp:rw,nosuid,nodev,size=64m");
        command.add("--mount");
        command.add("type=bind,source=" + workDir.toAbsolutePath() + ",target=/workspace");
        command.add("--workdir");
        command.add("/workspace");
        command.add(dockerProperties().getImage());
        command.add("bash");
        command.add("-lc");
        command.add(innerCommand);

        return runProcess(command, stdin);
    }

    private ProcessResult runProcess(List<String> command, String stdin)
            throws IOException, InterruptedException {
        long startTime = System.currentTimeMillis();

        ProcessBuilder processBuilder = new ProcessBuilder(command);
        processBuilder.redirectErrorStream(false);
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

        boolean finished = process.waitFor(timeoutMillis() + 2000, TimeUnit.MILLISECONDS);

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

    private boolean isDockerAvailable() {
        try {
            ProcessResult result = runProcess(List.of("docker", "--version"), "");
            return result.exitCode() == 0;
        } catch (Exception e) {
            return false;
        }
    }

    private long timeoutMillis() {
        return properties.getTimeoutMs();
    }

    private SandboxProperties.Docker dockerProperties() {
        return properties.getDocker();
    }

    private ExecuteAndAnalyzeResult.Execution sandboxException(Exception e, String expectedOutput) {
        return execution(false, "SANDBOX_ERROR", "SANDBOX", false, false, -1,
                "", "", "Docker 沙箱内部异常：" + e.getClass().getSimpleName() + ": " + e.getMessage(),
                0, expectedOutput, "");
    }
}