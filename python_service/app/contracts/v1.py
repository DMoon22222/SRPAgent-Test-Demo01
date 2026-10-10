from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Text = Annotated[str, Field(max_length=12000)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Operation = Literal["diagnose_error", "execute_and_diagnose", "check_syntax"]
Status = Literal["SUCCESS", "COMPILE_ERROR", "RUNTIME_ERROR", "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "ENVIRONMENT_ERROR", "SANDBOX_ERROR", "UNKNOWN"]
Stage = Literal["NONE", "PRE_CHECK", "COMPILE", "RUNTIME", "TEST", "SANDBOX", "UNKNOWN"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkflowContext(Contract):
    workflowId: Identifier
    requestId: Identifier
    iteration: int = Field(default=0, ge=0)
    producerAgentId: Identifier
    previousReportId: Identifier | None = None


class ProblemSpec(Contract):
    description: Text
    constraints: list[Text] = Field(default_factory=list, max_length=32)
    acceptanceCriteria: list[Text] = Field(default_factory=list, max_length=32)


class SourceFile(Contract):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=200000)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if "\\" in value or ":" in value or value.startswith("/"):
            raise ValueError("Use a relative POSIX path, not a host path or URL")
        if any(part in {"", ".", ".."} for part in value.split("/")) or any(ord(c) < 32 for c in value):
            raise ValueError("Unsafe source path")
        return value


class CodeArtifact(Contract):
    artifactId: Identifier
    revision: Identifier
    kind: Literal["snippet"] = "snippet"
    language: Literal["python", "java"]
    entryPoint: Literal["Main.py", "Main.java"]
    files: list[SourceFile] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def supported_layout(self):
        expected = "Main.py" if self.language == "python" else "Main.java"
        if self.entryPoint != expected or self.files[0].path != expected:
            raise ValueError(f"This version accepts one {expected} source file")
        return self

    def digest(self) -> str:
        return canonical_digest({
            "language": self.language, "entryPoint": self.entryPoint,
            "files": [f.model_dump() for f in sorted(self.files, key=lambda f: f.path)],
        })


class StdioCase(Contract):
    caseId: Identifier
    stdin: Text = ""
    expectedOutput: Text


class TestSuite(Contract):
    __test__ = False
    suiteId: Identifier
    revision: Identifier
    origin: Literal["GENERATED", "PROVIDED", "BENCHMARK"]
    kind: Literal["STDIO"] = "STDIO"
    cases: list[StdioCase] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({c.caseId for c in self.cases}) != len(self.cases):
            raise ValueError("caseId must be unique within a suite")
        return self

    def digest(self) -> str:
        return canonical_digest({"kind": self.kind, "cases": [c.model_dump() for c in self.cases]})


class TestSummary(Contract):
    __test__ = False
    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    timedOut: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if self.passed + self.failed != self.total or self.timedOut > self.failed:
            raise ValueError("Invalid test counts")
        return self


class CaseFeedback(Contract):
    caseId: Identifier
    status: Status
    failedStage: Stage
    exitCode: int
    stdout: Text = ""
    stderr: Text = ""
    errorLog: Text = ""
    stdoutTruncated: bool = False
    stderrTruncated: bool = False
    errorLogTruncated: bool = False
    expectedOutput: Text = ""
    executionTimeMs: int = Field(default=0, ge=0)


class ExecutionFeedback(Contract):
    runId: Identifier
    source: Literal["B_SANDBOX", "EXTERNAL"]
    codeArtifactId: Identifier
    codeRevision: Identifier
    codeDigest: Digest | None = None
    testSuiteId: Identifier | None = None
    testRevision: Identifier | None = None
    testDigest: Digest | None = None
    status: Status
    failedStage: Stage
    exitCode: int
    validationScope: Literal["STDIO", "SYNTAX_ONLY", "UNKNOWN"] = "UNKNOWN"
    summary: TestSummary = Field(default_factory=TestSummary)
    failures: list[CaseFeedback] = Field(default_factory=list, max_length=20)
    stdout: Text = ""
    stderr: Text = ""
    errorLog: Text = ""
    stdoutTruncated: bool = False
    stderrTruncated: bool = False
    errorLogTruncated: bool = False

    @model_validator(mode="after")
    def consistent_status(self):
        if (self.testSuiteId is None) != (self.testRevision is None):
            raise ValueError("testSuiteId and testRevision must be supplied together")
        if self.testDigest and not self.testSuiteId:
            raise ValueError("testDigest requires test suite references")
        if self.status == "SUCCESS":
            if self.exitCode != 0 or self.failedStage != "NONE" or self.failures or self.summary.failed:
                raise ValueError("SUCCESS contradicts failure feedback")
            if self.validationScope == "STDIO" and not self.summary.total:
                raise ValueError("Zero tests cannot establish STDIO success")
        return self


class DiagnosticRequest(Contract):
    schemaVersion: Literal["1.0"]
    operation: Operation
    workflow: WorkflowContext
    problem: ProblemSpec
    code: CodeArtifact
    tests: TestSuite | None = None
    feedback: ExecutionFeedback | None = None

    @model_validator(mode="after")
    def operation_inputs(self):
        if self.operation == "diagnose_error":
            if self.feedback is None or self.feedback.source != "EXTERNAL":
                raise ValueError("diagnose_error requires EXTERNAL feedback")
        elif self.feedback is not None:
            raise ValueError("Execution operations do not accept client execution feedback")
        if self.operation == "execute_and_diagnose" and self.tests is None:
            raise ValueError("execute_and_diagnose requires a nonempty STDIO suite")
        if self.operation == "check_syntax" and self.tests is not None:
            raise ValueError("check_syntax does not run a test suite")
        return self


class Evidence(Contract):
    source: Literal["EXECUTION", "RULE", "MODEL"]
    path: str | None = None
    lineStart: int | None = Field(default=None, ge=1)
    lineEnd: int | None = Field(default=None, ge=1)
    excerpt: Text


class RetrievalDecision(Contract):
    decision: Literal["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]
    reason: Text
    query: Text = ""
    knowledgeScope: Literal["DEPENDENCY", "LANGUAGE_API", "ALGORITHM", "UNKNOWN"] = "UNKNOWN"
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def query_matches_decision(self):
        if self.decision == "REQUIRED" and not self.query.strip():
            raise ValueError("REQUIRED needs a retrieval query")
        if self.decision != "REQUIRED" and self.query:
            raise ValueError("Only REQUIRED carries a retrieval query")
        return self


class DiagnosisReport(Contract):
    reportId: Identifier
    diagnosisStatus: Literal["COMPLETED", "INSUFFICIENT_CONTEXT", "NOT_APPLICABLE"]
    analysisMode: Literal["LLM_ASSISTED", "RULE_ONLY"]
    failedStage: str
    errorType: str
    errorSubtype: str
    rootCause: Text
    repairSuggestion: Text
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list, max_length=32)
    suspectedLocations: list[Evidence] = Field(default_factory=list, max_length=32)
    retrieval: RetrievalDecision


class DiagnosticResult(Contract):
    schemaVersion: Literal["1.0"] = "1.0"
    workflow: WorkflowContext
    codeArtifactId: Identifier
    codeRevision: Identifier
    codeDigest: Digest
    testSuiteId: Identifier | None = None
    testRevision: Identifier | None = None
    testDigest: Digest | None = None
    execution: ExecutionFeedback | None = None
    diagnosis: DiagnosisReport | None = None
    warnings: list[Text] = Field(default_factory=list, max_length=32)
    nextAction: Literal["REPAIR", "RETRIEVE_THEN_REPAIR", "PROVIDE_CONTEXT", "ACCEPT", "RUN_TESTS", "REVIEW_EXTERNAL_RESULT", "FIX_ENVIRONMENT"]


class ApiError(Contract):
    requestId: str | None = None
    code: str
    message: str
    retryable: bool = False
    details: list[dict] = Field(default_factory=list)


def canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
