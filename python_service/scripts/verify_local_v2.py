"""Opt-in real Docker verification using public, self-authored synthetic tasks.

Raw local journals and O runs stay under .interop/. Only a redacted summary
and explicitly public samples may be exported to the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_response
from reliable_codegen.orchestrator import Orchestrator, demo_inputs
from reliable_codegen.storage import ArtifactStore
from reliable_codegen.transport import TransportError, build_transport
from reliable_codegen.utils import canonical, digest, uid, utcnow

from srp_b import __version__, create_module
from srp_b.module import DIAGNOSE, EXECUTE, STATIC
from srp_b.samples import diagnostic, request, sample_request
from check_local_v2 import PROTECTED_PATCHES, check_diagnostic_evidence, check_sample


def source_metadata(root, registry):
    source_files = sorted((root / "srp_b").glob("*.py")) + [root / p for p in (
        "app/analyzer/error_signal_extractor.py", "app/schemas.py", "pyproject.toml",
        "requirements-local-v2.lock", "scripts/verify_local_v2.py", "scripts/check_local_v2.py",
        "scripts/run_local_v2_tests.py", "tests/test_local_v2.py", "tests/test_local_v2_samples.py")]
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    repository = root.parent
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repository, text=True).strip()
    return {
        "contract_sha256": hashlib.sha256((registry.root / "openapi_v0.2.json").read_bytes()).hexdigest(),
        "git_base_commit": git("rev-parse", "HEAD"), "git_branch": git("branch", "--show-current"),
        "source_state": "Uncommitted candidate; source_hashes identify the verified workspace files",
        "source_hashes": hashes, "source_snapshot_sha256": digest(canonical(hashes)),
        "metadata_hash_algorithm": "SHA-256 of original file bytes, without newline conversion",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="Authorize the self-authored target fixtures in Docker")
    parser.add_argument("--image", default="srp-b-python:0.3.0")
    parser.add_argument("--output", required=True)
    parser.add_argument("--public-samples")
    parser.add_argument("--framework-config", type=Path, help="Shared O config selecting the real B public factory")
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker is required; this verifier executes its fixed synthetic fixtures")
    registry = ContractRegistry()
    root = Path(__file__).resolve().parents[1]
    local = root / ".interop" / "validation" / uid("run")
    local.mkdir(parents=True)
    checks, samples, invocations = [], [], []
    module = create_module(state_dir=str(local / "b-state"), image=args.image)

    def passed(name, **details):
        checks.append({"name": name, "result": "passed", "evidence_kind": "real_adapter", **details})
        print("passed: " + name, flush=True)

    def export_sample(name, operation, envelope, response, kind="real_docker", **details):
        expected = {"response_kind": "business", "status": response["payload"]["status"]} if "payload" in response else {
            "response_kind": "transport_error", "error_code": response["error"]["error_code"]}
        if "payload" in response:
            payload = response["payload"]
            expected["execution_calls"] = payload["usage"]["execution_calls"]
            if payload["status"] == "blocked":
                expected["reason"] = payload["data"]["reason"]
            elif payload["status"] == "error":
                expected["error_code"] = payload["error"]["error_code"]
            elif operation == EXECUTE:
                expected["execution_status"] = payload["data"]["execution_status"]
        sample = {"sample_id": name, "scenario": name.replace("_", " "), "evidence_kind": kind,
                  "operation": operation, "request": deepcopy(envelope), "response": deepcopy(response),
                  "expected": expected, **details}
        sample["observed_request_sha256"] = digest(canonical(sample_request(sample)))
        check_sample(sample, registry)
        samples.append(sample)

    def invoke(operation, envelope, *, export=None, kind="real_docker"):
        response = module.call(operation, envelope)
        registry.validate_response(operation, response)
        check_response(envelope, response)
        assert response["payload"]["status"] == "completed", response["payload"]["status"]
        invocations.append({**{key: envelope[key] for key in ("task_id", "run_id", "trace_id", "call_id", "attempt_id")},
                            "operation": operation, "request_sha256": digest(canonical(envelope)),
                            "execution_id": response["payload"]["data"].get("execution_id"),
                            "execution_calls": response["payload"]["usage"]["execution_calls"],
                            "code_hash": envelope["payload"]["code_artifact"]["content_hash"]})
        if operation == DIAGNOSE:
            check_diagnostic_evidence(response["payload"]["data"])
        if export:
            export_sample(export, operation, envelope, response, kind)
        return response

    registry.validate("CapabilityDescriptor", module.capabilities())
    passed("capabilities")

    static_request = request(STATIC, source="def add(a, b)\n    return a + b\n", task_id="verify-static", run_id="verify-static-run")
    static = invoke(STATIC, static_request, export="static_failure", kind="real_static")["payload"]["data"]
    assert static["status"] == "failed"
    static_diagnosis = invoke(DIAGNOSE, diagnostic(static, static_request, static=True), export="static_diagnosis", kind="real_rules")
    assert static_diagnosis["payload"]["data"]["diagnosis_report"]["execution_result_id"] is None
    assert static_diagnosis["payload"]["usage"]["execution_calls"] == 0
    passed("real_static_failure_and_static_feedback", evidence_kind="real_static_and_rules")

    failed_request = request(EXECUTE, source="def add(a,b):\n    return a-b\n", task_id="verify-failure", run_id="verify-failure-run")
    failed_response = invoke(EXECUTE, failed_request, export="execution_failure")
    failed = failed_response["payload"]["data"]
    assert failed["test_outcome"] == "failed" and failed["test_case_results"]
    diagnosis = invoke(DIAGNOSE, diagnostic(failed, failed_request), export="execution_diagnosis", kind="real_rules")
    assert diagnosis["payload"]["data"]["failure_source"]["execution_result"] == failed
    assert diagnosis["payload"]["usage"]["execution_calls"] == 0
    passed("real_public_failure_and_feedback_only", evidence_kind="real_docker_and_rules")

    restarted = create_module(state_dir=str(local / "b-state"), image=args.image)
    replay = restarted.call(EXECUTE, failed_request)
    assert replay == failed_response
    export_sample("completed_replay", EXECUTE, failed_request, replay, "real_adapter_replay", replay_of="execution_failure")
    changed = deepcopy(failed_request)
    changed["extensions"] = {"changed": True}
    try:
        restarted.call(EXECUTE, changed)
    except TransportError as error:
        assert str(error) == "IDEMPOTENCY_CONFLICT"
    else:
        raise AssertionError("Changed content was replayed")
    passed("durable_replay_and_conflict")

    passing_request = request(EXECUTE, task_id="verify-success", run_id="verify-success-run")
    passing = invoke(EXECUTE, passing_request, export="execution_success")["payload"]["data"]
    assert passing["test_outcome"] == "passed" and passing["tests_total"] > 0
    context = passing["execution_context"]
    assert context["actual_runtime"]["version"].startswith("3.11.")
    assert context["isolation_guarantees"]["container_cleanup_confirmed"]
    passed("real_success_and_observed_environment", evidence_kind="real_docker", runtime=context["actual_runtime"], image_digest=context["image_digest"])

    hidden = request(EXECUTE, task_id="verify-protected", run_id="verify-protected-run")
    hidden["visibility"] = "restricted"
    hidden["payload"]["purpose"] = "final_acceptance"
    hidden["payload"]["test_artifact"]["kind"] = "final_hidden"
    protected_fact = invoke(EXECUTE, hidden)["payload"]["data"]
    assert protected_fact["test_outcome"] == "passed"
    try:
        module.call(DIAGNOSE, diagnostic(protected_fact, hidden))
    except TransportError as error:
        assert error.response["error"]["details"] == {}
    else:
        raise AssertionError("Protected feedback entered public diagnosis")
    passed("real_final_acceptance_and_public_diagnosis_rejection", evidence_kind="real_docker_and_rejection")

    final_failure = request(EXECUTE, source="def add(a,b):\n    return a+b if a else 0\n",
                            tests="from src.main import add\n\ndef test_final_boundary():\n    assert add(0, 5) == 5\n",
                            task_id="verify-protected-failure", run_id="verify-protected-failure-run")
    final_failure["visibility"] = "restricted"
    final_failure["payload"]["purpose"] = "final_acceptance"
    final_failure["payload"]["test_artifact"]["kind"] = "final_hidden"
    final_failed = invoke(EXECUTE, final_failure)["payload"]["data"]
    assert final_failed["test_outcome"] == "failed" and final_failed["visibility"] == "restricted"
    passed("real_final_acceptance_failure_kept_restricted", evidence_kind="real_docker")

    timed = request(EXECUTE, source="def add(a,b):\n    while True:\n        pass\n", task_id="verify-timeout", run_id="verify-timeout-run")
    timed["payload"]["execution_policy"]["timeout_ms"] = 1000
    timed_fact = invoke(EXECUTE, timed, export="timeout")["payload"]["data"]
    assert timed_fact["execution_status"] == "timeout"
    assert timed_fact["execution_context"]["isolation_guarantees"]["container_cleanup_confirmed"]
    passed("real_timeout_and_container_cleanup", evidence_kind="real_docker")

    oom = request(EXECUTE, source="def add(a,b):\n    return bytearray(512 * 1024 * 1024)\n",
                  task_id="verify-oom", run_id="verify-oom-run")
    oom["payload"]["execution_policy"].update(memory_mb=64, timeout_ms=10000)
    oom_fact = invoke(EXECUTE, oom)["payload"]["data"]
    assert oom_fact["execution_status"] == "oom" and oom_fact["termination_reason"] == "oom"
    assert oom_fact["execution_context"]["isolation_guarantees"]["container_cleanup_confirmed"]
    passed("real_oom_distinguished_from_code_failure", evidence_kind="real_docker")

    signal_request = request(EXECUTE, source="import os, signal\n\ndef add(a,b):\n    os.kill(os.getpid(), signal.SIGTERM)\n",
                             task_id="verify-signal", run_id="verify-signal-run")
    signal_fact = invoke(EXECUTE, signal_request)["payload"]["data"]
    assert signal_fact["termination_reason"] == "signal" and signal_fact["signal"] == "15"
    passed("real_signal_termination", evidence_kind="real_docker")

    isolation_test = '''import os
from pathlib import Path

def test_isolation():
    assert os.getuid() != 0
    source = Path("/workspace/src/main.py")
    original = source.read_text()
    try:
        source.write_text("changed")
    except OSError:
        pass
    else:
        raise AssertionError("source is writable")
    assert source.read_text() == original
    Path("/workspace/tmp/allowed.txt").write_text("ok")
    assert Path("/workspace/tmp/allowed.txt").read_text() == "ok"
    assert Path("/sys/class/net/lo").exists()
    assert sorted(p.name for p in Path("/sys/class/net").iterdir()) == ["lo"]
'''
    isolation_request = request(EXECUTE, tests=isolation_test, task_id="verify-isolation", run_id="verify-isolation-run")
    isolation = invoke(EXECUTE, isolation_request)["payload"]["data"]
    assert isolation["test_outcome"] == "passed"
    passed("real_readonly_source_write_scope_nonroot_and_network_namespace", evidence_kind="real_docker")

    mismatch = request(EXECUTE, task_id="verify-runtime", run_id="verify-runtime-run")
    mismatch["payload"]["build_manifest"]["runtime"]["version"] = "3.99"
    mismatch_response = invoke(EXECUTE, mismatch, export="environment_failure", kind="real_docker_environment_probe")
    assert mismatch_response["payload"]["data"]["execution_status"] == "infrastructure_error"
    assert mismatch_response["payload"]["usage"]["execution_calls"] == 0
    passed("observed_runtime_mismatch_rejected_without_target_execution", evidence_kind="real_docker_environment_probe")

    no_execution = request(EXECUTE, task_id="verify-budget", run_id="verify-budget-run")
    no_execution["payload"]["call_grant"]["max_execution_calls"] = 0
    rejected_response = module.call(EXECUTE, no_execution)
    rejected = rejected_response["payload"]
    assert rejected["status"] == "blocked" and rejected["usage"]["execution_calls"] == 0
    export_sample("execution_not_authorized", EXECUTE, no_execution, rejected_response, "fault_injection")
    passed("execution_grant_enforced", evidence_kind="fault_injection")

    # Export only public inputs and scalar patches, never a protected fact body.
    base = diagnostic(failed, failed_request)
    protected_sample = {"request": base, "request_patches": PROTECTED_PATCHES}
    try:
        module.call(DIAGNOSE, sample_request(protected_sample))
    except TransportError as error:
        export_sample("protected_diagnosis_rejected", DIAGNOSE, base, error.response, "fault_injection",
                      request_patches=PROTECTED_PATCHES,
                      request_encoding="public_base_plus_scalar_patches; reconstructed input is intentionally invalid")
    else:
        raise AssertionError("Protected synthetic feedback was accepted")
    passed("public_synthetic_protected_diagnosis_rejection_sample", evidence_kind="fault_injection")

    store = ArtifactStore(local / "partial-fact-store")
    store.put(failed, "ExecutionResult", failed["execution_id"])
    diagnosis_request = diagnostic(failed, failed_request)
    with patch("srp_b.module.diagnose", side_effect=RuntimeError("synthetic diagnosis fault")):
        failed_diagnosis = module.call(DIAGNOSE, diagnosis_request)
    error = failed_diagnosis["payload"]["error"]
    assert error["error_code"] == "DIAGNOSIS_FAILED"
    assert store.get(error["partial_result_ref"]) == failed
    assert module.resolve_fact(error["partial_result_ref"])["body_utf8"] == canonical(failed)
    assert failed_diagnosis["payload"]["usage"]["execution_calls"] == 0
    export_sample("diagnosis_failure_retains_fact", DIAGNOSE, diagnosis_request, failed_diagnosis,
                  "fault_injection", partial_result_resolved=True)
    passed("injected_diagnosis_failure_preserves_real_execution_fact", evidence_kind="fault_injection")

    # This is explicitly a mixed validation. A and C remain deterministic mocks.
    config_path = (args.framework_config or registry.root.parent / "config.b-local.example.json").resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["modules"]["B"]["factory"] == "srp_b:create_module"
    config_hash = digest(canonical(config))
    config["modules"]["B"]["options"].update(state_dir=str(local / "mixed-b-state"), image=args.image)
    transport = build_transport(config, registry)
    assert transport.capabilities("B")["extensions"]["srp_b"]["implementation_version"] == __version__
    assert all(transport.capabilities(name)["extensions"].get("mock") for name in ("A", "C"))
    orchestrator = Orchestrator(transport, local / "mixed-o-run", routing_mode=config["routing_mode"], max_repairs=config["max_repairs"])
    mixed = orchestrator.run(**demo_inputs())
    assert mixed["state"] == "accepted", mixed.get("stop_reason")
    passed("local_o_with_real_b_and_mock_a_c", terminal=mixed["state"], evidence_kind="mixed",
           routing_mode=config["routing_mode"], config_file=config_path.name, config_sha256=config_hash,
           factories={name: entry["factory"] for name, entry in config["modules"].items()},
           overrides=["B.options.state_dir (private run directory)", "B.options.image (explicit verifier selection)"],
           o_signoff="not_received", run_id=mixed["run_id"], trace_id=orchestrator.trace_id,
           iterations=mixed["iterations"], unknown_usage_ids=mixed["unknown_usage_ids"])

    remaining = subprocess.check_output(["docker", "ps", "-aq", "--filter", "name=srp-b-execution-"], text=True).strip()
    assert not remaining, "Verification containers remain"
    passed("no_remaining_verification_containers")

    summary = {
        "verified_at": utcnow(), "result": "passed", "implementation_version": __version__,
        "scope": "Synthetic real B Docker verification plus mixed O/A-Mock/B-real/C-Mock local flow",
        "model_calls": 0, "a_c_real_modules_validated": False,
        **source_metadata(root, registry),
        "host_python": platform.python_version(),
        "host_packages": {name: importlib.metadata.version(name) for name in ("pydantic", "jsonschema", "pytest")},
        "image_digest": context["image_digest"], "actual_runtime": context["actual_runtime"],
        "package_versions": context["package_versions"],
        "checks": checks, "raw_records": "Private .interop/validation directory; not committed",
        "invocations": invocations, "configured_image": args.image,
        "framework_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=registry.root.parent, text=True).strip(),
        "unverified": ["Real A/C modules and full ABC chain", "O group formal receipt", "Algorithm benefit experiments", "CPU time and peak memory"],
        "resource_measurement_limit": "CPU time and peak memory are unknown; host wall time is observed",
        "image_build_note": "This run uses an existing local image, identified by the observed immutable ID and runtime. The deployment Dockerfile uses python:3.11-slim; no benchmark score is claimed.",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if args.public_samples:
        Path(args.public_samples).parent.mkdir(parents=True, exist_ok=True)
        Path(args.public_samples).write_text(json.dumps({"kind": "public_synthetic_samples", "verified_at": summary["verified_at"],
            "source_snapshot_sha256": summary["source_snapshot_sha256"], "samples": samples}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"result": "passed", "checks": len(checks), "summary": args.output}))


if __name__ == "__main__":
    main()
