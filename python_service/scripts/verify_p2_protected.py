"""P2 protected receiver-view checks, with real B and declared A/C Mock.

Synthetic final tests and canaries are created per run and retained privately.
Shared O, transport, Schema, guards and Mock implementations are unchanged.
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

from reliable_codegen.artifact_access import referenced_artifacts
from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public, check_response
from reliable_codegen.orchestrator import Orchestrator, PATHS, demo_inputs
from reliable_codegen.storage import ArtifactRestricted
from reliable_codegen.transport import TransportError, build_transport
from reliable_codegen.utils import canonical, file_entry, files_hash, uid, utcnow
from srp_b.samples import diagnostic

if __package__:
    from .verify_p2_local import ROOT, require, validate_bundle
    from .verify_p2_boundaries import CountingRunner
else:
    from verify_p2_local import ROOT, require, validate_bundle
    from verify_p2_boundaries import CountingRunner

SCENARIOS = {
    "hidden_pass": ("accepted", None),
    "hidden_failure": ("stopped", "FINAL_ACCEPTANCE_FAILED"),
    "protected_business_error": ("human_review", "PROTECTED_OPERATION_FAILED"),
    "protected_transport_error": ("human_review", "MODULE_OPERATION_REJECTED"),
    "protected_module_exception": ("human_review", "OUTCOME_UNKNOWN"),
    "protected_late_result": ("human_review", "LATE_RESULT_NOT_APPLIED"),
}


class ReceiverObserver:
    """Observe actual module entry, downstream of the shared public guard."""
    def __init__(self, module, bridge, service):
        self.module, self.bridge, self.service = module, bridge, service
        self.calls, self.responses = [], []

    def capabilities(self):
        return self.module.capabilities()

    def bind_artifact_resolver(self, resolver):
        self.module.bind_artifact_resolver(resolver)

    def call(self, operation, envelope):
        self.calls.append((operation, deepcopy(envelope)))
        response = self.module.call(operation, envelope)
        self.responses.append((operation, deepcopy(response)))
        if self.service == "B" and envelope["visibility"] == "restricted":
            if self.bridge.name == "protected_module_exception":
                raise RuntimeError(self.bridge.error_canary)
            if self.bridge.name == "protected_late_result":
                # After the real B return, original LocalTransport detects late.
                self.bridge.base.timeout = 1e-12
        return response


class ProtectedTransport:
    """O-side fixture/observer; a storage handle is never delivered to B/A/C."""
    mode = "local"

    def __init__(self, base, name, error_canary):
        self.base, self.name, self.error_canary = base, name, error_canary
        self.store, self.records, self.private_refs = None, [], []
        self.observers = {service: ReceiverObserver(module, self, service) for service, module in base.modules.items()}
        base.modules = dict(self.observers)

    def capabilities(self, service):
        return self.base.capabilities(service)

    def bind_artifact_store(self, store):
        self.store = store
        self.base.bind_artifact_store(store)

    def _error_response(self, original):
        response = deepcopy(original)
        fact = original["payload"]["data"]
        partial = self.store.put(fact, "ExecutionResult", fact["execution_id"], visibility="restricted")
        cause = self.store.put({"private_fault": self.error_canary}, "ProtectedFixtureCause", visibility="restricted")
        self.private_refs.extend([partial, cause])
        response["payload"].update(status="error", data=None, error={
            "error_code": self.error_canary, "message": self.error_canary, "retryable": False,
            "stage": "execute", "observed_at": utcnow(), "details": {"private_detail": self.error_canary},
            "fallback_reason": "human_review", "partial_result_ref": partial, "cause_ref": cause,
            "failed_call_id": response["call_id"],
        })
        response.setdefault("extensions", {})["p2_fault_fixture"] = self.name
        return response

    def call(self, service, operation, envelope):
        record = {"service": service, "operation": operation, "request": deepcopy(envelope)}
        self.records.append(record)
        try:
            response = self.base.call(service, operation, envelope)
            record["original_response"] = deepcopy(response)
            if service == "B" and envelope["visibility"] == "restricted" and self.name in {
                "protected_business_error", "protected_transport_error"
            }:
                response = self._error_response(response)
                ContractRegistry().validate_response(operation, response)
                check_response(envelope, response)
                if self.name == "protected_transport_error":
                    raise TransportError(self.error_canary, response=response, status_code=500, outcome_unknown=False)
            record["response"] = deepcopy(response)
            return response
        except TransportError as error:
            record["transport_error"] = {"message": str(error), "response": deepcopy(error.response),
                                         "outcome_unknown": error.outcome_unknown}
            raise


def public_view(engine, summary):
    """Public events and their reachable artifacts, via verified store APIs."""
    events = engine.store.events(summary["run_id"])
    values = [summary, *events]
    queue = [ref for event in events for ref in referenced_artifacts(event)]
    queue.append(summary["evaluation_ref"])
    seen = set()
    while queue:
        reference = queue.pop()
        key = canonical(reference)
        if key in seen:
            continue
        seen.add(key)
        record = engine.store.record(reference["artifact_id"])
        require(record["artifact_ref"] == reference, "PUBLIC_REF_IDENTITY_MISMATCH")
        value = json.loads(record["body_utf8"]) if record["content_kind"] == "json" else record["body_utf8"]
        check_public(value)
        values.append(value)
        queue.extend(referenced_artifacts(value))
    for value in values:
        check_public(value)
    return values, len(events), len(seen)


def reject_public_probes(bridge, final_request, final_fact, final_ref):
    """Attempt invalid public handoffs; rejected data must not reach modules."""
    before = {service: len(observer.calls) for service, observer in bridge.observers.items()}
    diagnosis = diagnostic(final_fact, final_request)
    a_request = deepcopy(next(x[1] for x in bridge.observers["A"].calls if x[0] == PATHS["generate"]))
    a_request["message_id"] = uid("negative-msg")
    a_request["payload"]["provided_tests"] = deepcopy(final_request["payload"]["test_artifact"])
    c_request = deepcopy(bridge.observers["C"].calls[0][1])
    c_request["message_id"] = uid("negative-msg")
    c_request["payload"]["history_view"]["source_refs"].append(final_ref)
    probes = [("B", PATHS["diagnose"], diagnosis), ("A", PATHS["generate"], a_request),
              ("C", PATHS["decide"], c_request)]
    denials = []
    for service, operation, envelope in probes:
        try:
            bridge.base.call(service, operation, envelope)
        except TransportError as error:
            require(error.response["error"]["error_code"] == "CONTRACT_INVALID", "WRONG_PUBLIC_REJECTION")
            check_public(error.response)
            denials.append(error.response)
        else:
            raise ValueError("PROTECTED_INPUT_REACHED_PUBLIC_MODULE")
    try:
        bridge.observers["B"].module.call(PATHS["diagnose"], diagnosis)
    except TransportError as error:
        require(error.response["error"]["error_code"] == "CONTRACT_INVALID", "B_DIRECT_DIAGNOSIS_NOT_REJECTED")
        check_public(error.response)
        denials.append(error.response)
    else:
        raise ValueError("B_DIRECT_DIAGNOSIS_ACCEPTED_PROTECTED_FACT")
    require(before == {service: len(observer.calls) for service, observer in bridge.observers.items()}, "PUBLIC_REJECT_INVOKED_MODULE")
    return {"count": len(denials), "responses": denials, "module_invocations_added": 0}


def run_scenario(base, runner, directory, name, *, expected_image=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    error_canary = uid("p2-private-error")
    hidden_name = "test_p2_hidden_" + uid("canary").replace("-", "_")
    hidden_canary = uid("p2-private-body")
    bridge = ProtectedTransport(base, name, error_canary)
    inputs = demo_inputs()
    expected = 43 if name == "hidden_failure" else 42
    content = ("from src.main import add\n\n" + f"# {hidden_canary}\n" + f"def {hidden_name}():\n"
               + f"    assert add(19, 23) == {expected}, '{hidden_canary}'\n")
    tests = inputs["final_tests"]
    tests["files"] = [file_entry("tests/test_main.py", content)]
    tests["test_hash"] = files_hash(tests["files"])
    original_inputs = deepcopy(inputs)
    engine = Orchestrator(bridge, directory / "o", max_repairs=2, routing_mode="adaptive_rag", deadline_seconds=180)
    summary = engine.run(**inputs)
    require(inputs == original_inputs, "INPUTS_MUTATED")
    require((summary["state"], summary["stop_reason"]) == SCENARIOS[name], "PROTECTED_TERMINAL_MISMATCH")
    require(summary["iterations"] == 1, "PROTECTED_FLOW_REPAIR_COUNT_MISMATCH")
    require(all(bridge.capabilities(service).get("extensions", {}).get("mock") for service in ("A", "C")), "MOCK_MARKER_LOST")
    calls = bridge.records
    final_records = [x for x in calls if x["request"]["visibility"] == "restricted"]
    require(len(final_records) == 1 and final_records[0] is calls[-1], "FINAL_RESULT_RETURNED_TO_LOOP")
    final_record = final_records[0]
    final_request = final_record["request"]
    require(final_record["service"] == "B" and final_record["operation"] == PATHS["execute"], "PROTECTED_RECIPIENT_MISMATCH")
    require(final_request["payload"]["purpose"] == "final_acceptance" and final_request["payload"]["test_artifact"] == tests,
            "FINAL_TESTS_CHANGED")
    previous_execution = [x for x in calls[:-1] if x["operation"] == PATHS["execute"]][-1]
    for key in ("code_artifact", "build_manifest", "execution_policy"):
        require(previous_execution["request"]["payload"][key] == final_request["payload"][key], "SEALED_CANDIDATE_CHANGED")
    b_observer = bridge.observers["B"]
    final_fact = b_observer.responses[-1][1]["payload"]["data"]
    require(final_fact["visibility"] == "restricted" and final_fact["purpose"] == "final_acceptance", "FINAL_FACT_NOT_PROTECTED")
    require(final_fact["test_hash"] == tests["test_hash"] and final_fact["test_case_results"], "FINAL_TEST_FACT_MISMATCH")
    require(all(x["oracle_level"] == "final_hidden" for x in final_fact["test_case_results"]), "FINAL_CASE_ORACLE_MISMATCH")
    require(final_fact["test_outcome"] == ("failed" if name == "hidden_failure" else "passed"), "FINAL_OUTCOME_MISMATCH")
    if expected_image:
        require(hidden_name in canonical(final_fact["test_case_results"]), "FIXED_FINAL_TEST_NOT_OBSERVED")
    public, event_count, artifact_count = public_view(engine, summary)
    a_calls, c_calls = bridge.observers["A"].calls, bridge.observers["C"].calls
    require(any(x[0] == PATHS["repair"] for x in a_calls) and c_calls, "RECEIVER_VIEWS_NOT_EXERCISED")
    diagnoses = [x for x in calls if x["operation"] == PATHS["diagnose"]]
    require(len(diagnoses) == 1 and diagnoses[0]["request"]["visibility"] == "public", "HIDDEN_FACT_DIAGNOSED")
    receiver_values = [value for observer in bridge.observers.values() for op, value in observer.calls if value["visibility"] == "public"]
    receiver_values.extend(value for observer in (bridge.observers["A"], bridge.observers["C"]) for _, value in observer.responses)
    canaries = [error_canary, hidden_canary, hidden_name, tests["artifact_id"], final_fact["execution_id"]]
    for ref in bridge.private_refs:
        canaries.append(ref["artifact_id"])
    for value in [*public, *receiver_values]:
        check_public(value)
        require(not any(marker in canonical(value) for marker in canaries), "PROTECTED_CANARY_IN_PUBLIC_VIEW")
    all_events = engine.store.events(summary["run_id"], allow_restricted=True)
    final_event_index = next(i for i, x in enumerate(all_events) if x["event_type"] == "request" and x["message_id"] == final_request["message_id"])
    previous_states = [x["state_after"] for x in all_events[:final_event_index] if x["event_type"] == "state_transition"]
    require(previous_states[-2:] == ["sealed", "final_evaluating"], "FINAL_STARTED_BEFORE_SEAL")
    final_ref = engine.store.record(tests["artifact_id"], allow_restricted=True)["artifact_ref"]
    restricted_refs = [final_ref, *bridge.private_refs]
    for ref in restricted_refs:
        try:
            engine.store.get(ref)
        except ArtifactRestricted:
            pass
        else:
            raise ValueError("PROTECTED_STORE_READ_ALLOWED")
    require(engine.store.get(final_ref, allow_restricted=True) == tests, "PROTECTED_ORIGINAL_LOST")
    if bridge.private_refs:
        require(engine.store.get(bridge.private_refs[0], allow_restricted=True) == final_fact, "PROTECTED_PARTIAL_NOT_RESOLVABLE")
        require(summary["module_errors"] == [{"error_code": "PROTECTED_OPERATION_FAILED", "stage": "final_acceptance"}],
                "PROTECTED_ERROR_NOT_REDACTED")
        restricted_records = [engine.store.get(x["output_refs"][0], allow_restricted=True)
                              for x in all_events if x["visibility"] == "restricted" and x["output_refs"]]
        require(any(error_canary in canonical(value) for value in restricted_records), "PROTECTED_ORIGINAL_ERROR_NOT_RETAINED")
    expected_used = 2 if name == "protected_module_exception" else 3
    require(runner.calls == 3 and sum(x["execution_calls"] for x in runner.observations) == 3, "UNEXPECTED_TARGET_EXECUTIONS")
    require(summary["budget"]["used"]["execution_calls"] == expected_used, "PROTECTED_USAGE_ACCOUNTING_MISMATCH")
    require(summary["budget"]["reserved"]["execution_calls"] == (1 if name == "protected_module_exception" else 0),
            "PROTECTED_UNKNOWN_RESERVATION_MISMATCH")
    for observation in runner.observations:
        if expected_image:
            require(observation["image_digest"] == expected_image and observation["isolation_guarantees"]["container_cleanup_confirmed"],
                    "EXECUTION_IMAGE_OR_CLEANUP_MISMATCH")
    probes = None
    if name == "hidden_failure":
        probes = reject_public_probes(bridge, final_request, final_fact, final_ref)
        require(runner.calls == 3, "PUBLIC_PROBE_REEXECUTED_TARGET")
        for denial in probes["responses"]:
            require(not any(marker in canonical(denial) for marker in canaries), "REJECTION_ERROR_LEAK")
    raw = {"inputs": inputs, "transport_calls": calls, "receivers": {
        service: {"calls": observer.calls, "responses": observer.responses} for service, observer in bridge.observers.items()},
        "summary": summary, "public_values": public, "public_negative_probes": probes}
    (directory / "private-record.json").write_text(canonical(raw), encoding="utf-8")
    return {"name": name, "result": "passed", "terminal": summary["state"], "reason": summary["stop_reason"],
            "run_id": summary["run_id"], "trace_id": engine.trace_id, "physical_execution_calls": runner.calls,
            "ledger_execution_calls": expected_used, "reserved_execution_calls": summary["budget"]["reserved"]["execution_calls"],
            "repairs_before_seal": 1, "module_calls_after_final": 0, "public_canary_hits": 0,
            "a_received_calls": len(a_calls), "c_received_calls": len(c_calls), "public_diagnoses": len(diagnoses),
            "public_events_checked": event_count, "public_reachable_artifacts_checked": artifact_count,
            "public_negative_probes": probes["count"] if probes else 0,
            "source": "Real B/original O; A/C explicitly Mock; runtime-generated synthetic final tests",
            "fault_injection": name if name.startswith("protected_") else "none"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--config", type=Path, default=ROOT.parent / "docs/integration/config.b-local.p2.example.json")
    parser.add_argument("--manifest", type=Path, default=ROOT.parent / "docs/integration/p2_handoff_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "docs/verification/p2/protected_validation.json")
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker is required for the self-authored target fixtures")
    private = ROOT / ".interop/p2-protected" / uid("run")
    private.mkdir(parents=True)
    summary = {"verified_at": utcnow(), "result": "failed", "cases": [], "formal_p2_acceptance": "blocked", "o_receipt": "not_received",
               "scope": "B technical protected receiver-view verification", "actual_model_calls": 0,
               "raw_records": "Private python_service/.interop/p2-protected; not committed"}
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_bundle(config, manifest, ContractRegistry())
        def docker(*args):
            return subprocess.check_output(["docker", *args], text=True, timeout=15).strip()
        image = docker("image", "inspect", "--format", "{{.Id}}", manifest["image"]["configured_name"])
        require(image == manifest["image"]["expected_id"], "LOCKED_IMAGE_MISMATCH")
        baseline = set(docker("ps", "-aq", "--filter", "name=srp-b-execution-").split())
        overlay = {"driver": Path(__file__), "tests": ROOT / "tests/test_local_v2_p2_protected.py",
                   "bootstrap_driver": ROOT / "scripts/verify_p2_local.py", "boundary_driver": ROOT / "scripts/verify_p2_boundaries.py",
                   "config": args.config, "manifest": args.manifest}
        summary.update(implementation_version=manifest["implementation_version"], source_revision=manifest["source"]["revision"],
                       image_digest=image, public_contract_sha256=manifest["public_contract_sha256"], config_canonical_sha256=manifest["config_canonical_sha256"],
                       host_python=platform.python_version(), host_packages={x: importlib.metadata.version(x) for x in ("pytest", "pydantic", "jsonschema")},
                       framework_git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ContractRegistry().root.parent, text=True).strip(),
                       source_overlay="Uncommitted fixtures/tools; fixed 0.3.1 runtime and shared O/Mock/Schema/guards unchanged",
                       configuration_overrides={"B.options.state_dir": "Unique private directory per scenario", "O.output_dir": "Unique private directory per scenario",
                                                "transport.timeout_seconds": 60, "O.deadline_seconds": 180, "O.routing_mode": "adaptive_rag",
                                                "O.max_repairs": 2, "final_tests": "Runtime-generated self-authored private synthetic fixtures, not TEST-001 material"},
                       overlay_hashes={role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in overlay.items()},
                       overlay_files={role: path.name for role, path in overlay.items()})
        for name in SCENARIOS:
            active = deepcopy(config)
            active["timeout_seconds"] = 60
            active["modules"]["B"]["options"]["state_dir"] = str(private / name / "b")
            base = build_transport(active)
            runner = CountingRunner(base.modules["B"].runner)
            base.modules["B"].runner = runner
            result = run_scenario(base, runner, private / name, name, expected_image=image)
            summary["cases"].append(result)
            print("passed: " + name, flush=True)
        require(not set(docker("ps", "-aq", "--filter", "name=srp-b-execution-").split()) - baseline, "NEW_CONTAINER_REMAINS")
        summary.update(result="passed", physical_execution_calls=sum(x["physical_execution_calls"] for x in summary["cases"]),
                       public_canary_hits=0, no_new_remaining_containers=True)
    except Exception as error:
        summary["error_code"] = str(error) if isinstance(error, ValueError) and str(error).replace("_", "").isupper() else "PROTECTED_VERIFICATION_FAILED"
        (private / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    summary["unverified"] = ["Formal TEST-001 lock and actual A context/tokenizer metadata", "Consumer field review", "Independent O receipt", "Real A/C algorithms"]
    check_public(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"result": summary["result"], "cases": len(summary["cases"]), "formal_p2_acceptance": summary["formal_p2_acceptance"]}))
    return 0 if summary["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
