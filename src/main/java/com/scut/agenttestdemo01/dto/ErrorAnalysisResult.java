package com.scut.agenttestdemo01.dto;

import java.util.List;

public record ErrorAnalysisResult(
        String failedStage, //失败阶段：PRE_CHECK / COMPILE / RUNTIME / TEST / SANDBOX / UNKNOWN
        String errorType, //一级错误类型
        String errorSubtype, //二级错误类型，用于更细粒度定位
        String rootCause, //根本原因分析
        List<String> evidence, //来自执行日志或代码片段的分析证据
        String suspectedLocation, //疑似出错位置，例如 Main.java:12；无法判断时为空
        boolean needRetrieval, //是否需要RAG检索
        String retrievalQuery, //如果需要检索，生成什么query
        String repairSuggestion, //修复建议
        double confidence //模型对分析结果的置信度，0到1
) {
}
