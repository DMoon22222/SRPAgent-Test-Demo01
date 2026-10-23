"""Real rule-based diagnosis of supplied facts; no target or model is invoked."""

from __future__ import annotations

from copy import deepcopy

from app.analyzer.error_signal_extractor import make_rule_decision
from reliable_codegen.utils import canonical, digest, uid, utcnow


def diagnose(request, *, prior=None, logs=None):
    payload = request["payload"]
    source = payload["failure_source"]
    static = source["kind"] == "static"
    fact = source["static_report" if static else "execution_result"]
    code = payload["code_artifact"]
    evidence, locations = [], []
    if static:
        failures = [f for f in fact["findings"] if f["status"] != "passed"]
        text = "\n".join(f["message"] for f in failures)
        locations = [deepcopy(f["location"]) for f in failures if f["location"]]
        failed = fact["status"] != "passed"
        stage = "static" if failed else "none"
        failure_class = "syntax_error" if any(f["check"] == "syntax" for f in failures) else "unknown"
        domain = "code" if fact["status"] == "failed" else "unknown"
        for index, finding in enumerate(fact["findings"]):
            if finding["status"] != "passed":
                evidence.append({"kind": "source_location", "artifact_id": fact["report_id"],
                                 "pointer": f"/findings/{index}", "summary": finding["message"]})
    else:
        # Keep each resolved stream's identity; combined text has no /stderr provenance.
        streams = logs if logs is not None else {name: fact[name].get("text", "") for name in ("stdout", "stderr")}
        text_parts = []
        failed = fact["test_outcome"] != "passed"
        stage = fact["failure_stage"]
        domain = "code"
        failure_class = "test_failure" if fact["test_outcome"] == "failed" else "unknown"
        if fact["execution_status"] == "infrastructure_error":
            failure_class, domain = "environment_error", "environment"
        elif fact["execution_status"] == "policy_rejected":
            failure_class, domain = "unknown", "policy"
        elif fact["execution_status"] == "timeout":
            failure_class = "timeout"
        elif fact["execution_status"] == "oom":
            failure_class = "resource_limit"
        for index, case in enumerate(fact["test_case_results"]):
            if case["status"] in {"failed", "error"}:
                evidence.append({"kind": "test_result", "artifact_id": fact["execution_id"],
                                 "pointer": f"/test_case_results/{index}", "summary": case["message"] or case["status"]})
                if case["location"]:
                    locations.append(deepcopy(case["location"]))
                text_parts.append("\n".join(filter(None, (case["error_type"], case["message"]))))
        # Test facts precede logs, so assertion evidence also survives the analysis limit.
        for name in ("stdout", "stderr"):
            content = streams.get(name, "")
            if content.strip():
                evidence.append({"kind": "log_span", "artifact_id": fact["execution_id"],
                                 "pointer": f"/{name}", "summary": content[:512]})
                text_parts.append(content)
        text = "\n".join(text_parts)
    rule = make_rule_decision(error_log=text[:24000])
    if failed and domain == "code" and not static and failure_class not in {"timeout", "resource_limit"}:
        failure_class = {"COMPILE_ERROR": "syntax_error", "RUNTIME_ERROR": "runtime_error",
                         "WRONG_ANSWER": "test_failure", "API_MISUSE": "dependency_error"}.get(rule.errorType, failure_class)
    # A recognized exception alone does not establish the semantic root cause.
    sufficient = bool(evidence) and (rule.confidence > 0 or failure_class != "unknown")
    hint = "needed" if rule.needRetrieval else "not_needed" if sufficient else "unknown"
    action = "fix_environment" if domain == "environment" else "stop" if domain == "policy" else "repair" if sufficient else "collect_information"
    root_cause = rule.explanation if rule.confidence else "The supplied failure evidence does not establish a specific root cause."
    if failure_class == "test_failure" and rule.confidence == 0:
        root_cause = "The supplied fixed tests failed; inspect the recorded assertions before changing the implementation."
    confidence = rule.confidence if rule.confidence else None
    if not failed:
        failure_class, domain, stage, root_cause, confidence, hint, action = "none", "none", "none", None, None, "not_needed", "none"
    gap = [] if sufficient or not failed else [{
        "description": "Insufficient diagnostic evidence", "symbols": [],
        "required_versions": [], "missing_information": ["A precise failing assertion or exception and its source location"],
    }]
    report = {
        "schema_version": "2.0", "created_at": utcnow(), "producer": "B",
        "diagnosis_id": uid("diagnosis"), "task_id": request["task_id"],
        "code_artifact_id": code["artifact_id"], "revision": code["revision"],
        "execution_result_id": None if static else fact["execution_id"],
        "test_hash": payload["test_artifact"]["test_hash"],
        "failure_class": failure_class, "raw_failure_class": rule.errorSubtype if failed else None,
        "failure_stage": stage, "root_cause": root_cause, "confidence": confidence,
        "evidence_refs": evidence, "suggestions": ["Use the supplied code, fixed tests and recorded evidence to produce a new candidate."] if domain == "code" and failed else [],
        "retrieval_hint": hint, "next_action": action,
        "prior_diagnosis_id": prior["diagnosis_id"] if prior else None,
        "failure_source": deepcopy(source), "failure_domain": domain,
        "hypotheses": [{"hypothesis_id": uid("hypothesis"), "statement": root_cause,
                        "confidence": confidence, "evidence_refs": deepcopy(evidence), "locations": deepcopy(locations)}] if failed and evidence else [],
        "locations": locations, "context_gap": gap,
        "local_context_sufficiency": "sufficient" if sufficient or not failed else "insufficient",
        "query_hints": [rule.retrievalQuery] if rule.needRetrieval and rule.retrievalQuery else [],
        "failure_signature": digest(canonical({"code_hash": code["content_hash"], "failure_class": failure_class,
                                                "stage": stage, "raw": rule.errorSubtype})) if failed else None,
        "extensions": {"srp_b": {"algorithm": "existing-rule-extractor-v1", "model_calls": 0,
                                    "retrieval_hint_is_advisory": True}},
    }
    return {"failure_source": deepcopy(source), "diagnosis_report": report,
            "retrieval_hint": hint, "next_action": action}
