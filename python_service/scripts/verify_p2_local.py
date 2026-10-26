"""P2 bootstrap only: portable fixed B entry, real AST/rules and optional Docker/O.

This does not perform the full P2 interface matrix or provide O group receipt.
All original envelopes and O records stay in the private .interop directory.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import traceback

import srp_b
from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public, check_response
from reliable_codegen.orchestrator import Orchestrator, demo_inputs
from reliable_codegen.transport import build_transport
from reliable_codegen.utils import canonical, digest, uid, utcnow
from srp_b.samples import diagnostic, request

ROOT = Path(__file__).resolve().parents[1]
STATIC, EXECUTE, DIAGNOSE = ("/api/v2/validate/static", "/api/v2/execute", "/api/v2/diagnose")


def require(condition, code):
    if not condition:
        raise ValueError(code)


def validate_bundle(config, manifest, registry):
    """Check the trusted delivery bundle before importing configured factories."""
    require(config.get("transport") == "local" and config.get("schema_version") == "2.0", "LOCAL_V2_REQUIRED")
    require(set(config["modules"]) == {"A", "B", "C"}, "MODULE_SET_MISMATCH")
    require(config["modules"]["B"]["factory"] == manifest["factory"] == "srp_b:create_module", "B_FACTORY_MISMATCH")
    for name in ("A", "C"):
        entry = config["modules"][name]
        require(entry["factory"] == "reliable_codegen.mocks:create_mock_module" and entry["options"]["service"] == name,
                "BOOTSTRAP_REQUIRES_EXPLICIT_MOCKS")
    require(digest(canonical(config)) == manifest["config_canonical_sha256"], "CONFIG_HASH_MISMATCH")
    require(config["modules"]["B"]["options"]["image"] == manifest["image"]["configured_name"], "IMAGE_CONFIGURATION_MISMATCH")
    require(re.fullmatch(r"[0-9a-f]{40}", manifest["source"]["revision"]) is not None, "FIXED_SOURCE_REQUIRED")
    require(srp_b.__version__ == manifest["implementation_version"], "IMPLEMENTATION_VERSION_MISMATCH")
    actual_contract = hashlib.sha256((registry.root / "openapi_v0.2.json").read_bytes()).hexdigest()
    require(actual_contract == manifest["public_contract_sha256"], "CONTRACT_HASH_MISMATCH")
    runtime_root = Path(srp_b.__file__).resolve().parent.parent
    for relative, expected in manifest["runtime_source_hashes"].items():
        path = (runtime_root / relative).resolve()
        require(path.is_relative_to(runtime_root), "SOURCE_PATH_OUTSIDE_PACKAGE")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "RUNTIME_SOURCE_HASH_MISMATCH")


def run(config_path, manifest_path, output, *, docker=False):
    registry = ContractRegistry()
    private = ROOT / ".interop/p2-bootstrap" / uid("run")
    private.mkdir(parents=True)
    checks = []
    summary = {"verified_at": utcnow(), "result": "failed", "scope": "P2 bootstrap technical self-verification only",
               "implementation_version": srp_b.__version__, "checks": checks, "docker_requested": docker,
               "formal_p2_acceptance": "blocked", "o_receipt": "not_received", "model_calls": 0,
               "actual_target_a_context_verified": False,
               "external_dependencies": "docs/integration/p2_external_dependencies.json",
               "raw_records": "Private python_service/.interop/p2-bootstrap directory; not committed"}

    def passed(name, kind="real_adapter", **details):
        checks.append({"name": name, "result": "passed", "evidence_kind": kind, **details})
        print("passed: " + name, flush=True)

    def docker_text(*args):
        return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.DEVNULL, timeout=15).strip()

    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        validate_bundle(config, manifest, registry)
        # Config and manifest may be supplied from O's checkout or another directory.
        # Stable role names avoid embedding host paths or requiring a sibling layout.
        overlay = {"config": Path(config_path), "manifest": Path(manifest_path), "driver": Path(__file__),
                   "tests": ROOT / "tests/test_local_v2_p2.py",
                   "dependencies": ROOT.parent / "docs/integration/p2_external_dependencies.json"}
        summary.update(source_revision=manifest["source"]["revision"], public_contract_sha256=manifest["public_contract_sha256"],
                       config_canonical_sha256=manifest["config_canonical_sha256"],
                       overlay_state="Uncommitted P2 delivery tools; fixed 0.3.1 runtime is unchanged",
                       overlay_hashes={role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in overlay.items()},
                       overlay_files={role: path.name for role, path in overlay.items()},
                       host_python=platform.python_version(),
                       host_packages={name: importlib.metadata.version(name) for name in ("pydantic", "jsonschema", "pytest")},
                       framework_git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=registry.root.parent, text=True).strip())
        passed("fixed_runtime_config_and_contract", runtime_source_files=len(manifest["runtime_source_hashes"]))
        effective = deepcopy(config)
        effective["modules"]["B"]["options"]["state_dir"] = str(private / "b-state")
        summary["config_overrides"] = {"B.options.state_dir": "Private directory unique to this run", "output_dir": "Private O directory unique to this run"}
        transport = build_transport(effective, registry)
        caps = {name: transport.capabilities(name) for name in "ABC"}
        require(all(caps[name].get("extensions", {}).get("mock") for name in ("A", "C")), "MOCK_MARKER_MISSING")
        require(set(caps["B"]["operations"]) == {STATIC, EXECUTE, DIAGNOSE}, "B_OPERATION_MISMATCH")
        require({"static_feedback", "feedback_only"} <= set(caps["B"]["supported_diagnosis_modes"]), "B_DIAGNOSIS_MODE_MISMATCH")
        passed("public_factories_and_capabilities", factories={k: v["factory"] for k, v in effective["modules"].items()})

        def call(operation, envelope):
            envelope["created_at"] = utcnow()
            response = transport.call("B", operation, envelope)
            registry.validate_request(operation, envelope)
            registry.validate_response(operation, response)
            check_response(envelope, response)
            check_public(response)
            identity = uid("call-record")
            (private / (identity + ".json")).write_text(canonical({"request": envelope, "response": response}), encoding="utf-8")
            require(response["payload"]["status"] == "completed", "B_BOOTSTRAP_OPERATION_INCOMPLETE")
            return response

        static_request = request(STATIC, source="def add(a,b)\n    return a+b\n", task_id=uid("bootstrap-static"), run_id=uid("run"))
        static = call(STATIC, static_request)["payload"]["data"]
        require(static["status"] == "failed", "STATIC_FAILURE_NOT_OBSERVED")
        passed("real_static_failure", "real_static", report_id=static["report_id"])
        diagnosis = call(DIAGNOSE, diagnostic(static, static_request, static=True))["payload"]
        require(diagnosis["data"]["failure_source"]["static_report"] == static and diagnosis["usage"]["execution_calls"] == 0,
                "STATIC_DIAGNOSIS_FACT_MISMATCH")
        passed("static_feedback_without_execution", "real_rules", diagnosis_id=diagnosis["data"]["diagnosis_report"]["diagnosis_id"])

        if docker:
            image_id = docker_text("image", "inspect", "--format", "{{.Id}}", manifest["image"]["configured_name"])
            require(image_id == manifest["image"]["expected_id"], "LOCKED_IMAGE_MISMATCH")
            baseline_containers = set(docker_text("ps", "-aq", "--filter", "name=srp-b-execution-").split())
            summary.update(docker_engine=docker_text("version", "--format", "{{.Server.Version}}"), image_digest=image_id)
            passed("locked_image_available", "real_environment_probe", image_digest=image_id)
            execution_request = request(EXECUTE, task_id=uid("bootstrap-execute"), run_id=uid("run"))
            execution_response = call(EXECUTE, execution_request)
            fact = execution_response["payload"]["data"]
            context = fact["execution_context"]
            require(fact["test_outcome"] == "passed" and bool(fact["test_case_results"]), "REAL_TESTS_NOT_PASSED")
            require(context["image_digest"] == image_id and context["actual_runtime"] == manifest["image"]["expected_runtime"], "OBSERVED_ENVIRONMENT_MISMATCH")
            require(context["isolation_guarantees"]["container_cleanup_confirmed"], "CLEANUP_NOT_CONFIRMED")
            passed("real_execution_from_portable_config", "real_docker", execution_id=fact["execution_id"],
                   code_hash=fact["code_hash"], test_hash=fact["test_hash"], config_hash=fact["execution_config_hash"],
                   actual_runtime=context["actual_runtime"], package_versions=context["package_versions"])
            orchestrator = Orchestrator(transport, private / "o-run", registry, max_repairs=config["max_repairs"], routing_mode=config["routing_mode"])
            mixed = orchestrator.run(**demo_inputs(registry))
            (private / "o-summary.json").write_text(canonical(mixed), encoding="utf-8")
            require(mixed["state"] == "accepted" and not mixed["unknown_usage_ids"], "MIXED_FLOW_NOT_ACCEPTED")
            passed("real_o_b_with_mock_a_c", "mixed", run_id=mixed["run_id"], trace_id=orchestrator.trace_id,
                   terminal=mixed["state"], iterations=mixed["iterations"], routing_mode=config["routing_mode"],
                   used_budget=mixed["budget"]["used"], o_receipt="not_received")
            require(not set(docker_text("ps", "-aq", "--filter", "name=srp-b-execution-").split()) - baseline_containers,
                    "NEW_VERIFICATION_CONTAINERS_REMAIN")
            passed("no_new_remaining_containers", "real_environment_probe")
        summary["result"] = "passed"
    except Exception as error:
        summary["error_code"] = str(error) if re.fullmatch(r"[A-Z_]+", str(error)) else "BOOTSTRAP_FAILED"
        (private / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    summary["unverified"] = ["Full P2 multi-round/interface matrix", "TEST-001 formal material lock", "Actual target A tokenizer/context metadata", "Independent O receipt", "Real A/C algorithms"]
    check_public(summary)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT.parent / "docs/integration/config.b-local.p2.example.json")
    parser.add_argument("--manifest", type=Path, default=ROOT.parent / "docs/integration/p2_handoff_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "docs/verification/p2/bootstrap_validation.json")
    parser.add_argument("--docker", action="store_true", help="Execute the fixed self-authored public fixtures in Docker")
    args = parser.parse_args()
    result = run(args.config, args.manifest, args.output, docker=args.docker)
    print(json.dumps({"result": result["result"], "checks": len(result["checks"]), "formal_p2_acceptance": result["formal_p2_acceptance"]}))
    return 0 if result["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
