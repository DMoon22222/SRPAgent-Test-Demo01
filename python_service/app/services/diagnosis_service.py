from __future__ import annotations

from uuid import uuid4

from app.analyzer.error_analyzer import ErrorAnalyzer
from app.analyzer.error_signal_extractor import make_rule_decision
from app.config import settings
from app.contracts.v1 import (
    CaseFeedback, DiagnosticRequest, DiagnosticResult, DiagnosisReport,
    Evidence, ExecutionFeedback, RetrievalDecision, TestSummary,
)
from app.sandbox.docker_sandbox import DockerSandbox
from app.sandbox.local_sandbox import LocalSandbox
from app.sandbox.support import truncate_output
from app.schemas import AnalyzeRequest, ExecuteAndAnalyzeRequest


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, retryable: bool = False):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable


class ComparedRequest(ExecuteAndAnalyzeRequest):
    @property
    def compareOutput(self):
        return True


class DiagnosisService:
    def __init__(self, sandbox=None, analyzer=None, registry=None):
        self.sandbox = sandbox
        self.analyzer = analyzer or ErrorAnalyzer()
        self.registry = registry

    def validate(self, request: DiagnosticRequest):
        f = request.feedback
        if f:
            if (f.codeArtifactId, f.codeRevision) != (request.code.artifactId, request.code.revision):
                raise ServiceError("CODE_VERSION_CONFLICT", "Feedback refers to a different code artifact or revision")
            if f.codeDigest and f.codeDigest != request.code.digest():
                raise ServiceError("CODE_DIGEST_CONFLICT", "Feedback code digest does not match received source")
            if request.tests:
                t = request.tests
                if (f.testSuiteId, f.testRevision) != (t.suiteId, t.revision):
                    raise ServiceError("TEST_VERSION_CONFLICT", "Feedback refers to a different test suite or revision")
                if f.testDigest and f.testDigest != t.digest():
                    raise ServiceError("TEST_DIGEST_CONFLICT", "Feedback test digest does not match received suite")

    def process(self, request: DiagnosticRequest, owner="local-development") -> DiagnosticResult:
        self.validate(request)
        if self.registry:
            self.registry.register_contract(request, owner)
        warnings = []
        if request.feedback:
            execution = request.feedback.model_copy(deep=True)
            warnings.append("External feedback has not been reproduced by B's sandbox.")
            if not execution.codeDigest:
                warnings.append("External feedback has no content digest; only artifact and revision references were checked.")
        else:
            sandbox = self.sandbox or self._sandbox()
            cases = []
            if request.operation == "check_syntax":
                single = self._request(request)
                run = sandbox.check_syntax(single)
                representative = self._case("syntax", run)
                summary = TestSummary()
            else:
                for case in request.tests.cases:
                    run = sandbox.run(self._request(request, case.stdin, case.expectedOutput))
                    cases.append(self._case(case.caseId, run))
                representative = next((c for c in cases if c.status != "SUCCESS"), cases[0])
                passed = sum(c.status == "SUCCESS" for c in cases)
                summary = TestSummary(total=len(cases), passed=passed, failed=len(cases) - passed,
                                      timedOut=sum(c.status == "TIME_LIMIT_EXCEEDED" for c in cases))
            execution = ExecutionFeedback(
                runId=str(uuid4()), source="B_SANDBOX", codeArtifactId=request.code.artifactId,
                codeRevision=request.code.revision, codeDigest=request.code.digest(),
                testSuiteId=request.tests.suiteId if request.tests else None,
                testRevision=request.tests.revision if request.tests else None,
                testDigest=request.tests.digest() if request.tests else None,
                status=representative.status, failedStage=representative.failedStage, exitCode=representative.exitCode,
                validationScope="SYNTAX_ONLY" if request.operation == "check_syntax" else "STDIO",
                summary=summary, failures=[c for c in cases if c.status != "SUCCESS"],
                stdout=representative.stdout, stderr=representative.stderr, errorLog=representative.errorLog,
                stdoutTruncated=representative.stdoutTruncated, stderrTruncated=representative.stderrTruncated,
                errorLogTruncated=representative.errorLogTruncated,
            )
        diagnosis = None
        if execution.status in {"ENVIRONMENT_ERROR", "SANDBOX_ERROR"}:
            next_action = "FIX_ENVIRONMENT"
        elif execution.status == "SUCCESS":
            next_action = "REVIEW_EXTERNAL_RESULT" if execution.source == "EXTERNAL" else (
                "ACCEPT" if execution.validationScope == "STDIO" and execution.summary.total else "RUN_TESTS")
        else:
            diagnosis = self._diagnose(request, execution)
            if diagnosis.diagnosisStatus == "INSUFFICIENT_CONTEXT":
                next_action = "PROVIDE_CONTEXT"
            else:
                next_action = "RETRIEVE_THEN_REPAIR" if diagnosis.retrieval.decision == "REQUIRED" else "REPAIR"
        result = DiagnosticResult(
            workflow=request.workflow, codeArtifactId=request.code.artifactId,
            codeRevision=request.code.revision, codeDigest=request.code.digest(),
            testSuiteId=request.tests.suiteId if request.tests else execution.testSuiteId,
            testRevision=request.tests.revision if request.tests else execution.testRevision,
            testDigest=request.tests.digest() if request.tests else execution.testDigest,
            execution=execution, diagnosis=diagnosis, warnings=warnings, nextAction=next_action,
        )
        if self.registry:
            self.registry.register_report(result, owner)
        return result

    def _diagnose(self, request, execution):
        signals = execution.model_dump()
        feedback_text = "\n".join([
            execution.errorLog, execution.stderr,
            *[f"{f.caseId}: {f.errorLog}\n{f.stderr}" for f in execution.failures],
        ])[:12000]
        rule = make_rule_decision(execution=signals, error_log=feedback_text)
        analysis, mode = self.analyzer.analyze_with_metadata(AnalyzeRequest(
            problem="\n".join([request.problem.description, *request.problem.constraints, *request.problem.acceptanceCriteria]),
            language=request.code.language, code=request.code.files[0].content, errorLog=feedback_text,
        ), rule)
        unknown = rule.errorType == "UNKNOWN" or rule.confidence == 0
        decision = "UNDETERMINED" if unknown else "REQUIRED" if rule.needRetrieval else "NOT_REQUIRED"
        query = analysis.retrievalQuery if decision == "REQUIRED" else ""
        if decision == "REQUIRED" and not query.strip():
            decision = "UNDETERMINED"
        evidence = [Evidence(source="EXECUTION", excerpt=feedback_text)] if feedback_text else []
        evidence += [Evidence(source="RULE", excerpt=str(item)[:12000]) for item in rule.evidence[:20]]
        rule_evidence = set(rule.evidence)
        evidence += [Evidence(source="MODEL" if mode == "LLM_ASSISTED" else "RULE", excerpt=str(item)[:12000])
                     for item in analysis.evidence if item not in rule_evidence][:10]
        return DiagnosisReport(
            reportId=str(uuid4()), diagnosisStatus="INSUFFICIENT_CONTEXT" if unknown else "COMPLETED",
            analysisMode=mode, failedStage=analysis.failedStage, errorType=analysis.errorType,
            errorSubtype=analysis.errorSubtype, rootCause=analysis.rootCause[:12000],
            repairSuggestion=analysis.repairSuggestion[:12000], confidence=analysis.confidence,
            evidence=evidence[:32], suspectedLocations=[],
            retrieval=RetrievalDecision(decision=decision, query=query[:12000],
                reason=rule.explanation[:12000] or "Execution feedback does not establish a reliable retrieval decision.",
                confidence=rule.confidence,
                knowledgeScope="DEPENDENCY" if rule.errorSubtype == "DEPENDENCY_MISSING" else "UNKNOWN"),
        )

    @staticmethod
    def _sandbox():
        if settings.sandbox_mode.strip().lower() == "local":
            if not settings.interop_allow_local_execution:
                raise ServiceError("LOCAL_EXECUTION_DISABLED", "Local execution requires an explicit trusted-development opt-in", 503)
            return LocalSandbox()
        return DockerSandbox()

    @staticmethod
    def _request(request, stdin="", expected=""):
        return ComparedRequest(problem=request.problem.description, language=request.code.language,
                               code=request.code.files[0].content, stdin=stdin, expectedOutput=expected)

    @staticmethod
    def _case(case_id, execution):
        if (execution.failedStage == "COMPILE" and execution.exitCode in {125, 126, 127}
                and any(signal in execution.stderr for signal in ("docker:", "Error response from daemon", "Unable to find image"))):
            execution = execution.model_copy(update={"status": "ENVIRONMENT_ERROR", "failedStage": "PRE_CHECK"})
        limit = min(12000, max(1, settings.sandbox_max_output_chars))
        stdout, out_cut = truncate_output(execution.stdout, limit)
        stderr, err_cut = truncate_output(execution.stderr, limit)
        error_log, log_cut = truncate_output(execution.errorLog, limit)
        observation = execution.observation
        return CaseFeedback(caseId=case_id, status=execution.status, failedStage=execution.failedStage,
            exitCode=execution.exitCode, stdout=stdout, stderr=stderr, errorLog=error_log,
            expectedOutput=execution.expectedOutput[:12000], executionTimeMs=execution.executionTimeMs,
            stdoutTruncated=out_cut or bool(observation and observation.stdoutTruncated),
            stderrTruncated=err_cut or bool(observation and observation.stderrTruncated),
            errorLogTruncated=log_cut or "[TRUNCATED: original length" in execution.errorLog)
