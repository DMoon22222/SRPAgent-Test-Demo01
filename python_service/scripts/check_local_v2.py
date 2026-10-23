"""Read-only validation of public delivery samples and current source evidence."""

import hashlib
import json
from pathlib import Path

from reliable_codegen.contracts import ContractError, ContractRegistry
from reliable_codegen.guards import check_artifact_files, check_execution_cases, check_public, check_response
from reliable_codegen.utils import canonical, digest
from srp_b import __version__
from srp_b.module import DIAGNOSE, EXECUTE, STATIC
from srp_b.samples import sample_request

REQUIRED_SCENARIOS = {"static_failure", "static_diagnosis", "execution_failure", "execution_diagnosis",
                      "execution_success", "environment_failure", "timeout", "protected_diagnosis_rejected",
                      "diagnosis_failure_retains_fact", "execution_not_authorized", "completed_replay"}
PROTECTED_PATCHES = [
    {"pointer": "/payload/failure_source/execution_result/visibility", "value": "restricted"},
    {"pointer": "/payload/failure_source/execution_result/purpose", "value": "final_acceptance"},
]


def check_diagnostic_evidence(data):
    """Schema permits pointer strings; public samples must also prove their targets."""
    report, source = data["diagnosis_report"], data["failure_source"]
    assert report["failure_source"] == source
    static = source["kind"] == "static"
    fact = source["static_report" if static else "execution_result"]
    identity = fact["report_id" if static else "execution_id"]
    refs = report["evidence_refs"]
    for hypothesis in report["hypotheses"]:
        assert hypothesis["evidence_refs"] and all(ref in refs for ref in hypothesis["evidence_refs"])
    for ref in refs:
        assert ref["artifact_id"] == identity
        pointer = ref["pointer"]
        if ref["kind"] == "log_span":
            assert not static and pointer in {"/stdout", "/stderr"}
            text = fact[pointer[1:]]["text"]
            assert text.strip() and ref["summary"] and ref["summary"] in text
        elif ref["kind"] == "test_result":
            assert not static and pointer.startswith("/test_case_results/")
            index = pointer.rsplit("/", 1)[1]
            assert index.isdigit()
            case = fact["test_case_results"][int(index)]
            assert case["status"] in {"failed", "error"}
            assert ref["summary"] == (case["message"] or case["status"])
        else:
            assert static and pointer.startswith("/findings/")
            index = pointer.rsplit("/", 1)[1]
            assert index.isdigit()
            finding = fact["findings"][int(index)]
            assert finding["status"] != "passed" and ref["summary"] == finding["message"]
    assert report["task_id"] == fact["task_id"]
    assert report["code_artifact_id"] == fact["code_artifact_id"] and report["revision"] == fact["revision"]
    assert data["retrieval_hint"] == report["retrieval_hint"] and data["next_action"] == report["next_action"]


def check_sample(sample, registry):
    check_public(sample)  # Rejection fixtures must not serialize protected objects either.
    operation, response = sample["operation"], sample["response"]
    registry.validate_request(operation, sample["request"])
    request = sample_request(sample)
    assert sample["observed_request_sha256"] == digest(canonical(request))
    expected = sample["expected"]
    if sample.get("request_patches"):
        assert sample["sample_id"] == "protected_diagnosis_rejected"
        assert sample["evidence_kind"] == "fault_injection" and sample["request_patches"] == PROTECTED_PATCHES
        try:
            registry.validate_request(operation, request)
        except ContractError:
            pass  # The actual illegal input must fail the public diagnosis schema.
        else:
            raise AssertionError("Protected diagnostic fixture unexpectedly conforms")
        try:
            check_public(request)
        except ContractError:
            pass
        else:
            raise AssertionError("Protected diagnostic fixture unexpectedly became public")
    else:
        check_public(request)
    for key in ("code_artifact", "test_artifact", "build_manifest"):
        if request["payload"].get(key):
            check_artifact_files(request["payload"][key])
    if expected["response_kind"] == "transport_error":
        registry.validate("TransportErrorResponse", response)
        assert response["request_id"] == request["request_id"] and response["trace_id"] == request["trace_id"]
        assert response["error"]["failed_call_id"] == request["call_id"]
        assert response["error"]["error_code"] == expected["error_code"]
        assert response["error"]["details"] == {} and "payload" not in response
        return
    registry.validate_response(operation, response)
    check_response(request, response)
    payload = response["payload"]
    assert payload["status"] == expected["status"]
    if payload["status"] == "completed":
        if operation == STATIC:
            fact, code = payload["data"], request["payload"]["code_artifact"]
            assert fact["code_hash"] == code["content_hash"] and fact["revision"] == code["revision"]
            assert fact["code_artifact_id"] == code["artifact_id"]
            assert all(fact[key] == request[key] for key in ("task_id", "attempt_id"))
        elif operation == EXECUTE:
            fact = payload["data"]
            code, tests = (request["payload"][key] for key in ("code_artifact", "test_artifact"))
            check_execution_cases(fact)
            for key in ("task_id", "attempt_id"):
                assert fact[key] == request[key]
            assert fact["code_artifact_id"] == code["artifact_id"] and fact["revision"] == code["revision"]
            assert fact["code_hash"] == code["content_hash"]
            assert fact["test_artifact_id"] == tests["artifact_id"] and fact["test_hash"] == tests["test_hash"]
            context = fact["execution_context"]
            assert context["build_manifest"] == request["payload"]["build_manifest"]
            assert context["execution_policy"] == request["payload"]["execution_policy"]
            assert fact["execution_config_hash"] == context["execution_config_hash"] == digest(canonical({
                "manifest": context["build_manifest"], "policy": context["execution_policy"]}))
            for name in ("stdout", "stderr"):
                assert fact[name]["sha256"] == digest(fact[name]["text"])
        elif operation == DIAGNOSE:
            assert payload["data"]["failure_source"] == request["payload"]["failure_source"]
            report = payload["data"]["diagnosis_report"]
            assert report["test_hash"] == request["payload"]["test_artifact"]["test_hash"]
            check_diagnostic_evidence(payload["data"])
    elif payload["status"] == "error":
        assert payload["error"]["error_code"] == expected["error_code"]
        fact = request["payload"]["failure_source"]["execution_result"]
        ref = payload["error"]["partial_result_ref"]
        assert sample["partial_result_resolved"] is True
        assert ref == {"artifact_id": fact["execution_id"], "artifact_type": "ExecutionResult",
                       "sha256": digest(canonical(fact)), "media_type": "application/json",
                       "visibility": "public", "resolver_key": "local-store"}
    else:
        assert payload["data"]["reason"] == expected["reason"]
    if expected.get("execution_status"):
        assert payload["data"]["execution_status"] == expected["execution_status"]
    if "execution_calls" in expected:
        assert payload["usage"]["execution_calls"] == expected["execution_calls"]


def check():
    root = Path(__file__).resolve().parents[1]
    docs = root.parent / "docs"
    registry = ContractRegistry()
    capability = json.loads((docs / "contracts/v2/capabilities.json").read_text(encoding="utf-8"))
    registry.validate("CapabilityDescriptor", capability)
    assert set(capability["operations"]) == {STATIC, EXECUTE, DIAGNOSE}
    assert {"static_feedback", "feedback_only"} <= set(capability["supported_diagnosis_modes"])
    assert capability["extensions"]["srp_b"]["implementation_version"] == __version__
    public = json.loads((docs / "contracts/v2/local_samples.json").read_text(encoding="utf-8"))
    check_public(public)
    samples = {sample["sample_id"]: sample for sample in public["samples"]}
    assert len(samples) == len(public["samples"]) and REQUIRED_SCENARIOS <= samples.keys()
    for sample in samples.values():
        check_sample(sample, registry)
        if sample.get("replay_of"):
            previous = samples[sample["replay_of"]]
            assert sample["request"] == previous["request"] and sample["response"] == previous["response"]
    evidence = json.loads((docs / "verification/local_v2_validation.json").read_text(encoding="utf-8"))
    assert evidence["result"] == "passed" and all(c["result"] == "passed" for c in evidence["checks"])
    assert evidence["contract_sha256"] == hashlib.sha256((registry.root / "openapi_v0.2.json").read_bytes()).hexdigest()
    for relative, expected in evidence["source_hashes"].items():
        path = (root / relative).resolve()
        assert path.is_relative_to(root)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
    assert evidence["source_snapshot_sha256"] == digest(canonical(evidence["source_hashes"]))
    assert public["source_snapshot_sha256"] == evidence["source_snapshot_sha256"]
    tests = json.loads((docs / "verification/local_v2_tests.json").read_text(encoding="utf-8"))
    assert tests["result"] == "passed" and tests["source_hashes"] == evidence["source_hashes"]
    assert all(s["failures"] == s["errors"] == 0 for s in tests["suites"].values())
    return {"result": "passed", "public_samples": len(public["samples"]),
            "verification_checks": len(evidence["checks"]), "verified_source_files": len(evidence["source_hashes"])}


if __name__ == "__main__":
    print(json.dumps(check()))
