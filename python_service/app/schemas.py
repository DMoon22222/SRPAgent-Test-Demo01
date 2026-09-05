from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    testCases: list[TestCase]


class AgentObservation(BaseModel):
    observationId: str = ""
    command: str = ""
    language: str = ""
    stage: str = ""
    status: str = ""
    shortSummary: str = ""
    importantSignals: list[str] = Field(default_factory=list)
    stdoutTruncated: bool = False
    stderrTruncated: bool = False
    nextActionHint: str = ""


class RuleDecision(BaseModel):
    failedStage: str = "UNKNOWN"
    errorType: str = "UNKNOWN"
    errorSubtype: str = "UNKNOWN"
    needRetrieval: bool = False
    retrievalQuery: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    decisionSource: str = "RULE"
    explanation: str = ""


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
    observation: AgentObservation | None = None


class ErrorAnalysisResult(BaseModel):
    failedStage: str
    errorType: str
    errorSubtype: str
    rootCause: str
    evidence: list[str]
    suspectedLocation: str
    needRetrieval: bool
    retrievalQuery: str
    repairSuggestion: str
    confidence: float = Field(ge=0.0, le=1.0)
    ruleDecision: RuleDecision | None = None
    classificationSource: str = "RULE_FIRST_LLM_EXPLAIN"
    enumNormalized: bool = False
    llmOverrodeRule: bool = False
    analysisDepth: str = "ROOT_CAUSE"
    canExplainLogicBug: bool = True


class ExecuteAndAnalyzeResult(BaseModel):
    execution: Execution
    analysis: ErrorAnalysisResult | None = None


class RepositoryExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspacePath: str = Field(min_length=1)
    runner: Literal["pytest"] = "pytest"
    testTargets: list[str] = Field(default_factory=list)
    timeoutSeconds: int = Field(default=60, ge=1, le=600)
    benchmark: str = ""

    @field_validator("workspacePath")
    @classmethod
    def workspace_path_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspacePath must not be blank")
        return value

    @field_validator("testTargets")
    @classmethod
    def test_targets_must_be_safe(cls, values: list[str]) -> list[str]:
        from app.repository.target_validation import validate_target_selector

        return [validate_target_selector(value) for value in values]


class RepositoryTestFailure(BaseModel):
    testId: str
    message: str = ""
    location: str = ""
    excerpt: str = ""


class RepositoryTestSummary(BaseModel):
    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class RepositoryObservation(BaseModel):
    observationId: str = ""
    runner: str = ""
    status: str = ""
    shortSummary: str = ""
    importantSignals: list[str] = Field(default_factory=list)
    failingTests: list[str] = Field(default_factory=list)
    stdoutTruncated: bool = False
    stderrTruncated: bool = False
    nextActionHint: str = ""


class RepositoryExecution(BaseModel):
    success: bool
    status: str
    failedStage: str
    runner: str
    timeout: bool
    exitCode: int
    executionTimeMs: int
    summary: RepositoryTestSummary
    failures: list[RepositoryTestFailure] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    observation: RepositoryObservation | None = None


class RepositoryExecuteAndAnalyzeResult(BaseModel):
    execution: RepositoryExecution
    analysis: ErrorAnalysisResult | None = None


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
    caseResults: list[BatchCaseResult]
    analysis: ErrorAnalysisResult | None = None
