package com.scut.agenttestdemo01.controller;

import com.scut.agenttestdemo01.dto.AnalyzeRequest;
import com.scut.agenttestdemo01.dto.ErrorAnalysisResult;
import com.scut.agenttestdemo01.service.ErrorAnalyzerService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class ErrorAnalysisController {
    private final ErrorAnalyzerService errorAnalyzerService;

    public ErrorAnalysisController(ErrorAnalyzerService errorAnalyzerService) {
        this.errorAnalyzerService = errorAnalyzerService;
    }

    @PostMapping({"/analyze-error", "/analyze_error"})
    public ErrorAnalysisResult analyzeError(@RequestBody AnalyzeRequest request) {
        return errorAnalyzerService.analyze(request);
    }

    @GetMapping("/ping")
    public String ping() {
        return "srp-ai-demo is running";
    }
}
