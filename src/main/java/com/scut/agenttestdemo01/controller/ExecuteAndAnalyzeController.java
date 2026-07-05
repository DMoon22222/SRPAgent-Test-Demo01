package com.scut.agenttestdemo01.controller;

import com.scut.agenttestdemo01.dto.AnalyzeRequest;
import com.scut.agenttestdemo01.dto.ErrorAnalysisResult;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;
import com.scut.agenttestdemo01.service.ErrorAnalyzerService;
import com.scut.agenttestdemo01.service.SandboxRouterService;
import org.springframework.web.bind.annotation.*;

/**
 * 如果你原来的 Controller 已经能正常工作，不建议直接整文件替换。
 *
 * 你只需要把原来注入 JavaSandboxService 的地方，改成注入 SandboxRouterService；
 * 然后把 javaSandboxService.run(request) 改成 sandboxRouterService.run(request)。
 */
@RestController
@RequestMapping("/api")
public class ExecuteAndAnalyzeController {

    private final SandboxRouterService sandboxRouterService;
    private final ErrorAnalyzerService errorAnalyzerService;

    public ExecuteAndAnalyzeController(
            SandboxRouterService sandboxRouterService,
            ErrorAnalyzerService errorAnalyzerService
    ) {
        this.sandboxRouterService = sandboxRouterService;
        this.errorAnalyzerService = errorAnalyzerService;
    }

    @PostMapping("/execute-and-analyze")
    public ExecuteAndAnalyzeResult executeAndAnalyze(@RequestBody ExecuteAndAnalyzeRequest request) {
        ExecuteAndAnalyzeResult.Execution execution = sandboxRouterService.run(request);

        ErrorAnalysisResult analysis = null;

        if (!execution.success()) {
            AnalyzeRequest analyzeRequest = new AnalyzeRequest(
                    request.problem(),
                    request.language(),
                    request.code(),
                    execution.errorLog()
            );

            analysis = errorAnalyzerService.analyze(analyzeRequest);
        }

        return new ExecuteAndAnalyzeResult(execution, analysis);
    }
}
