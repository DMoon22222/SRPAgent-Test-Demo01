"""B-owned P2 reference/accounting fixtures; shared O/transport/guards stay intact.

Original envelopes, logs and O journals remain private. Negative cases are
explicit injections, never production outcomes or formal O acceptance.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import traceback
from unittest.mock import patch

from reliable_codegen.artifact_access import ArtifactAccessDenied
from reliable_codegen.budget import BudgetLedger, BudgetExhausted
from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public, check_response
from reliable_codegen.mocks import create_mock_module
from reliable_codegen.orchestrator import Orchestrator, demo_inputs
from reliable_codegen.storage import ArtifactStore
from reliable_codegen.transport import LocalTransport, TransportError
from reliable_codegen.utils import canonical, digest, uid, utcnow
from srp_b.samples import diagnostic, request

if __package__:
    from .verify_p2_local import ROOT, STATIC, EXECUTE, DIAGNOSE, require, validate_bundle
else:
    from verify_p2_local import ROOT, STATIC, EXECUTE, DIAGNOSE, require, validate_bundle

REFERENCE_CASES = (
    "history_and_prior", "unlisted_reference", "wrong_reference_hash", "missing_reference",
    "wrong_reference_task", "wrong_history_run", "protected_reference", "resolver_body_hash", "resolver_identity",
    "exception_revocation", "log_reference", "log_hash_mismatch", "missing_log_reference",
)
BUDGET_CASES = ("zero_grant", "insufficient_budget", "invalid_budget_revision",
                "envelope_deadline", "grant_deadline", "budget_deadline", "wall_budget",
                "ledger_exhausted", "durable_replay")
O_CASES = ("pending_outcome", "late_result", "partial_diagnosis")


class CountingRunner:
    """Transparent B-owned observation hook; delegates to the original backend."""
    def __init__(self, backend):
        self.backend, self.calls, self.observations = backend, 0, []

    def execute(self, *args, **kwargs):
        self.calls += 1
        value = self.backend.execute(*args, **kwargs)
        self.observations.append(deepcopy(value))
        return value


class AlteredRecordResolver:
    """Explicit defective-resolver fixture, downstream of the real O resolver."""
    def __init__(self, resolver, fault):
        self.resolver, self.fault = resolver, fault

    def resolve(self, reference):
        record = self.resolver.resolve(reference)
        if self.fault == "resolver_body_hash":
            record["body_utf8"] += " "
        else:
            record["artifact_ref"]["artifact_id"] = "fixture-wrong-identity"
        return record


class ObservingModule:
    """Observe only the public binder/call boundary; inject named test faults."""
    def __init__(self, module, *, forbidden=None, fault=None):
        self.module, self.forbidden, self.fault = module, forbidden, fault
        self.resolver, self.saved, self.calls, self.responses = None, [], [], []
        self.denied_unlisted = False

    def capabilities(self):
        return self.module.capabilities()

    def bind_artifact_resolver(self, resolver):
        self.resolver = resolver
        if resolver is not None:
            self.saved.append(resolver)
        bound = AlteredRecordResolver(resolver, self.fault) if resolver is not None and self.fault in {"resolver_body_hash", "resolver_identity"} else resolver
        self.module.bind_artifact_resolver(bound)

    def call(self, operation, envelope):
        self.calls.append((operation, deepcopy(envelope)))
        if self.forbidden is not None:
            try:
                self.resolver.resolve(self.forbidden)
            except ArtifactAccessDenied:
                self.denied_unlisted = True
            else:
                raise AssertionError("UNLISTED_REFERENCE_WAS_READABLE")
            allowed = envelope["payload"]["history_view"]["source_refs"][0]
            record = self.resolver.resolve(allowed)
            before = deepcopy(record)
            record["body_utf8"] = "CALLER_MUTATION"
            require(self.resolver.resolve(allowed) == before, "RESOLVER_RECORD_WAS_SHARED")
        if self.fault == "pending_outcome" and operation == EXECUTE:
            # B-owned crash fixture: a durable pending row, no backend invocation.
            self.module.journal.begin(operation, envelope)
        if self.fault == "partial_diagnosis" and operation == DIAGNOSE:
            with patch("srp_b.module.diagnose", side_effect=RuntimeError("P2_PRIVATE_FAULT_DETAIL")):
                response = self.module.call(operation, envelope)
        else:
            response = self.module.call(operation, envelope)
        self.responses.append((operation, deepcopy(envelope), deepcopy(response)))
        if self.fault == "exception_revocation" and operation == DIAGNOSE:
            raise RuntimeError("P2_PRIVATE_FAULT_DETAIL")
        if self.fault == "late_result" and operation == EXECUTE:
            # Deterministic post-return timeout, without sleeping or changing facts.
            # The real shared LocalTransport will classify this as late.
            self.transport.timeout = 1e-12
        return response


def checked_call(transport, operation, envelope):
    before = deepcopy(envelope)
    response = transport.call("B", operation, envelope)
    registry = ContractRegistry()
    registry.validate_request(operation, envelope)
    registry.validate_response(operation, response)
    check_response(envelope, response)
    check_public(response)
    require(envelope == before, "REQUEST_MUTATED")
    return response


def revoked(observer, reference):
    require(observer.resolver is None, "RESOLVER_STILL_BOUND")
    for resolver in observer.saved:
        try:
            resolver.resolve(reference)
        except ArtifactAccessDenied:
            pass
        else:
            raise ValueError("RESOLVER_STILL_ACTIVE")


def result_record(name, group, runner, **details):
    return {"name": name, "group": group, "result": "passed",
            "backend_invocations": runner.calls,
            "physical_execution_calls": sum(x["execution_calls"] for x in runner.observations), **details}


def reference_case(make_module, directory, name):
    module, runner = make_module(directory / "b")
    store = ArtifactStore(directory / "o-store")
    observer = ObservingModule(module)
    transport = LocalTransport({"B": observer}, timeout=60)
    transport.bind_artifact_store(store)
    original = request(STATIC, source="def add(a,b)\n    return a+b\n", task_id=uid("task"), run_id=uid("run"))
    fact = checked_call(transport, STATIC, original)["payload"]["data"]
    prior_request = diagnostic(fact, original, static=True)
    prior = checked_call(transport, DIAGNOSE, prior_request)["payload"]["data"]["diagnosis_report"]
    code = deepcopy(original["payload"]["code_artifact"])
    ref = store.put(code, "CodeArtifact")
    current = diagnostic(fact, original, static=True)
    current["payload"]["history_view"]["source_refs"] = [ref]
    expected, status = None, "completed"
    injection = "none" if name == "history_and_prior" else "Declared B-owned reference/probe fixture"
    if name == "history_and_prior":
        current["payload"]["prior_diagnosis_ref"] = store.put(prior, "DiagnosisReport", prior["diagnosis_id"])
    elif name == "unlisted_reference":
        observer.forbidden = store.put({"task_id": "other-task"}, "Example")
    elif name == "wrong_reference_hash":
        current["payload"]["history_view"]["source_refs"][0] = {**ref, "sha256": "0" * 64}
        status, expected = "blocked", "AUTHORIZED_CONTEXT_UNAVAILABLE"
    elif name == "missing_reference":
        current["payload"]["history_view"]["source_refs"][0] = {**ref, "artifact_id": "not-registered"}
        status, expected = "blocked", "AUTHORIZED_CONTEXT_UNAVAILABLE"
    elif name == "wrong_reference_task":
        code["task_id"] = "other-task"
        current["payload"]["history_view"]["source_refs"] = [store.put(code, "CodeArtifact")]
        status, expected = "blocked", "AUTHORIZED_CONTEXT_UNAVAILABLE"
    elif name == "wrong_history_run":
        current["payload"]["history_view"]["run_id"] = "other-run"
        status, expected = "error", "INPUT_INVARIANT_VIOLATION"
    elif name == "protected_reference":
        current["payload"]["history_view"]["source_refs"] = [store.put({"protected_fixture": True}, "Example", visibility="restricted")]
        status, expected = "transport_error", "CONTRACT_INVALID"
    elif name == "exception_revocation":
        observer.fault = name
        status, expected = "transport_error", "MODULE_IMPLEMENTATION_ERROR"
    elif name in {"resolver_body_hash", "resolver_identity"}:
        observer.fault = name
        status, expected = "blocked", "AUTHORIZED_CONTEXT_UNAVAILABLE"
        injection = "Declared defective-resolver fixture after original O authorization"
    elif name.startswith("log_") or name == "missing_log_reference":
        # Log reference encoding is an explicit fixture. It is NOT presented as
        # the unchanged original Docker observation: assign a new fixture ID.
        original = request(EXECUTE, source="def add(a,b):\n    return a-b\n", task_id=uid("task"), run_id=uid("run"))
        observed = checked_call(transport, EXECUTE, original)["payload"]["data"]
        fact = deepcopy(observed)
        fact["execution_id"] = uid("fixture-execution")
        log_ref = store.put("AssertionError: P2 referenced log fixture", "Log")
        fact["stdout"] = {"content_ref": log_ref, "sha256": log_ref["sha256"], "truncated": False}
        if name == "log_hash_mismatch":
            fact["stdout"]["sha256"] = "0" * 64
            status, expected = "error", "INPUT_INVARIANT_VIOLATION"
        elif name == "missing_log_reference":
            fact["stdout"]["content_ref"] = {**log_ref, "artifact_id": "not-registered"}
            status, expected = "error", "INPUT_INVARIANT_VIOLATION"
        current = diagnostic(fact, original)
        injection = "Declared referenced-log fixture based on observed execution shape; new fixture execution_id"
        (directory / "original-log-observation.json").write_text(canonical(observed), encoding="utf-8")
    try:
        response = checked_call(transport, DIAGNOSE, current)
        outcome = response["payload"]
        require(outcome["status"] == status, "REFERENCE_OUTCOME_MISMATCH")
        actual = outcome["data"]["reason"] if status == "blocked" else outcome["error"]["error_code"] if status == "error" else None
        require(actual == expected, "REFERENCE_REASON_MISMATCH")
        if name == "history_and_prior":
            require(outcome["data"]["diagnosis_report"]["prior_diagnosis_id"] == prior["diagnosis_id"], "PRIOR_NOT_CONSUMED")
        if name == "log_reference":
            evidence = outcome["data"]["diagnosis_report"]["evidence_refs"]
            require(any(x["pointer"] == "/stdout" and "P2 referenced log fixture" in x["summary"] for x in evidence), "LOG_REF_NOT_CONSUMED")
        if name == "unlisted_reference":
            require(observer.denied_unlisted, "UNLISTED_PROBE_NOT_EXERCISED")
    except TransportError as error:
        require(status == "transport_error" and error.response["error"]["error_code"] == expected, "UNEXPECTED_REFERENCE_TRANSPORT_ERROR")
        require("P2_PRIVATE_FAULT_DETAIL" not in canonical(error.response), "PRIVATE_ERROR_LEAK")
        response = error.response
    revoked(observer, ref)
    (directory / "calls.json").write_text(canonical({"calls": observer.calls, "responses": observer.responses,
                                                     "last_request": current, "last_response": response}), encoding="utf-8")
    return result_record(name, "reference_lifecycle", runner, expected_status=status, reason=expected,
                         resolver_revoked=True, injection=injection)


def issue(ledger, operation):
    envelope = request(operation, task_id=uid("task"), run_id=uid("run"))
    context = {"reserved_output_tokens": 100, "max_input_tokens": 1000,
               "max_evidence_tokens": 100, "target_tokenizer_id": "p2-fixture-only"}
    envelope["payload"]["call_grant"] = ledger.issue(envelope["call_id"], operation, context)
    envelope["payload"]["budget"] = ledger.snapshot()
    envelope["deadline_at"] = ledger.deadline_at
    return envelope


def budget_case(make_module, directory, name):
    module, runner = make_module(directory / "b")
    transport = LocalTransport({"B": module}, timeout=60)
    ledger = BudgetLedger(seconds=120)
    envelope = issue(ledger, EXECUTE)
    payload = envelope["payload"]
    reason = None
    if name == "ledger_exhausted":
        limits = deepcopy(ledger.limits)
        limits["execution_calls"] = 0
        exhausted = BudgetLedger(limits=limits)
        try:
            issue(exhausted, EXECUTE)
        except BudgetExhausted as error:
            require(str(error) == "CALL_BUDGET_UNAVAILABLE", "WRONG_BUDGET_REFUSAL")
        else:
            raise ValueError("EXHAUSTED_LEDGER_ISSUED_GRANT")
        return result_record(name, "budget_replay_accounting", runner, reason="CALL_BUDGET_UNAVAILABLE",
                             injection="Declared zero execution budget fixture")
    if name == "zero_grant":
        payload["call_grant"]["max_execution_calls"] = 0
        reason = "EXECUTION_NOT_AUTHORIZED"
    elif name == "insufficient_budget":
        for key in ("limits", "reserved", "remaining"):
            payload["budget"][key]["execution_calls"] = 0
        reason = "GRANT_EXCEEDS_BUDGET"
    elif name == "invalid_budget_revision":
        payload["call_grant"]["budget_revision"] += 1
        reason = "GRANT_BUDGET_MISMATCH"
    elif name.endswith("_deadline"):
        target = envelope if name == "envelope_deadline" else payload["call_grant"] if name == "grant_deadline" else payload["budget"]
        target["deadline_at"] = "2000-01-01T00:00:00Z"
        reason = "DEADLINE_EXCEEDED"
        # Original LocalTransport rejects even before entering B.
        try:
            checked_call(transport, EXECUTE, envelope)
        except TransportError as error:
            require(error.response["error"]["error_code"] == reason, "WRONG_DEADLINE_REFUSAL")
        else:
            raise ValueError("EXPIRED_TRANSPORT_STARTED_WORK")
    elif name == "wall_budget":
        payload["budget"]["used"]["wall_time_ms"] = payload["budget"]["limits"]["wall_time_ms"]
        payload["budget"]["remaining"]["wall_time_ms"] = 0
        reason = "DEADLINE_EXCEEDED"
    if reason:
        # Also exercise B's public module boundary, independent of transport.
        response = module.call(EXECUTE, envelope)
        check_response(envelope, response)
        require(response["payload"]["status"] == "blocked" and response["payload"]["data"]["reason"] == reason,
                "B_BUDGET_REFUSAL_MISMATCH")
        require(runner.calls == response["payload"]["usage"]["execution_calls"] == 0, "UNAUTHORIZED_EXECUTION_STARTED")
        ledger.settle(envelope["call_id"], response["payload"]["usage"])
    else:
        response = checked_call(transport, EXECUTE, envelope)
        require(response["payload"]["status"] == "completed", "REPLAY_INITIAL_EXECUTION_FAILED")
        usage = response["payload"]["usage"]
        ledger.settle(envelope["call_id"], usage)
        again = checked_call(transport, EXECUTE, envelope)
        other, other_runner = make_module(directory / "b")
        durable = checked_call(LocalTransport({"B": other}, timeout=60), EXECUTE, envelope)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        with patch("reliable_codegen.transport.datetime", wraps=datetime) as clock:
            clock.now.return_value = future
            expired_cached = checked_call(transport, EXECUTE, envelope)
        with patch("srp_b.module.datetime", wraps=datetime) as clock:
            clock.now.return_value = future
            expired_durable = other.call(EXECUTE, envelope)
        for replay in (again, durable, expired_cached, expired_durable):
            require(replay == response and replay["payload"]["usage"]["execution_calls"] == 1, "REPLAY_RESPONSE_CHANGED")
            ledger.settle(envelope["call_id"], replay["payload"]["usage"])
        require(runner.calls == 1 and other_runner.calls == 0 and ledger.used["execution_calls"] == 1 and len(ledger.seen) == 1,
                "REPLAY_DOUBLE_EXECUTION_OR_SETTLEMENT")
        for target in (transport, module, other):
            changed = deepcopy(envelope)
            changed["extensions"] = {"p2_changed_body": True}
            try:
                target.call("B", EXECUTE, changed) if isinstance(target, LocalTransport) else target.call(EXECUTE, changed)
            except TransportError as error:
                require(error.response["error"]["error_code"] == "IDEMPOTENCY_CONFLICT", "WRONG_REPLAY_CONFLICT")
            else:
                raise ValueError("CHANGED_REPLAY_ACCEPTED")
        reused = deepcopy(envelope)
        reused["message_id"] = uid("msg")
        try:
            other.call(EXECUTE, reused)
        except TransportError as error:
            require(error.response["error"]["error_code"] == "CALL_GRANT_REUSED", "WRONG_GRANT_REUSE_ERROR")
        else:
            raise ValueError("REUSED_CALL_ID_ACCEPTED")
        altered_usage = deepcopy(usage)
        altered_usage["execution_calls"] = 0
        try:
            ledger.settle(envelope["call_id"], altered_usage)
        except ValueError as error:
            require("different content" in str(error), "WRONG_USAGE_CONFLICT")
        else:
            raise ValueError("ALTERED_USAGE_ACCEPTED")
        require(runner.calls == 1 and other_runner.calls == 0 and ledger.used["execution_calls"] == 1, "CONFLICT_STARTED_WORK")
    (directory / "record.json").write_text(canonical({"request": envelope, "response": response, "budget": ledger.snapshot()}), encoding="utf-8")
    return result_record(name, "budget_replay_accounting", runner, reason=reason, ledger_execution_calls=ledger.used["execution_calls"],
                         usage_id=response["payload"]["usage"]["usage_id"], completed_response_replay_count=4 if name == "durable_replay" else 0,
                         injection="Declared future-clock replay checks" if name == "durable_replay" else "Declared grant/deadline/budget fixture")


def o_case(make_module, directory, name):
    module, runner = make_module(directory / "b")
    observer = ObservingModule(module, fault=name)
    a_observer = ObservingModule(create_mock_module(service="A"))
    c_observer = ObservingModule(create_mock_module(service="C"))
    transport = LocalTransport({"B": observer, "A": a_observer, "C": c_observer}, timeout=60)
    observer.transport = transport
    engine = Orchestrator(transport, directory / "o", max_repairs=2, routing_mode="no_rag")
    summary = engine.run(**demo_inputs())
    require(summary["state"] == "human_review" and summary["iterations"] == 0, "FAULT_DID_NOT_STOP_RUN")
    require(not any(operation.endswith("/repair") for operation, _ in a_observer.calls), "FAULT_APPLIED_TO_REPAIR")
    require(not c_observer.calls, "FAULT_APPLIED_TO_RETRIEVAL")
    executions = [x for x in observer.responses if x[0] == EXECUTE]
    require(len(executions) == 1, "FAULT_AUTOMATICALLY_RETRIED")
    operation, envelope, response = executions[0]
    if name == "pending_outcome":
        require(summary["stop_reason"] == "USAGE_RECONCILIATION_REQUIRED" and len(summary["unknown_usage_ids"]) == 1,
                "UNKNOWN_NOT_RETAINED")
        require(summary["budget"]["reserved"]["execution_calls"] == 1 and runner.calls == 0, "UNKNOWN_RESERVATION_RELEASED")
        before_seen = len(engine.budget.seen)
        for replay_transport in (transport, LocalTransport({"B": module})):
            replay = checked_call(replay_transport, EXECUTE, envelope)
            require(replay["payload"]["error"]["error_code"] == "OUTCOME_UNKNOWN" and replay["payload"]["usage"]["execution_calls"] is None,
                    "PENDING_REPLAY_BECAME_KNOWN")
        engine.budget.settle(envelope["call_id"], response["payload"]["usage"])
        require(len(engine.budget.seen) == before_seen and runner.calls == 0, "UNKNOWN_REPLAY_REEXECUTED")
        require(engine.budget.snapshot()["reserved"]["execution_calls"] == 1, "UNKNOWN_REPLAY_RELEASED_RESERVATION")
    elif name == "late_result":
        require(summary["stop_reason"] == "LATE_RESULT_NOT_APPLIED" and runner.calls == 1, "LATE_RESULT_RETRIED")
        require(summary["budget"]["used"]["execution_calls"] == 1 and not summary["unknown_usage_ids"], "LATE_USAGE_LOST")
        events = engine.store.events(summary["run_id"])
        failures = [engine.store.get(x["output_refs"][0]) for x in events if x["payload_type"] == "TransportFailure"]
        require(any(x["response"] == response for x in failures), "LATE_FACT_NOT_RETAINED")
        try:
            transport.call("B", EXECUTE, envelope)
        except TransportError as error:
            require(str(error) == "LATE_RESULT_NOT_APPLIED" and error.response == response, "LATE_REPLAY_CHANGED")
        else:
            raise ValueError("LATE_REPLAY_APPLIED")
    else:
        require(summary["stop_reason"] == "DIAGNOSIS_FAILED" and runner.calls == 1, "PARTIAL_REEXECUTED")
        diagnosis = next(x[2] for x in observer.responses if x[0] == DIAGNOSE)
        partial = diagnosis["payload"]["error"]["partial_result_ref"]
        require(engine.store.get(partial) == response["payload"]["data"], "PARTIAL_FACT_NOT_RESOLVABLE_BY_O")
        require(diagnosis["payload"]["usage"]["execution_calls"] == 0, "PARTIAL_DIAGNOSIS_EXECUTED")
        require("P2_PRIVATE_FAULT_DETAIL" not in canonical(summary), "PARTIAL_PRIVATE_ERROR_LEAK")
    require(runner.calls == (0 if name == "pending_outcome" else 1), "FAULT_EXTRA_BACKEND_INVOCATION")
    revoked(observer, {"artifact_id": "unused"})
    (directory / "calls.json").write_text(canonical({"calls": observer.calls, "responses": observer.responses,
                                                     "a_calls": a_observer.calls, "c_calls": c_observer.calls, "summary": summary}), encoding="utf-8")
    return result_record(name, "unknown_late_partial", runner, terminal=summary["state"], reason=summary["stop_reason"],
                         ledger_execution_calls=summary["budget"]["used"]["execution_calls"],
                         reserved_execution_calls=summary["budget"]["reserved"]["execution_calls"],
                         unknown_usage_count=len(summary["unknown_usage_ids"]), injection="Declared B-owned " + name + " fixture")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--config", type=Path, default=ROOT.parent / "docs/integration/config.b-local.p2.example.json")
    parser.add_argument("--manifest", type=Path, default=ROOT.parent / "docs/integration/p2_handoff_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "docs/verification/p2/boundaries_validation.json")
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker is required to run the fixed self-authored target fixtures")
    from reliable_codegen.transport import build_transport
    private = ROOT / ".interop/p2-boundaries" / uid("run")
    private.mkdir(parents=True)
    summary = {"verified_at": utcnow(), "result": "failed", "cases": [], "formal_p2_acceptance": "blocked", "o_receipt": "not_received",
               "scope": "B technical reference, budget/replay and unknown/late/partial joint verification", "model_calls": 0,
               "raw_records": "Private python_service/.interop/p2-boundaries directory; not committed"}
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_bundle(config, manifest, ContractRegistry())
        def docker(*args):
            return subprocess.check_output(["docker", *args], text=True, timeout=15).strip()
        image = docker("image", "inspect", "--format", "{{.Id}}", manifest["image"]["configured_name"])
        require(image == manifest["image"]["expected_id"], "LOCKED_IMAGE_MISMATCH")
        baseline = set(docker("ps", "-aq", "--filter", "name=srp-b-execution-").split())
        runners = []
        def make_module(directory):
            active = deepcopy(config)
            active["modules"]["B"]["options"]["state_dir"] = str(directory)
            module = build_transport(active).modules["B"]
            counter = CountingRunner(module.runner)
            module.runner = counter
            runners.append(counter)
            return module, counter
        overlay = {"driver": Path(__file__), "tests": ROOT / "tests/test_local_v2_p2_boundaries.py",
                   "bootstrap_driver": ROOT / "scripts/verify_p2_local.py", "config": args.config, "manifest": args.manifest}
        summary.update(implementation_version=manifest["implementation_version"], source_revision=manifest["source"]["revision"],
                       image_digest=image, public_contract_sha256=manifest["public_contract_sha256"],
                       config_canonical_sha256=manifest["config_canonical_sha256"], docker_engine=docker("version", "--format", "{{.Server.Version}}"),
                       host_python=platform.python_version(),
                       host_packages={name: importlib.metadata.version(name) for name in ("pytest", "pydantic", "jsonschema")},
                       framework_git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ContractRegistry().root.parent, text=True).strip(),
                       configuration_overrides={"B.options.state_dir": "Unique private fixture directory; same directory only for durable replay",
                                                "transport.timeout_seconds": "60; late fixture explicitly reduces timeout after B returns",
                                                "O.routing_mode": "no_rag", "O.max_repairs": 2, "O.output_dir": "Unique private fixture directory",
                                                "O.A_and_C": "Original declared Mock factories; no real model calls",
                                                "budget_context": "Explicit fixture values; not actual A tokenizer/context metadata"},
                       overlay_hashes={role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in overlay.items()},
                       overlay_files={role: path.name for role, path in overlay.items()},
                       source_overlay="Uncommitted B-owned test fixtures; fixed 0.3.1 runtime and shared framework unchanged")
        for names, function in ((REFERENCE_CASES, reference_case), (BUDGET_CASES, budget_case), (O_CASES, o_case)):
            for name in names:
                record = function(make_module, private / name, name)
                summary["cases"].append(record)
                print("passed: " + name, flush=True)
        observations = [x for r in runners for x in r.observations]
        require(all(x["image_digest"] == image and x["actual_runtime"] == manifest["image"]["expected_runtime"]
                    and x["isolation_guarantees"]["container_cleanup_confirmed"] for x in observations), "EXECUTION_ENVIRONMENT_OR_CLEANUP_MISMATCH")
        require(not set(docker("ps", "-aq", "--filter", "name=srp-b-execution-").split()) - baseline, "VERIFICATION_CONTAINER_REMAINS")
        summary.update(result="passed", backend_invocations=sum(r.calls for r in runners),
                       physical_execution_calls=sum(x["execution_calls"] for x in observations),
                       no_new_remaining_containers=True, actual_runtimes=[x["actual_runtime"] for x in observations])
    except Exception as error:
        summary["error_code"] = str(error) if isinstance(error, ValueError) and str(error).replace("_", "").isupper() else "BOUNDARY_VERIFICATION_FAILED"
        (private / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    summary["unverified"] = ["Full protected receiver-view matrix", "Formal TEST-001 lock and target A metadata", "Independent O receipt", "Real A/C algorithms"]
    check_public(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"result": summary["result"], "cases": len(summary["cases"]), "formal_p2_acceptance": summary["formal_p2_acceptance"]}))
    return 0 if summary["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
