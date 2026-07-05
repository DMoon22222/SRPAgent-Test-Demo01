package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SandboxExecutionSupportTest {

    @Test
    void normalizesSupportedLanguageAliases() {
        assertThat(SandboxExecutionSupport.normalizeLanguage("java")).isEqualTo("java");
        assertThat(SandboxExecutionSupport.normalizeLanguage("python3")).isEqualTo("python");
        assertThat(SandboxExecutionSupport.normalizeLanguage("py")).isEqualTo("python");
        assertThat(SandboxExecutionSupport.normalizeLanguage("cpp")).isNull();
    }

    @Test
    void treatsTrimmedExpectedOutputAsMatch() {
        ExecuteAndAnalyzeRequest request = new ExecuteAndAnalyzeRequest(
                "print hello",
                "python",
                "print('Hello')",
                "",
                "Hello"
        );
        ProcessResult result = new ProcessResult(0, "Hello\r\n", "", false, 10);

        ExecuteAndAnalyzeResult.Execution execution = SandboxExecutionSupport.buildRunResult(
                "Python", request, result, true, 5000
        );

        assertThat(execution.success()).isTrue();
        assertThat(execution.status()).isEqualTo("SUCCESS");
    }

    @Test
    void reportsWrongAnswerWhenExpectedOutputDiffers() {
        ExecuteAndAnalyzeRequest request = new ExecuteAndAnalyzeRequest(
                "print hello",
                "python",
                "print('Hi')",
                "",
                "Hello"
        );
        ProcessResult result = new ProcessResult(0, "Hi\n", "", false, 10);

        ExecuteAndAnalyzeResult.Execution execution = SandboxExecutionSupport.buildRunResult(
                "Python", request, result, true, 5000
        );

        assertThat(execution.success()).isFalse();
        assertThat(execution.status()).isEqualTo("WRONG_ANSWER");
        assertThat(execution.failedStage()).isEqualTo("TEST");
    }
}