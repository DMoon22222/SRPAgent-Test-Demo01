"""P2 history/lineage checks with real B and explicitly adapted A/C mocks.

Candidate changes are declared test injections. ExecutionResult is never forged
by this driver. Original envelopes, including protected calls, stay in .interop.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import traceback

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_artifact_files, check_public, check_response
from reliable_codegen.orchestrator import Orchestrator, PATHS, demo_inputs
from reliable_codegen.transport import build_transport
from reliable_codegen.utils import canonical, digest, file_entry, files_hash, uid, utcnow

if __package__:
    from .verify_p2_local import ROOT, require, validate_bundle
else:
    from verify_p2_local import ROOT, require, validate_bundle

GOOD = "def add(a,b):\n    return a+b\n"
WRONG = "def add(a,b):\n    return a+b+1\n"
SYNTAX = "def add(a,b)\n    return a+b\n"
SCENARIOS = {
    "two_execution_failures": {"initial": "execution", "first": "execution", "executions": 4},
    "two_static_failures": {"initial": "static", "first": "static", "executions": 2},
    "static_then_execution": {"initial": "static", "first": "execution", "executions": 3},
    "wrong_parent_id": {"fault": "wrong_parent_id", "reason": "Patch parent artifact/hash mismatch", "executions": 1},
    "wrong_parent_hash": {"fault": "wrong_parent_hash", "reason": "Patch parent artifact/hash mismatch", "executions": 1},
    "wrong_parent_attempt": {"fault": "wrong_parent_attempt", "reason": "Patch parent attempt mismatch", "executions": 1},
    "reused_target_attempt": {"fault": "reused_target_attempt", "reason": "Patch target attempt mismatch", "executions": 1},
    "wrong_preserved_test_hash": {"fault": "wrong_preserved_test_hash", "reason": "Patch changed the fixed test hash", "executions": 1},
    "unauthorized_build": {"fault": "unauthorized_build", "reason": "Build manifest replacement is not authorized", "executions": 1},
    "stale_failure_source": {"fault": "stale_failure_source", "first": "execution", "reason": "INPUT_INVARIANT_VIOLATION", "executions": 2},
    "changed_fixed_tests": {"fault": "changed_fixed_tests", "reason": "FIXED_TESTS_CHANGED", "executions": 1},
}


class ScenarioTransport:
    """Public transport decorator: declare candidate/input injection and observe calls."""
    mode = "local"

    def __init__(self, base, specification):
        self.base, self.specification = base, specification
        self.registry = ContractRegistry()
        self.calls, self.repair_count = [], 0

    def capabilities(self, service):
        return self.base.capabilities(service)

    def bind_artifact_store(self, store):
        self.base.bind_artifact_store(store)

    def call(self, service, operation, envelope):
        original, delivered = deepcopy(envelope), deepcopy(envelope)
        previous_executions = [c for c in self.calls if c["service"] == "B" and c["operation"] == PATHS["execute"]]
        fault = self.specification.get("fault")
        if service == "B" and operation == PATHS["diagnose"] and fault == "stale_failure_source":
            previous_diagnoses = [c for c in self.calls if c["service"] == "B" and c["operation"] == PATHS["diagnose"]]
            if previous_diagnoses:
                delivered["payload"]["failure_source"] = deepcopy(previous_diagnoses[0]["request"]["payload"]["failure_source"])
        if service == "B" and operation == PATHS["execute"] and fault == "changed_fixed_tests" and previous_executions:
            tests = delivered["payload"]["test_artifact"]
            tests["files"][0] = file_entry(tests["files"][0]["path"], tests["files"][0]["content"] + "\n# Explicit fixed-test tampering fixture\n")
            tests["test_hash"] = files_hash(tests["files"])
        response = self.base.call(service, operation, delivered)
        original_response = deepcopy(response)
        if service == "A" and operation in {PATHS["generate"], PATHS["repair"]}:
            response = deepcopy(response)
            data = response["payload"]["data"]
            if operation == PATHS["generate"]:
                code = data["code_artifact"]
                content = SYNTAX if self.specification.get("initial") == "static" else code["files"][0]["content"]
            else:
                self.repair_count += 1
                code = data["new_code_artifact"]
                first = self.specification.get("first")
                content = (SYNTAX if first == "static" else WRONG) if self.repair_count == 1 and first else GOOD
                code["revision"] = "p2-r" + str(self.repair_count)
            code["files"][0] = file_entry(code["files"][0]["path"], content)
            code["content_hash"] = files_hash(code["files"])
            if operation == PATHS["repair"]:
                context = delivered["payload"]["repair_context"]
                if fault == "wrong_parent_id":
                    data["base_artifact_id"] = "p2-unrelated-parent"
                elif fault == "wrong_parent_hash":
                    data["base_hash"] = "0" * 64
                elif fault == "wrong_parent_attempt":
                    data["parent_attempt_id"] = "p2-unrelated-attempt"
                elif fault == "reused_target_attempt":
                    data["target_attempt_id"] = context["parent_attempt_id"]
                    code["attempt_id"] = context["parent_attempt_id"]
                elif fault == "wrong_preserved_test_hash":
                    data["preserved_test_hash"] = "0" * 64
                elif fault == "unauthorized_build":
                    data["build_manifest_mode"] = "replace"
                    data["updated_build_manifest"] = deepcopy(context["base_build_manifest"])
                    data["updated_build_manifest"]["manifest_id"] = uid("p2-unauthorized-manifest")
            response.setdefault("extensions", {})["p2_test_adapter"] = {
                "candidate_source": "Explicit synthetic A Mock candidate adapter; no actual A model",
                "fault": fault, "repair_index": self.repair_count}
        self.registry.validate_response(operation, response)
        check_response(delivered, response)
        if delivered["visibility"] == "public":
            check_public(response)
        self.calls.append({"service": service, "operation": operation, "original_request": original,
                           "request": delivered, "original_response": original_response, "response": deepcopy(response)})
        return response


def run_scenario(base_transport, directory, name, *, evidence_kind="synthetic_unit_backend", expected_image=None):
    spec = SCENARIOS[name]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    transport = ScenarioTransport(base_transport, spec)
    engine = Orchestrator(transport, directory / "o", max_repairs=2, routing_mode="no_rag")
    result = engine.run(**demo_inputs())
    (directory / "original-calls.json").write_text(canonical(transport.calls), encoding="utf-8")
    (directory / "o-summary.json").write_text(canonical(result), encoding="utf-8")
    b_calls = [c for c in transport.calls if c["service"] == "B"]
    execution_calls = [c for c in b_calls if c["operation"] == PATHS["execute"]]
    diagnoses = [c for c in b_calls if c["operation"] == PATHS["diagnose"]]
    repairs = [c for c in transport.calls if c["service"] == "A" and c["operation"] == PATHS["repair"]]
    observed_executions = sum(c["response"]["payload"]["usage"]["execution_calls"] for c in execution_calls)
    require(observed_executions == spec["executions"], "UNEXPECTED_PHYSICAL_EXECUTION_COUNT")
    require(result["budget"]["used"]["execution_calls"] == observed_executions, "O_EXECUTION_ACCOUNTING_MISMATCH")
    require(all(c["response"]["payload"]["usage"]["execution_calls"] == 0 for c in diagnoses), "DIAGNOSIS_REEXECUTED")
    require(all(transport.capabilities(n).get("extensions", {}).get("mock") for n in ("A", "C")), "MOCK_SOURCE_MARKER_LOST")
    observed_images = set()
    for call in execution_calls:
        payload = call["response"]["payload"]
        if payload["status"] == "completed":
            context = payload["data"]["execution_context"]
            if context["image_digest"]:
                observed_images.add(context["image_digest"])
            if expected_image:
                require(context["image_digest"] == expected_image and context["isolation_guarantees"].get("container_cleanup_confirmed"),
                        "EXECUTION_ENVIRONMENT_OR_CLEANUP_MISMATCH")

    trace = []
    if "reason" not in spec:
        require(result["state"] == "accepted" and result["iterations"] == 2 and len(diagnoses) == len(repairs) == 2,
                "TWO_ROUND_FLOW_INCOMPLETE")
        first_report = diagnoses[0]["response"]["payload"]["data"]["diagnosis_report"]
        second_request = diagnoses[1]["request"]["payload"]
        second_report = diagnoses[1]["response"]["payload"]["data"]["diagnosis_report"]
        require(second_request["prior_diagnosis_ref"]["artifact_id"] == first_report["diagnosis_id"] == second_report["prior_diagnosis_id"],
                "PRIOR_DIAGNOSIS_CHAIN_MISMATCH")
        history = second_request["history_view"]
        require(len(history["attempt_summaries"]) == 2 and history["truncation"]["truncated"] is False, "HISTORY_CONTINUITY_MISMATCH")
        require(history["attempt_summaries"][1]["parent_attempt_id"] == history["attempt_summaries"][0]["attempt_id"], "HISTORY_PARENT_MISMATCH")
        fixed_tests, fixed_manifest = None, None
        for c in b_calls:
            p = c["request"]["payload"]
            manifest = p.get("build_manifest", p.get("execution_context", {}).get("build_manifest"))
            if manifest:
                fixed_manifest = fixed_manifest or manifest
                require(manifest == fixed_manifest, "BUILD_MANIFEST_CHANGED")
            if p.get("test_artifact") and c["request"]["visibility"] == "public":
                fixed_tests = fixed_tests or p["test_artifact"]
                require(p["test_artifact"] == fixed_tests, "PUBLIC_TESTS_CHANGED")
            if c["operation"] == PATHS["diagnose"]:
                data = c["response"]["payload"]["data"]
                require(data["failure_source"] == data["diagnosis_report"]["failure_source"] == p["failure_source"], "ORIGINAL_FAILURE_CHANGED")
                fact = p["failure_source"]["static_report" if p["failure_source"]["kind"] == "static" else "execution_result"]
                require(fact["attempt_id"] == c["request"]["attempt_id"] and fact["code_hash"] == p["code_artifact"]["content_hash"],
                        "FACT_CURRENT_CANDIDATE_MISMATCH")
                if p["failure_source"]["kind"] == "static":
                    require(data["diagnosis_report"]["execution_result_id"] is None, "STATIC_SOURCE_HAS_EXECUTION")
                trace.append({"attempt_id": c["request"]["attempt_id"], "code_id": fact["code_artifact_id"], "revision": fact["revision"],
                              "code_hash": fact["code_hash"], "source_kind": p["failure_source"]["kind"],
                              "diagnosis_id": data["diagnosis_report"]["diagnosis_id"], "prior_diagnosis_id": data["diagnosis_report"]["prior_diagnosis_id"]})
        for c in repairs:
            patch = c["response"]["payload"]["data"]
            ctx = c["request"]["payload"]["repair_context"]
            require(patch["base_artifact_id"] == patch["new_code_artifact"]["parent_artifact_id"] == ctx["base_code_artifact"]["artifact_id"],
                    "PATCH_PARENT_MISMATCH")
            require(patch["new_code_artifact"]["attempt_id"] == ctx["target_attempt_id"] != ctx["parent_attempt_id"], "PATCH_ATTEMPT_MISMATCH")
            require(patch["preserved_test_hash"] == fixed_tests["test_hash"] and patch["build_manifest_mode"] == "inherit", "PATCH_FIXED_CONTEXT_CHANGED")
            check_artifact_files(patch["new_code_artifact"])
    else:
        require(result["state"] == "human_review" and result["stop_reason"] == spec["reason"], "EXPECTED_REJECTION_NOT_OBSERVED")
        require(len(repairs) == 1, "ILLEGAL_CANDIDATE_CONTINUED_REPAIR")
        if name == "changed_fixed_tests":
            require(len(execution_calls) == 2 and execution_calls[-1]["response"]["payload"]["usage"]["execution_calls"] == 0,
                    "TAMPERED_TESTS_REACHED_RUNNER")
        elif name == "stale_failure_source":
            require(len(diagnoses) == 2 and diagnoses[-1]["request"]["payload"]["failure_source"] != diagnoses[-1]["original_request"]["payload"]["failure_source"],
                    "STALE_FACT_INJECTION_NOT_EXERCISED")
        else:
            require(len(execution_calls) == 1, "ILLEGAL_PATCH_REACHED_B_EXECUTION")
    public = {"scenario": name, "result": "passed", "evidence_kind": evidence_kind,
              "candidate_source": "Declared A/C Mock test adapter; no actual model", "terminal": result["state"],
              "stop_reason": result["stop_reason"], "iterations": result["iterations"], "run_id": result["run_id"],
              "trace_id": engine.trace_id, "execution_requests": len(execution_calls), "physical_execution_calls": observed_executions,
              "diagnosis_calls": len(diagnoses), "repair_calls": len(repairs), "routing_mode": "no_rag", "repair_limit": 2,
              "observed_image_ids": sorted(observed_images), "lineage": trace}
    check_public(public)
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--config", type=Path, default=ROOT.parent / "docs/integration/config.b-local.p2.example.json")
    parser.add_argument("--manifest", type=Path, default=ROOT.parent / "docs/integration/p2_handoff_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "docs/verification/p2/lineage_validation.json")
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker is required for the fixed self-authored lineage fixtures")
    private = ROOT / ".interop/p2-lineage" / uid("run")
    private.mkdir(parents=True)
    summary = {"verified_at": utcnow(), "result": "failed", "scope": "P2 multi-round history/parent/fixed-test technical verification",
               "formal_p2_acceptance": "blocked", "o_receipt": "not_received", "model_calls": 0, "cases": [],
               "raw_records": "Private python_service/.interop/p2-lineage directory; not committed"}
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_bundle(config, manifest, ContractRegistry())
        image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", manifest["image"]["configured_name"]], text=True).strip()
        require(image == manifest["image"]["expected_id"], "LOCKED_IMAGE_MISMATCH")
        overlay = {"lineage_driver": Path(__file__), "lineage_tests": ROOT / "tests/test_local_v2_p2_lineage.py",
                   "bootstrap_driver": ROOT / "scripts/verify_p2_local.py", "config": args.config, "manifest": args.manifest}
        summary.update(implementation_version=manifest["implementation_version"], source_revision=manifest["source"]["revision"],
                       image_digest=image, public_contract_sha256=manifest["public_contract_sha256"],
                       config_canonical_sha256=manifest["config_canonical_sha256"],
                       configuration_overrides={"O.routing_mode": "no_rag to isolate B history/lineage cases", "B.options.state_dir": "Unique private directory per scenario", "O.output_dir": "Unique private directory per scenario"},
                       source_overlay="Uncommitted test adapter and driver; fixed B runtime is unchanged",
                       host_python=platform.python_version(),
                       host_packages={name: importlib.metadata.version(name) for name in ("pytest", "pydantic", "jsonschema")},
                       overlay_hashes={role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in overlay.items()},
                       overlay_files={role: path.name for role, path in overlay.items()})
        for name in SCENARIOS:
            active = deepcopy(config)
            active["modules"]["B"]["options"]["state_dir"] = str(private / name / "b")
            record = run_scenario(build_transport(active), private / name, name,
                                  evidence_kind="real_docker_with_declared_mock_candidates_and_fault_injection", expected_image=image)
            summary["cases"].append(record)
            print("passed: " + name, flush=True)
        summary["result"] = "passed"
    except Exception as error:
        summary["error_code"] = str(error) if isinstance(error, ValueError) and str(error).replace("_", "").isupper() else "LINEAGE_VERIFICATION_FAILED"
        (private / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    summary["unverified"] = ["Full reference/unknown/late/protected-receiver P2 matrix", "Formal TEST-001 lock and target A context metadata", "O independent receipt", "Real A/C algorithms"]
    check_public(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"result": summary["result"], "cases": len(summary["cases"]), "formal_p2_acceptance": summary["formal_p2_acceptance"]}))
    return 0 if summary["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
