from typing import List, Optional

from pydantic import BaseModel, Field


class ExecuteAndAnalyzeRequest(BaseModel):
    problem: str = ""
    language: str = "python"
    code: str
    stdin: str = ""
    expectedOutput: str = ""
    benchmark: str = ""


class TestCase(BaseModel):
    caseId: str = ""
    stdin: str = ""
    expectedOutput: str = ""


class BatchExecuteAndAnalyzeRequest(BaseModel):
    problem: str = ""
    language: str = "python"
    code: str
    testCases: List[TestCase]


class AgentObservation(BaseModel):
    observationId: str = ""
    command: str = ""
    language: str = ""
    stage: str = ""
    status: str = ""
    shortSummary: str = ""
    importantSignals: List[str] = Field(default_factory=list)
    stdoutTruncated: bool = False
    stderrTruncated: bool = False
    nextActionHint: str = ""


class Execution(BaseModel):
    success: bool
    status: str
    failedStage: str
    compileSuccess: bool
    timeout: bool
    exitCode: int
    stdout: str
    stderr: str
    errorLog: str
    executionTimeMs: int
    expectedOutput: str
    actualOutput: str
    observation: Optional[AgentObservation] = None


class ErrorAnalysisResult(BaseModel):
    failedStage: str
    errorType: str
    errorSubtype: str
    rootCause: str
    evidence: List[str]
    suspectedLocation: str
    needRetrieval: bool
    retrievalQuery: str
    repairSuggestion: str
    confidence: float = Field(ge=0.0, le=1.0)


class ExecuteAndAnalyzeResult(BaseModel):
    execution: Execution
    analysis: Optional[ErrorAnalysisResult] = None


class AnalyzeRequest(BaseModel):
    problem: str = ""
    language: str = ""
    code: str = ""
    errorLog: str = ""


class BatchSummary(BaseModel):
    total: int
    passed: int
    failed: int
    timedOut: int
    passRate: float


class BatchCaseResult(BaseModel):
    caseId: str
    execution: Execution


class BatchExecuteAndAnalyzeResult(BaseModel):
    summary: BatchSummary
    caseResults: List[BatchCaseResult]
    analysis: Optional[ErrorAnalysisResult] = None
