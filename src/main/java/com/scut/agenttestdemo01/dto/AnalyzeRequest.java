package com.scut.agenttestdemo01.dto;

/**
 * 请求DTO
 * @param problem
 * @param language
 * @param code
 * @param errorLog
 */
public record AnalyzeRequest(
        String problem, //编程题目或需求
        String language, //编程语言，比如Java
        String code, //当前错误代码
        String errorLog //编译、运行或测试错误信息
) {
}
