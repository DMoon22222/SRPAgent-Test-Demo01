"""Four opt-in real Docker executions and one cleanup check; no image pull."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from time import monotonic

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_response
from reliable_codegen.transport import TransportError
from reliable_codegen.utils import utcnow
from srp_b import __version__, create_module
from srp_b.module import DIAGNOSE, EXECUTE
from srp_b.samples import diagnostic, request

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = (
    ("SUCCESS", "def add(a, b):\n    return a + b\n", None, 10000),
    ("TEST_FAILED", "def add(a, b):\n    return a - b\n", None, 10000),
    ("TIMEOUT", "def add(a, b):\n    while True:\n        pass\n", None, 1000),
    (
        "OUTPUT_LIMIT",
        ("import os\n\ndef add(a, b):\n    for _ in range(64):\n"
         "        os.write(1, b'x' * 65536)\n    return a + b\n"),
        ("from src.main import add\n\ndef test_output(capfd):\n"
         "    with capfd.disabled():\n        assert add(2, 3) == 5\n"),
        10000,
    ),
)


def docker(*arguments):
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=15, check=False,
    )


class TrackingRunner:
    """Observe native runner container names; delegate all facts unchanged."""

    def __init__(self, native):
        self.native = native
        self.names = set()

    def execute(self, payload, *, timeout_seconds, execution_id):
        name = "srp-b-" + execution_id
        self.names.update((name, name + "-probe"))
        return self.native.execute(
            payload, timeout_seconds=timeout_seconds, execution_id=execution_id,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--image", default="srp-b-python:0.3.0")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "docs/verification/pre_integration_docker_smoke.json",
    )
    args = parser.parse_args()
    if not args.docker:
        parser.error("--docker explicitly authorizes these self-authored fixtures")
    if args.output.exists():
        parser.error("Output already exists; select a fresh path to retain prior evidence")
    started = monotonic()
    result = {
        "record_version": "1.0", "verified_at": utcnow(),
        "implementation_version": __version__,
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "host": {"python": platform.python_version(), "platform": platform.platform()},
        "image": args.image, "mock": False, "real_docker": False,
        "real_claude_api": False, "model_calls": 0,
        "scope": "B-only smoke; fixed public synthetic fixtures, no A/C/O loop or formal receipt",
        "cases": [],
    }
    source_files = sorted((ROOT / "python_service/srp_b").glob("*.py")) + [
        ROOT / "python_service/app/analyzer/error_signal_extractor.py",
        ROOT / "docker/b-local/Dockerfile",
    ]
    result["source_hashes"] = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files
    }
    result["source_state"] = "Uncommitted hardening workspace, bound by source_hashes"
    registry = ContractRegistry()
    tracking = None
    try:
        version = docker("version", "--format", "{{json .Server}}")
        inspected = docker("image", "inspect", args.image, "--format", "{{.Id}}")
        if version.returncode or inspected.returncode:
            result.update(result="BLOCKED_BY_DOCKER", reason="Engine or existing local image unavailable")
        else:
            result.update(engine=json.loads(version.stdout)["Version"], image_id=inspected.stdout.strip())
            with tempfile.TemporaryDirectory(prefix="b-hardening-state-") as temp:
                module = create_module(state_dir=temp, image=args.image, diagnosis_backend="rules")
                tracking = TrackingRunner(module.runner)
                module.runner = tracking
                raw_dir = ROOT / "python_service/.interop/pre-integration" / Path(temp).name
                raw_dir.mkdir(parents=True, exist_ok=True)
                result["private_records"] = raw_dir.relative_to(ROOT).as_posix()
                for name, source, tests, timeout in SCENARIOS:
                    case_start = monotonic()
                    case = {"case_id": name, "result": "failed", "evidence_kind": "real_docker"}
                    try:
                        options = {"source": source, "task_id": "hardening-" + name, "run_id": "hardening-" + name}
                        if tests is not None:
                            options["tests"] = tests
                        envelope = request(EXECUTE, **options)
                        envelope["payload"]["execution_policy"]["timeout_ms"] = timeout
                        response = module.call(EXECUTE, envelope)
                        registry.validate_response(EXECUTE, response)
                        check_response(envelope, response)
                        (raw_dir / (name + ".json")).write_text(
                            json.dumps({"request": envelope, "response": response}, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        if response["payload"]["status"] != "completed":
                            raise AssertionError("B capability did not complete")
                        fact = response["payload"]["data"]
                        isolation = fact["execution_context"]["isolation_guarantees"]
                        case.update(
                            execution_id=fact["execution_id"],
                            execution_status=fact["execution_status"], test_outcome=fact["test_outcome"],
                            exit_code=fact["exit_code"], termination_reason=fact["termination_reason"],
                            tests_total=fact["tests_total"], tests_passed=fact["tests_passed"],
                            code_hash=fact["code_hash"], test_hash=fact["test_hash"],
                            execution_config_hash=fact["execution_config_hash"],
                            actual_runtime=fact["execution_context"]["actual_runtime"],
                            image_digest=fact["execution_context"]["image_digest"],
                            isolation_guarantees=isolation, resource_usage=fact["resource_usage"],
                            stdout_retained_bytes=len(fact["stdout"]["text"].encode()),
                            stdout_truncated=fact["stdout"]["truncated"],
                            execution_calls=response["payload"]["usage"]["execution_calls"],
                        )
                        assert isolation.get("container_cleanup_confirmed") is True
                        assert isolation["network"] == "none" and isolation["root_read_only"]
                        assert case["image_digest"] == result["image_id"]
                        if name == "SUCCESS":
                            assert fact["test_outcome"] == "passed" and fact["tests_total"] > 0
                        elif name == "TEST_FAILED":
                            assert fact["test_outcome"] == "failed" and fact["test_case_results"]
                            diagnostic_request = diagnostic(fact, envelope)
                            explanation = module.call(DIAGNOSE, diagnostic_request)
                            registry.validate_response(DIAGNOSE, explanation)
                            report = explanation["payload"]["data"]["diagnosis_report"]
                            assert report["failure_class"] == "test_failure" and report["evidence_refs"]
                            assert explanation["payload"]["usage"]["execution_calls"] == 0
                            case["diagnosis"] = {"failure_class": report["failure_class"], "evidence_refs": report["evidence_refs"]}
                        elif name == "TIMEOUT":
                            assert fact["execution_status"] == "timeout" and fact["termination_reason"] == "timeout"
                        else:
                            assert fact["execution_status"] == "policy_rejected"
                            assert fact["termination_reason"] == "policy" and fact["stdout"]["truncated"]
                            assert case["stdout_retained_bytes"] <= 32768
                        case["result"] = "passed"
                    except (AssertionError, KeyError, TypeError, ValueError, OSError, TransportError) as error:
                        case["error"] = f"{type(error).__name__}: {error}"
                    case["duration_seconds"] = round(monotonic() - case_start, 3)
                    result["cases"].append(case)
                    print(name + ": " + case["result"], flush=True)
                result["real_docker"] = any(c.get("execution_calls") == 1 for c in result["cases"])
    except (OSError, subprocess.SubprocessError, ValueError, sqlite3.Error) as error:
        result.update(result="BLOCKED_BY_ENVIRONMENT", reason=type(error).__name__)
    finally:
        if tracking is not None:
            cleanup = {"case_id": "CLEANUP", "result": "passed", "owned_containers": len(tracking.names)}
            try:
                listing = docker("ps", "-a", "--format", "{{.Names}}")
                assert listing.returncode == 0
                remaining = sorted(tracking.names.intersection(listing.stdout.splitlines()))
                cleanup["remaining_before_remediation"] = remaining
                for name in remaining:
                    docker("rm", "--force", name)
                verified = docker("ps", "-a", "--format", "{{.Names}}")
                cleanup["remaining_owned_containers"] = sorted(tracking.names.intersection(verified.stdout.splitlines()))
                if remaining or verified.returncode or cleanup["remaining_owned_containers"]:
                    cleanup["result"] = "failed"
            except (OSError, subprocess.SubprocessError, AssertionError) as error:
                cleanup.update(result="failed", error=type(error).__name__)
            result["cases"].append(cleanup)
        if "result" not in result:
            result["result"] = "passed" if len(result["cases"]) == 5 and all(c["result"] == "passed" for c in result["cases"]) else "failed"
        if result["result"].startswith("BLOCKED"):
            completed_ids = {case["case_id"] for case in result["cases"]}
            for name in (*[scenario[0] for scenario in SCENARIOS], "CLEANUP"):
                if name not in completed_ids:
                    result["cases"].append({"case_id": name, "result": "blocked", "reason": result["result"]})
        result["counts"] = {key: sum(c["result"] == key for c in result["cases"]) for key in ("passed", "failed", "skipped", "blocked")}
        result["counts"]["total"] = len(result["cases"])
        result["physical_execution_calls"] = sum(c.get("execution_calls") or 0 for c in result["cases"])
        result["duration_seconds"] = round(monotonic() - started, 3)
        result["driver_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": result["result"], "counts": result["counts"]}), flush=True)
    return 1 if result["result"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
