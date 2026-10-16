"""Read-only contract, public-sample and source-evidence consistency checks."""

import hashlib
import json
from pathlib import Path

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_artifact_files, check_public, check_response
from srp_b.module import DIAGNOSE, EXECUTE, STATIC


def check():
    root = Path(__file__).resolve().parents[1]
    docs = root.parent / "docs"
    registry = ContractRegistry()
    capability = json.loads((docs / "contracts/v2/capabilities.json").read_text(encoding="utf-8"))
    registry.validate("CapabilityDescriptor", capability)
    assert set(capability["operations"]) == {STATIC, EXECUTE, DIAGNOSE}
    assert {"static_feedback", "feedback_only"} <= set(capability["supported_diagnosis_modes"])
    public = json.loads((docs / "contracts/v2/local_samples.json").read_text(encoding="utf-8"))
    check_public(public)
    modes = set()
    for sample in public["samples"]:
        operation, request, response = (sample[k] for k in ("operation", "request", "response"))
        registry.validate_request(operation, request)
        registry.validate_response(operation, response)
        check_response(request, response)
        check_artifact_files(request["payload"]["code_artifact"])
        if request["payload"].get("test_artifact"):
            check_artifact_files(request["payload"]["test_artifact"])
        if operation == DIAGNOSE:
            modes.add(request["payload"]["input_mode"])
    assert modes == {"static_feedback", "feedback_only"}
    evidence = json.loads((docs / "verification/local_v2_validation.json").read_text(encoding="utf-8"))
    assert evidence["result"] == "passed" and all(c["result"] == "passed" for c in evidence["checks"])
    assert evidence["contract_sha256"] == hashlib.sha256((registry.root / "openapi_v0.2.json").read_bytes()).hexdigest()
    for relative, expected in evidence["source_hashes"].items():
        path = (root / relative).resolve()
        assert path.is_relative_to(root)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
    tests = json.loads((docs / "verification/local_v2_tests.json").read_text(encoding="utf-8"))
    assert tests["result"] == "passed"
    assert all(s["failures"] == s["errors"] == 0 for s in tests["suites"].values())
    return {"result": "passed", "public_samples": len(public["samples"]),
            "real_docker_checks": len(evidence["checks"]), "verified_source_files": len(evidence["source_hashes"])}


if __name__ == "__main__":
    print(json.dumps(check()))
