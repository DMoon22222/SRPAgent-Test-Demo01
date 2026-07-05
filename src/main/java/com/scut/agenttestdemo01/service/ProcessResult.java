package com.scut.agenttestdemo01.service;

record ProcessResult(
        int exitCode,
        String stdout,
        String stderr,
        boolean timeout,
        long durationMs
) {
}
