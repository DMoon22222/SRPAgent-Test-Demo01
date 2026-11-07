"""Git-free consumer check in an extracted bundle; never executes target code."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def run(bundle):
    bundle = Path(bundle).resolve()
    inventory = json.loads((bundle / "DELIVERY.json").read_text(encoding="utf-8"))
    for name, expected in inventory["files"].items():
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("CONSUMER_INVENTORY_MISMATCH")
    b_site, framework, tools = bundle / "installed_b", bundle / "framework", bundle / "b/python_service"
    sys.path[:0] = [str(b_site), str(framework), str(tools)]
    import srp_b
    import reliable_codegen
    if not Path(srp_b.__file__).resolve().is_relative_to(b_site) or not Path(reliable_codegen.__file__).resolve().is_relative_to(framework):
        raise ValueError("CONSUMER_SOURCE_SHADOWED")
    from scripts.check_p2_delivery import check
    from reliable_codegen.contracts import ContractRegistry
    from reliable_codegen.guards import check_response, check_public
    from reliable_codegen.transport import build_transport
    from srp_b.samples import request, diagnostic
    audit = check(bundle / "b")
    config = json.loads((bundle / "b/docs/integration/config.b-local.p2.example.json").read_text(encoding="utf-8"))
    config["modules"]["B"]["options"]["state_dir"] = str(bundle / "consumer-state")
    transport = build_transport(config)
    operation = "/api/v2/validate/static"
    envelope = request(operation, source="def add(a,b)\n    return a+b\n")
    response = transport.call("B", operation, envelope)
    ContractRegistry().validate_response(operation, response)
    check_response(envelope, response)
    fact = response["payload"]["data"]
    if fact["status"] != "failed":
        raise ValueError("CONSUMER_STATIC_CHECK_FAILED")
    current = diagnostic(fact, envelope, static=True)
    result = transport.call("B", "/api/v2/diagnose", current)
    check_response(current, result)
    check_public(result)
    if result["payload"]["status"] != "completed" or result["payload"]["usage"]["execution_calls"] != 0:
        raise ValueError("CONSUMER_RULE_CHECK_FAILED")
    if any(name in sys.modules for name in ("fastapi", "uvicorn", "mcp", "a2a")):
        raise ValueError("UNEXPECTED_LEGACY_SERVICE_IMPORT")
    return {"result": "passed", "inventory_files_checked": len(inventory["files"]), "delivery_files_checked": audit["files_checked"],
            "wheel_factory_loaded": True, "framework_snapshot_loaded": True, "git_checkout_required": False,
            "real_ast_and_rules": True, "actual_target_executions": 0, "actual_model_calls": 0,
            "dependency_environment": "Existing local-v2 venv dependencies reused; no clean dependency install claimed",
            "formal_p2_acceptance": "blocked", "o_receipt": "not_received"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.bundle_root)))
