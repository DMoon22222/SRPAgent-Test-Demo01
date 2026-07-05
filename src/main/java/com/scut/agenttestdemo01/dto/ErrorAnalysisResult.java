package com.scut.agenttestdemo01.dto;

public record ErrorAnalysisResult(
        String errorType, //错误类型
        String rootCause, //根本原因分析
        boolean needRetrieval, //是否需要RAG检索
        String retrievalQuery, //如果需要检索，生成什么query
        String repairSuggestion, //修复建议
        double confidence //模型对分析结果的置信度，0到1
) {
}
