package com.scut.agenttestdemo01.service;

import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeRequest;
import com.scut.agenttestdemo01.dto.ExecuteAndAnalyzeResult;
import org.springframework.stereotype.Service;

@Service
public class SandboxRouterService {

    private final CodeSandbox localSandboxService;
    private final CodeSandbox dockerSandboxService;
    private final SandboxProperties properties;

    public SandboxRouterService(
            JavaSandboxService localSandboxService,
            DockerSandboxService dockerSandboxService,
            SandboxProperties properties
    ) {
        this.localSandboxService = localSandboxService;
        this.dockerSandboxService = dockerSandboxService;
        this.properties = properties;
    }

    public ExecuteAndAnalyzeResult.Execution run(ExecuteAndAnalyzeRequest request) {
        if ("docker".equalsIgnoreCase(properties.getMode())) {
            return dockerSandboxService.run(request);
        }

        return localSandboxService.run(request);
    }
}