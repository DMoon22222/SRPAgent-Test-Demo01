package com.scut.agenttestdemo01.dto;

/**
 * 执行并分析代码的请求。
 *
 * @param problem        题目描述
 * @param language       编程语言，支持 java / python / python3 / py
 * @param code           待执行代码。Java 建议类名使用 Main；Python 没有类名要求
 * @param stdin          标准输入，可为空
 * @param expectedOutput 期望输出，可为空
 */
public record ExecuteAndAnalyzeRequest(
        String problem,
        String language,
        String code,
        String stdin,
        String expectedOutput
) {
}

