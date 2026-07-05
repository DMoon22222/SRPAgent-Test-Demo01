package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.AnalyzeRequest;
import com.scut.agenttestdemo01.dto.ErrorAnalysisResult;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ErrorAnalyzerService {

    private final ChatClient chatClient;

    public ErrorAnalyzerService(ChatClient.Builder chatClientBuilder) {
        this.chatClient = chatClientBuilder.build();
    }

    public ErrorAnalysisResult analyze(AnalyzeRequest request) {
        String ruleHints = ErrorSignalExtractor.summarize(request.errorLog());
        String systemPrompt = """
                你是一个代码错误根因分析 Agent，负责根据题目、错误代码和标准化执行反馈日志进行结构化错误分析。
                你只负责 B 组模块：执行反馈理解、错误分类、根因分析和检索必要性判断，不负责生成新代码或执行修复闭环。

                分析流程：
                1. 先判断失败阶段 failedStage：PRE_CHECK、COMPILE、RUNTIME、TEST、SANDBOX、UNKNOWN。
                2. 再判断一级错误类型 errorType。
                3. 再判断二级错误类型 errorSubtype，用于描述更具体的错误形态。
                4. 从日志或代码中摘取 evidence，必须是能支持判断的具体证据。
                5. 如果日志包含文件名和行号，提取 suspectedLocation；无法判断时输出空字符串。
                6. 说明 rootCause，并给出简洁、可执行的 repairSuggestion。
                7. 判断 needRetrieval：只有当错误涉及外部库、框架 API、依赖、版本差异或知识缺口时才为 true。

                errorType 只能从下面的值中选择：
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

                errorSubtype 优先从下面的值中选择；确实无法归类时输出 UNKNOWN：
                SYNTAX_ERROR
                MISSING_SYMBOL
                TYPE_MISMATCH
                INDENTATION_ERROR
                NULL_POINTER
                INDEX_OUT_OF_BOUNDS
                DIVIDE_BY_ZERO
                DEPENDENCY_MISSING
                API_SIGNATURE_MISMATCH
                OUTPUT_FORMAT_ERROR
                ALGORITHM_ERROR
                INFINITE_LOOP
                RESOURCE_LIMIT
                SANDBOX_INTERNAL_ERROR
                UNKNOWN

                分类参考：
                - Java javac 报错、Python SyntaxError、IndentationError：通常是 COMPILE_ERROR。
                - Java Exception、Python Traceback 且进程非 0 退出：通常是 RUNTIME_ERROR。
                - 程序正常结束，但 actualOutput 和 expectedOutput 不一致：通常是 WRONG_ANSWER 或 LOGIC_ERROR。
                - 日志中 timeout=true 或 status=TIME_LIMIT_EXCEEDED：通常是 TIME_LIMIT_EXCEEDED。
                - 缺少 Python/Java/Docker 环境、解释器不存在：通常是 ENVIRONMENT_ERROR。
                - 执行器本身异常：通常是 SANDBOX_ERROR。
                - 第三方库、API 参数、版本差异导致的问题：通常可能是 API_MISUSE 或 KNOWLEDGE_GAP。

                needRetrieval 判断规则：
                - 语法错误、明显空指针、数组越界、除零、缩进错误、简单输出格式错误，通常为 false。
                - 不熟悉的库、框架 API、版本差异、依赖缺失、函数用法不确定，通常为 true。
                - 如果仅凭当前代码和日志就能判断根因，通常为 false。

                输出字段必须完整，字段名必须与下面一致：
                {
                  "failedStage": "COMPILE",
                  "errorType": "COMPILE_ERROR",
                  "errorSubtype": "MISSING_SYMBOL",
                  "rootCause": "简体中文根因说明",
                  "evidence": ["来自日志或代码的具体证据"],
                  "suspectedLocation": "Main.java:12",
                  "needRetrieval": false,
                  "retrievalQuery": "",
                  "repairSuggestion": "简体中文修复建议",
                  "confidence": 0.85
                }

                输出要求：
                - 必须输出结构化结果，不要输出 Markdown，不要输出额外解释。
                - errorType 和 errorSubtype 保持英文枚举值。
                - rootCause、evidence、repairSuggestion 必须使用简体中文。
                - evidence 至少 1 条；如果日志为空，说明“未提供可用执行日志”。
                - retrievalQuery 如果不需要检索必须为空字符串。
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

                【内置规则提取的执行信号】
                ```text
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
                ruleHints,
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
                    "UNKNOWN",
                    "UNKNOWN",
                    "模型调用或结构化解析失败：" + e.getMessage(),
                    List.of("模型调用异常，未能获得可用分析结果。"),
                    "",
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
