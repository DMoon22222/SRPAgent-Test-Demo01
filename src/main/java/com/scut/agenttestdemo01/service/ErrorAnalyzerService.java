package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.AnalyzeRequest;
import com.scut.agenttestdemo01.dto.ErrorAnalysisResult;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

@Service
public class ErrorAnalyzerService {

    private final ChatClient chatClient;

    public ErrorAnalyzerService(ChatClient.Builder chatClientBuilder) {
        this.chatClient = chatClientBuilder.build();
    }

    public ErrorAnalysisResult analyze(AnalyzeRequest request) {
        String systemPrompt = """
                你是一个代码错误根因分析 Agent，负责根据题目、错误代码和标准化执行反馈日志进行结构化错误分析。

                你需要同时支持 Java 和 Python 代码错误分析。

                你的任务：
                1. 先判断失败阶段：PRE_CHECK、COMPILE、RUNTIME、TEST、SANDBOX。
                2. 再判断错误类型。
                3. 根据代码和日志分析最可能的根本原因。
                4. 判断是否需要外部知识检索。
                5. 如果需要检索，生成一个简短、准确的检索 query。
                6. 给出简洁、可执行的修复建议。

                错误类型只能从下面的值中选择：
                COMPILE_ERROR
                RUNTIME_ERROR
                WRONG_ANSWER
                TIME_LIMIT_EXCEEDED
                LOGIC_ERROR
                API_MISUSE
                KNOWLEDGE_GAP
                ENVIRONMENT_ERROR
                SANDBOX_ERROR
                UNKNOWN

                分类参考：
                - Java javac 报错、Python SyntaxError、IndentationError：通常是 COMPILE_ERROR。
                - Java Exception、Python Traceback 且进程非 0 退出：通常是 RUNTIME_ERROR。
                - 程序正常结束，但 actualOutput 和 expectedOutput 不一致：通常是 WRONG_ANSWER 或 LOGIC_ERROR。
                - 日志中 timeout=true 或 status=TIME_LIMIT_EXCEEDED：通常是 TIME_LIMIT_EXCEEDED。
                - 缺少 Python/Java 环境、解释器不存在：通常是 ENVIRONMENT_ERROR。
                - 执行器本身异常：通常是 SANDBOX_ERROR。
                - 第三方库、API 参数、版本差异导致的问题：通常可能是 API_MISUSE 或 KNOWLEDGE_GAP。

                needRetrieval 判断规则：
                - 如果错误主要来自语法错误、明显空指针、数组越界、除零、缩进错误、简单输出错误，通常为 false。
                - 如果错误涉及不熟悉的库、框架 API、版本差异、依赖缺失、函数用法不确定，通常为 true。
                - 如果仅凭当前代码和日志就能判断根因，通常为 false。

                输出要求：
                - 必须输出结构化结果。
                - 不要输出 Markdown。
                - 不要输出额外解释。
                - errorType 保持英文枚举值。
                - rootCause 必须使用简体中文。
                - repairSuggestion 必须使用简体中文。
                - retrievalQuery 如果需要检索，优先使用中文；涉及英文 API 名称时可以保留英文术语。
                - confidence 是 0 到 1 之间的小数。
                """;

        String userPrompt = """
                请用简体中文分析下面的代码错误。

                【题目 / 需求】
                %s

                【编程语言】
                %s

                【错误代码】
                ```%s
                %s
                ```

                【标准化执行反馈 / 错误日志】
                ```text
                %s
                ```
                """.formatted(
                safe(request.problem()),
                safe(request.language()),
                safe(request.language()),
                safe(request.code()),
                safe(request.errorLog())
        );

        try {
            return chatClient.prompt()
                    .system(systemPrompt)
                    .user(userPrompt)
                    .call()
                    .entity(ErrorAnalysisResult.class);
        } catch (Exception e) {
            return new ErrorAnalysisResult(
                    "UNKNOWN",
                    "模型调用或结构化解析失败：" + e.getMessage(),
                    false,
                    "",
                    "请检查 API Key、模型配置、网络连接，或暂时改为普通文本输出进行调试。",
                    0.0
            );
        }
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }
}
