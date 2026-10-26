from copy import deepcopy
import json
from pathlib import Path

import pytest

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public, check_response
from reliable_codegen.transport import build_transport
from srp_b.samples import diagnostic, request
from scripts.verify_p2_local import STATIC, DIAGNOSE, run, validate_bundle

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture
def bundle():
    config = json.loads((REPOSITORY / "docs/integration/config.b-local.p2.example.json").read_text(encoding="utf-8"))
    manifest = json.loads((REPOSITORY / "docs/integration/p2_handoff_manifest.json").read_text(encoding="utf-8"))
    return config, manifest


def test_fixed_bundle_matches_installed_runtime_and_public_contract(bundle):
    validate_bundle(*bundle, ContractRegistry())


def test_bootstrap_rejects_http_configuration(bundle):
    config, manifest = bundle
    config["transport"] = "http"
    with pytest.raises(ValueError, match="LOCAL_V2_REQUIRED"):
        validate_bundle(config, manifest, ContractRegistry())


def test_bootstrap_rejects_implicit_real_model_factory_before_loading(bundle):
    config, manifest = bundle
    config["modules"]["A"]["factory"] = "untrusted.module:factory"
    with pytest.raises(ValueError, match="BOOTSTRAP_REQUIRES_EXPLICIT_MOCKS"):
        validate_bundle(config, manifest, ContractRegistry())


def test_bootstrap_rejects_unregistered_config_change(bundle):
    config, manifest = bundle
    config["max_repairs"] += 1
    with pytest.raises(ValueError, match="CONFIG_HASH_MISMATCH"):
        validate_bundle(config, manifest, ContractRegistry())


def test_bootstrap_rejects_wrong_contract_digest(bundle):
    config, manifest = bundle
    manifest["public_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="CONTRACT_HASH_MISMATCH"):
        validate_bundle(config, manifest, ContractRegistry())


def test_public_config_loads_real_static_and_diagnosis_without_docker(bundle, tmp_path):
    config, manifest = bundle
    validate_bundle(config, manifest, ContractRegistry())
    config["modules"]["B"]["options"]["state_dir"] = str(tmp_path / "state")
    transport = build_transport(config)
    assert transport.capabilities("B")["extensions"]["srp_b"]["implementation_version"] == "0.3.1"
    assert all(transport.capabilities(name)["extensions"]["mock"] for name in ("A", "C"))
    current = request(STATIC, source="def add(a,b)\n    return a+b\n")
    before = deepcopy(current)
    response = transport.call("B", STATIC, current)
    check_response(current, response)
    assert current == before and response["payload"]["data"]["status"] == "failed"
    diagnosis_request = diagnostic(response["payload"]["data"], current, static=True)
    diagnosis = transport.call("B", DIAGNOSE, diagnosis_request)
    check_response(diagnosis_request, diagnosis)
    check_public(diagnosis)
    assert diagnosis["payload"]["data"]["failure_source"]["static_report"] == response["payload"]["data"]
    assert diagnosis["payload"]["usage"]["execution_calls"] == 0


def test_bootstrap_accepts_config_and_manifest_outside_b_checkout(bundle, tmp_path):
    config, manifest = bundle
    config_path, manifest_path = tmp_path / "external-config.json", tmp_path / "external-manifest.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run(config_path, manifest_path, tmp_path / "summary.json")
    assert result["result"] == "passed" and result["docker_requested"] is False
    assert result["formal_p2_acceptance"] == "blocked"
    assert result["overlay_files"]["config"] == "external-config.json"
    assert result["overlay_hashes"]["config"]
