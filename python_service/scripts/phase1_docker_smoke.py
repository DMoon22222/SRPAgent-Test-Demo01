"""B-only phase-1 resource/traceback checks using existing policy and image."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import tempfile
from pathlib import Path
from time import monotonic

from pre_integration_docker_smoke import SCENARIOS, TrackingRunner, docker
from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_response
from reliable_codegen.utils import utcnow

from srp_b import __version__, create_module
from srp_b.module import DIAGNOSE, EXECUTE
from srp_b.samples import diagnostic, request

ROOT = Path(__file__).resolve().parents[2]
EXTRA = (
    ("HIGH_CPU", "import time\n\ndef add(a, b):\n    end = time.monotonic() + 2\n    while time.monotonic() < end:\n        _ = 12345 ** 2\n    return a + b\n", None, 5000),
    ("HIGH_MEMORY", "import time\n\ndef add(a, b):\n    block = bytearray(24 * 1024 * 1024)\n    time.sleep(2)\n    return a + b + block[0]\n", None, 5000),
    ("OOM", "def add(a, b):\n    return bytearray(512 * 1024 * 1024)\n", None, 5000),
)


def run(output, image="srp-b-python:0.3.0"):
    if output.exists():
        raise ValueError("Output exists; choose a new filename")
    started = monotonic()
    record = {"record_version": "1.0", "verified_at": utcnow(), "implementation_version": __version__,
              "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_state": "Uncommitted phase1 workspace; hashes bind the executed sources",
              "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "scope": "Self-authored public fixtures; native B Docker only, no A/C/O or model calls",
              "real_docker": False, "real_claude_api_calls": 0, "cases": []}
    files = sorted((ROOT / "python_service/srp_b").glob("*.py")) + [Path(__file__).resolve(), ROOT / "docker/b-local/Dockerfile"]
    record["source_hashes"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    registry, tracking = ContractRegistry(), None
    try:
        version = docker("version", "--format", "{{json .Server}}")
        inspected = docker("image", "inspect", image, "--format", "{{.Id}}")
        if version.returncode or inspected.returncode:
            record.update(result="BLOCKED_BY_DOCKER", reason="Existing engine/image unavailable")
        else:
            record.update(engine=json.loads(version.stdout)["Version"], image_id=inspected.stdout.strip())
            with tempfile.TemporaryDirectory(prefix="b-phase1-docker-") as state:
                module = create_module(state_dir=state, image=image, diagnosis_backend="rules")
                tracking = TrackingRunner(module.runner)
                module.runner = tracking
                private = ROOT / "python_service/.interop/phase1" / Path(state).name
                private.mkdir(parents=True, exist_ok=True)
                record["private_records"] = private.relative_to(ROOT).as_posix()
                for name, source, tests, timeout in (*SCENARIOS, *EXTRA):
                    began = monotonic()
                    case = {"case_id": name, "result": "failed"}
                    try:
                        options = {"source": source, "task_id": "phase1-" + name, "run_id": "phase1-" + name}
                        if tests is not None:
                            options["tests"] = tests
                        envelope = request(EXECUTE, **options)
                        envelope["payload"]["execution_policy"]["timeout_ms"] = timeout
                        response = module.call(EXECUTE, envelope)
                        registry.validate_response(EXECUTE, response)
                        check_response(envelope, response)
                        (private / (name + ".json")).write_text(json.dumps({"request": envelope, "response": response}, ensure_ascii=False, indent=2), encoding="utf-8")
                        assert response["payload"]["status"] == "completed", response["payload"]["status"]
                        fact = response["payload"]["data"]
                        resources = fact["resource_usage"]
                        monitoring = resources["extensions"]["srp_b"]["resource_monitoring"]
                        isolation = fact["execution_context"]["isolation_guarantees"]
                        case.update(
                            execution_id=fact["execution_id"], execution_status=fact["execution_status"],
                            test_outcome=fact["test_outcome"], termination_reason=fact["termination_reason"],
                            execution_calls=response["payload"]["usage"]["execution_calls"],
                            code_hash=fact["code_hash"], test_hash=fact["test_hash"],
                            execution_config_hash=fact["execution_config_hash"],
                            image_id=fact["execution_context"]["image_digest"],
                            runtime=fact["execution_context"]["actual_runtime"],
                            package_versions=fact["execution_context"]["package_versions"],
                            resource_usage=resources, traceback=fact["traceback"],
                            isolation_guarantees=isolation,
                        )
                        assert case["image_id"] == record["image_id"]
                        assert isolation["container_cleanup_confirmed"] and monitoring["monitor_thread_cleanup_confirmed"]
                        assert isolation["network"] == "none" and isolation["root_read_only"] and isolation["capabilities"] == "dropped"
                        assert isolation["cpu_limit"] == 1 and isolation["memory_mb"] == 256
                        if name in {"SUCCESS", "HIGH_CPU", "HIGH_MEMORY"}:
                            assert fact["test_outcome"] == "passed"
                        elif name == "TEST_FAILED":
                            assert fact["test_outcome"] == "failed" and fact["traceback"]
                            current = diagnostic(fact, envelope)
                            diagnosis = module.call(DIAGNOSE, current)
                            registry.validate_response(DIAGNOSE, diagnosis)
                            assert diagnosis["payload"]["status"] == "completed"
                            assert diagnosis["payload"]["data"]["failure_source"]["execution_result"] == fact
                            assert diagnosis["payload"]["usage"]["execution_calls"] == 0
                            case["diagnosis_confidence"] = diagnosis["payload"]["data"]["diagnosis_report"]["extensions"]["srp_b"]["confidence_assessment"]
                        elif name == "TIMEOUT":
                            assert fact["execution_status"] == "timeout" and monitoring["timeout"] is True
                        elif name == "OUTPUT_LIMIT":
                            assert fact["execution_status"] == "policy_rejected" and monitoring["output_limit_reached"]
                            assert fact["stdout"]["truncated"] and len(fact["stdout"]["text"].encode()) <= 32768
                        else:
                            assert fact["execution_status"] == "oom" and monitoring["oom_killed"] is True
                        if name == "HIGH_CPU":
                            assert resources["cpu_time_ms"] is not None and resources["cpu_time_ms"] > 0
                        if name == "HIGH_MEMORY":
                            assert resources["peak_memory_bytes"] is not None and resources["peak_memory_bytes"] >= 24 * 1024 * 1024
                        case["result"] = "passed"
                    except (AssertionError, ValueError, TypeError, KeyError, OSError) as error:
                        case["error"] = f"{type(error).__name__}: {error}"
                    case["duration_seconds"] = round(monotonic() - began, 3)
                    record["cases"].append(case)
                    print(name + ": " + case["result"], flush=True)
                record["real_docker"] = any(c.get("execution_calls") == 1 for c in record["cases"])
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        record.update(result="BLOCKED_BY_ENVIRONMENT", reason=type(error).__name__)
    finally:
        if tracking is not None:
            listing = docker("ps", "-a", "--format", "{{.Names}}")
            remaining = sorted(tracking.names.intersection(listing.stdout.splitlines()))
            for name in remaining:
                docker("rm", "--force", name)
            verified = docker("ps", "-a", "--format", "{{.Names}}")
            leftovers = sorted(tracking.names.intersection(verified.stdout.splitlines()))
            record["cases"].append({"case_id": "CLEANUP", "result": "passed" if not remaining and not leftovers and verified.returncode == 0 else "failed", "remaining_owned_containers": leftovers, "remediation_needed": bool(remaining)})
        if "result" not in record:
            record["result"] = "passed" if len(record["cases"]) == 8 and all(c["result"] == "passed" for c in record["cases"]) else "failed"
        record["counts"] = {key: sum(c["result"] == key for c in record["cases"]) for key in ("passed", "failed", "skipped")}
        record["counts"]["total"] = len(record["cases"])
        record["physical_execution_calls"] = sum(c.get("execution_calls") or 0 for c in record["cases"])
        record["duration_seconds"] = round(monotonic() - started, 3)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--image", default="srp-b-python:0.3.0")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/verification/phase1_docker_smoke.json")
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker authorizes only the fixed self-authored fixtures")
    result = run(args.output, args.image)
    print(json.dumps({"result": result["result"], "counts": result["counts"]}))
    return int(result["result"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
