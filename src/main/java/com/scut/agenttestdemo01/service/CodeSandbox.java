package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;

public interface CodeSandbox {
    ExecuteAndAnalyzeResult.Execution run(ExecuteAndAnalyzeRequest request);
}
