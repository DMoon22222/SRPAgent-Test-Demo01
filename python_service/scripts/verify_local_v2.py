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

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public, check_response
from reliable_codegen.mocks import create_mock_module
from reliable_codegen.orchestrator import Orchestrator, demo_inputs
from reliable_codegen.transport import LocalTransport, TransportError
from reliable_codegen.utils import canonical, digest, uid, utcnow

from srp_b import __version__, create_module
from srp_b.module import DIAGNOSE, EXECUTE, STATIC
from srp_b.samples import diagnostic, request


def source_metadata(root, registry):
    source_files = sorted((root / "srp_b").glob("*.py")) + [root / p for p in (
        "app/analyzer/error_signal_extractor.py", "app/schemas.py", "pyproject.toml",
        "requirements-local-v2.lock", "scripts/verify_local_v2.py")]
    return {
        "contract_sha256": hashlib.sha256((registry.root / "openapi_v0.2.json").read_bytes()).hexdigest(),
        "source_hashes": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "metadata_hash_algorithm": "SHA-256 of original file bytes, without newline conversion",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="Authorize the self-authored target fixtures in Docker")
    parser.add_argument("--image", default="srp-b-python:0.3.0")
    parser.add_argument("--output", required=True)
    parser.add_argument("--public-samples")
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker is required; this verifier executes its fixed synthetic fixtures")
    registry = ContractRegistry()
    root = Path(__file__).resolve().parents[1]
    local = root / ".interop" / "validation" / uid("run")
    local.mkdir(parents=True)
    checks, samples = [], []
    module = create_module(state_dir=str(local / "b-state"), image=args.image)

    def passed(name, **details):
        checks.append({"name": name, "result": "passed", **details})
        print("passed: " + name, flush=True)

    def invoke(operation, envelope, *, export=False):
        response = module.call(operation, envelope)
        registry.validate_response(operation, response)
        check_response(envelope, response)
        assert response["payload"]["status"] == "completed", response["payload"]["status"]
        if export:
            check_public(envelope)
            check_public(response)
            samples.append({"operation": operation, "request": envelope, "response": response})
        return response

    registry.validate("CapabilityDescriptor", module.capabilities())
    passed("capabilities")

    static_request = request(STATIC, source="def add(a, b)\n    return a + b\n", task_id="verify-static", run_id="verify-static-run")
    static = invoke(STATIC, static_request, export=True)["payload"]["data"]
    assert static["status"] == "failed"
    static_diagnosis = invoke(DIAGNOSE, diagnostic(static, static_request, static=True), export=True)
    assert static_diagnosis["payload"]["data"]["diagnosis_report"]["execution_result_id"] is None
    assert static_diagnosis["payload"]["usage"]["execution_calls"] == 0
    passed("real_static_failure_and_static_feedback")

    failed_request = request(EXECUTE, source="def add(a,b):\n    return a-b\n", task_id="verify-failure", run_id="verify-failure-run")
    failed_response = invoke(EXECUTE, failed_request, export=True)
    failed = failed_response["payload"]["data"]
    assert failed["test_outcome"] == "failed" and failed["test_case_results"]
    diagnosis = invoke(DIAGNOSE, diagnostic(failed, failed_request), export=True)
    assert diagnosis["payload"]["data"]["failure_source"]["execution_result"] == failed
    assert diagnosis["payload"]["usage"]["execution_calls"] == 0
    passed("real_public_failure_and_feedback_only")

    restarted = create_module(state_dir=str(local / "b-state"), image=args.image)
    assert restarted.call(EXECUTE, failed_request) == failed_response
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
    passing = invoke(EXECUTE, passing_request, export=True)["payload"]["data"]
    assert passing["test_outcome"] == "passed" and passing["tests_total"] > 0
    context = passing["execution_context"]
    assert context["actual_runtime"]["version"].startswith("3.11.")
    assert context["isolation_guarantees"]["container_cleanup_confirmed"]
    passed("real_success_and_observed_environment", runtime=context["actual_runtime"], image_digest=context["image_digest"])

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
    passed("real_final_acceptance_and_public_diagnosis_rejection")

    final_failure = request(EXECUTE, source="def add(a,b):\n    return a+b if a else 0\n",
                            tests="from src.main import add\n\ndef test_final_boundary():\n    assert add(0, 5) == 5\n",
                            task_id="verify-protected-failure", run_id="verify-protected-failure-run")
    final_failure["visibility"] = "restricted"
    final_failure["payload"]["purpose"] = "final_acceptance"
    final_failure["payload"]["test_artifact"]["kind"] = "final_hidden"
    final_failed = invoke(EXECUTE, final_failure)["payload"]["data"]
    assert final_failed["test_outcome"] == "failed" and final_failed["visibility"] == "restricted"
    passed("real_final_acceptance_failure_kept_restricted")

    timed = request(EXECUTE, source="def add(a,b):\n    while True:\n        pass\n", task_id="verify-timeout", run_id="verify-timeout-run")
    timed["payload"]["execution_policy"]["timeout_ms"] = 1000
    timed_fact = invoke(EXECUTE, timed)["payload"]["data"]
    assert timed_fact["execution_status"] == "timeout"
    assert timed_fact["execution_context"]["isolation_guarantees"]["container_cleanup_confirmed"]
    passed("real_timeout_and_container_cleanup")

    oom = request(EXECUTE, source="def add(a,b):\n    return bytearray(512 * 1024 * 1024)\n",
                  task_id="verify-oom", run_id="verify-oom-run")
    oom["payload"]["execution_policy"].update(memory_mb=64, timeout_ms=10000)
    oom_fact = invoke(EXECUTE, oom)["payload"]["data"]
    assert oom_fact["execution_status"] == "oom" and oom_fact["termination_reason"] == "oom"
    assert oom_fact["execution_context"]["isolation_guarantees"]["container_cleanup_confirmed"]
    passed("real_oom_distinguished_from_code_failure")

    signal_request = request(EXECUTE, source="import os, signal\n\ndef add(a,b):\n    os.kill(os.getpid(), signal.SIGTERM)\n",
                             task_id="verify-signal", run_id="verify-signal-run")
    signal_fact = invoke(EXECUTE, signal_request)["payload"]["data"]
    assert signal_fact["termination_reason"] == "signal" and signal_fact["signal"] == "15"
    passed("real_signal_termination")

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
    passed("real_readonly_source_write_scope_nonroot_and_network_namespace")

    mismatch = request(EXECUTE, task_id="verify-runtime", run_id="verify-runtime-run")
    mismatch["payload"]["build_manifest"]["runtime"]["version"] = "3.99"
    mismatch_response = invoke(EXECUTE, mismatch)
    assert mismatch_response["payload"]["data"]["execution_status"] == "infrastructure_error"
    assert mismatch_response["payload"]["usage"]["execution_calls"] == 0
    passed("observed_runtime_mismatch_rejected_without_target_execution")

    no_execution = request(EXECUTE, task_id="verify-budget", run_id="verify-budget-run")
    no_execution["payload"]["call_grant"]["max_execution_calls"] = 0
    rejected = module.call(EXECUTE, no_execution)["payload"]
    assert rejected["status"] == "blocked" and rejected["usage"]["execution_calls"] == 0
    passed("execution_grant_enforced")

    # This is explicitly a mixed validation. A and C remain deterministic mocks.
    transport = LocalTransport({"A": create_mock_module(service="A"), "B": create_module(
        state_dir=str(local / "mixed-b-state"), image=args.image), "C": create_mock_module(service="C")}, timeout=15)
    orchestrator = Orchestrator(transport, local / "mixed-o-run", routing_mode="no_rag")
    mixed = orchestrator.run(**demo_inputs())
    assert mixed["state"] == "accepted", mixed.get("stop_reason")
    passed("local_o_with_real_b_and_mock_a_c", terminal=mixed["state"], evidence_kind="mixed", routing_mode="no_rag")

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
        "resource_measurement_limit": "CPU time and peak memory are unknown; host wall time is observed",
        "image_build_note": "Local validation image uses an existing Python 3.11.5 base plus fixed offline pytest wheels; deployment Dockerfile uses python:3.11-slim. No benchmark score is claimed.",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if args.public_samples:
        Path(args.public_samples).parent.mkdir(parents=True, exist_ok=True)
        Path(args.public_samples).write_text(json.dumps({"kind": "public_synthetic_samples", "samples": samples}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"result": "passed", "checks": len(checks), "summary": args.output}))


if __name__ == "__main__":
    main()
