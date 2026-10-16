from copy import deepcopy
from unittest.mock import patch

import pytest

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_execution_cases, check_response
from reliable_codegen.storage import ArtifactStore
from reliable_codegen.transport import LocalTransport, TransportError
from reliable_codegen.utils import canonical, digest, file_entry, files_hash
from srp_b import create_module
from srp_b.module import BModule, DIAGNOSE, EXECUTE, STATIC
from srp_b.samples import diagnostic, request
from srp_b.sandbox import Command, DockerRunner, empty_observation, log_stream, parse_cases


class SyntheticRunner:
    def __init__(self):
        self.calls = 0

    def execute(self, payload, **kwargs):
        self.calls += 1
        result = empty_observation()
        result.update(execution_status="completed", test_outcome="failed", exit_code=1,
                      tests_passed=0, tests_total=1, failure_stage="test", termination_reason="normal",
                      stderr=log_stream("AssertionError: assert -1 == 5"), execution_calls=1,
                      test_case_results=[{"test_id": "test_add", "status": "failed", "oracle_level": payload["test_artifact"]["kind"],
                                          "expected": None, "actual": None, "error_type": "AssertionError",
                                          "message": "assert -1 == 5", "location": None}])
        return result


@pytest.fixture
def module(tmp_path):
    return BModule(state_dir=tmp_path / "state", runner=SyntheticRunner())


def call(module, operation, envelope):
    result = module.call(operation, envelope)
    registry = ContractRegistry()
    registry.validate_response(operation, result)
    check_response(envelope, result)
    return result["payload"]


def rehash(artifact):
    for f in artifact["files"]:
        f["sha256"] = digest(f["content"])
    artifact["content_hash" if "content_hash" in artifact else "test_hash"] = files_hash(artifact["files"])


def test_capability_is_valid_json_and_isolated(tmp_path):
    module = create_module(state_dir=str(tmp_path / "factory"))
    capability = module.capabilities()
    ContractRegistry().validate("CapabilityDescriptor", capability)
    assert capability["supported_diagnosis_modes"] == ["static_feedback", "feedback_only"]
    capability["operations"].clear()
    assert len(module.capabilities()["operations"]) == 3


def test_static_failure_has_no_execution_fact_or_execution(module):
    envelope = request(STATIC, source="def add(a, b)\n    return a + b\n")
    outcome = call(module, STATIC, envelope)
    assert outcome["status"] == "completed" and outcome["data"]["status"] == "failed"
    assert "execution_result" not in outcome["data"]
    diagnosis = call(module, DIAGNOSE, diagnostic(outcome["data"], envelope, static=True))
    assert diagnosis["data"]["diagnosis_report"]["failure_class"] == "syntax_error"
    assert diagnosis["data"]["diagnosis_report"]["execution_result_id"] is None
    assert module.runner.calls == 0


def test_unsupported_static_check_does_not_pass(module):
    envelope = request(STATIC)
    envelope["payload"]["validation_policy"]["checks"] = ["security_scan"]
    assert call(module, STATIC, envelope)["data"]["status"] == "blocked"


def test_static_missing_entry_is_reported_as_a_static_fact(module):
    envelope = request(STATIC)
    envelope["payload"]["build_manifest"]["entry_point"] = "src/missing.py"
    outcome = call(module, STATIC, envelope)
    assert outcome["data"]["status"] == "failed"
    assert any(f["check"] == "entry_point" and f["status"] == "failed" for f in outcome["data"]["findings"])
    assert module.runner.calls == 0


def test_nonstdlib_task_import_is_explicitly_blocked(module):
    envelope = request(EXECUTE, source="import requests\n")
    outcome = call(module, EXECUTE, envelope)
    assert outcome["status"] == "blocked" and outcome["data"]["reason"] == "NON_STDLIB_TASK_IMPORT"
    assert module.runner.calls == 0


def test_legacy_contract_is_not_silently_upgraded(module):
    with pytest.raises(TransportError) as error:
        module.call(EXECUTE, {"schemaVersion": "1.0"})
    assert error.value.response["error"]["error_code"] == "CONTRACT_INVALID"


@pytest.mark.parametrize("change", [
    lambda r: r["payload"]["code_artifact"]["files"][0].update(content="changed"),
    lambda r: r["payload"]["test_artifact"].update(test_hash="0" * 64),
    lambda r: r["payload"]["code_artifact"].update(attempt_id="other"),
])
def test_invalid_artifacts_never_reach_runner(module, change):
    envelope = request(EXECUTE)
    change(envelope)
    assert call(module, EXECUTE, envelope)["status"] == "error"
    assert module.runner.calls == 0


def test_traversal_is_rejected_by_boundary_schema(module):
    envelope = request(EXECUTE)
    envelope["payload"]["code_artifact"]["files"][0]["path"] = "../main.py"
    with pytest.raises(TransportError, match="CONTRACT_INVALID"):
        module.call(EXECUTE, envelope)
    assert module.runner.calls == 0


@pytest.mark.parametrize("change,reason", [
    (lambda r: r["payload"]["call_grant"].update(max_execution_calls=0), "EXECUTION_NOT_AUTHORIZED"),
    (lambda r: r["payload"]["call_grant"].update(budget_revision=999), "GRANT_BUDGET_MISMATCH"),
    (lambda r: r["payload"]["budget"]["remaining"].update(tokens=0), "INVALID_BUDGET_SNAPSHOT"),
    (lambda r: r["payload"]["call_grant"].update(deadline_at="2000-01-01T00:00:00Z"), "DEADLINE_EXCEEDED"),
    (lambda r: r.update(deadline_at="2000-01-01T00:00:00Z"), "DEADLINE_EXCEEDED"),
])
def test_grant_budget_and_earliest_deadline(module, change, reason):
    envelope = request(EXECUTE)
    change(envelope)
    outcome = call(module, EXECUTE, envelope)
    assert outcome["status"] == "blocked" and outcome["data"]["reason"] == reason
    assert outcome["usage"]["execution_calls"] == 0
    assert module.runner.calls == 0


def test_execution_and_feedback_diagnosis_preserve_original(module):
    envelope = request(EXECUTE)
    fact = call(module, EXECUTE, envelope)["data"]
    check_execution_cases(fact)
    before = deepcopy(fact)
    diagnosis = call(module, DIAGNOSE, diagnostic(fact, envelope))
    assert diagnosis["data"]["failure_source"]["execution_result"] == before == fact
    assert diagnosis["data"]["diagnosis_report"]["failure_domain"] == "code"
    assert diagnosis["usage"]["execution_calls"] == diagnosis["usage"]["model_calls"] == 0
    assert module.runner.calls == 1


def test_completed_replay_survives_new_instance_and_skips_work(module, tmp_path):
    envelope = request(EXECUTE)
    first = module.call(EXECUTE, envelope)
    first_copy = deepcopy(first)
    first["payload"]["data"]["execution_id"] = "mutated-by-consumer"
    renewed = BModule(state_dir=tmp_path / "state", runner=SyntheticRunner())
    with patch.object(renewed, "_authorize", side_effect=AssertionError("Replay must skip deadline check")):
        assert renewed.call(EXECUTE, envelope) == first_copy
    assert renewed.runner.calls == 0
    assert module.runner.calls == 1


def test_same_key_changed_body_rejected(module):
    envelope = request(EXECUTE)
    module.call(EXECUTE, envelope)
    envelope["extensions"] = {"changed": True}
    with pytest.raises(TransportError, match="IDEMPOTENCY_CONFLICT"):
        module.call(EXECUTE, envelope)
    assert module.runner.calls == 1


def test_pending_record_does_not_reexecute(module):
    envelope = request(EXECUTE)
    module.journal.begin(EXECUTE, envelope)
    outcome = call(module, EXECUTE, envelope)
    assert outcome["error"]["error_code"] == "OUTCOME_UNKNOWN"
    assert outcome["usage"]["execution_calls"] is None
    assert module.runner.calls == 0


def test_reused_grant_cannot_start_second_work(module):
    envelope = request(EXECUTE)
    module.call(EXECUTE, envelope)
    envelope["message_id"] += "-second"
    with pytest.raises(TransportError, match="CALL_GRANT_REUSED"):
        module.call(EXECUTE, envelope)
    assert module.runner.calls == 1


@pytest.mark.parametrize("code_change", [True, False])
def test_immutable_code_and_fixed_tests(module, code_change):
    call(module, EXECUTE, request(EXECUTE))
    second = request(EXECUTE)
    artifact = second["payload"]["code_artifact" if code_change else "test_artifact"]
    artifact["files"][0]["content"] += "\n# changed\n"
    rehash(artifact)
    outcome = call(module, EXECUTE, second)
    assert outcome["error"]["error_code"] == ("CODE_REVISION_REUSED" if code_change else "FIXED_TESTS_CHANGED")
    assert module.runner.calls == 1


def test_final_acceptance_executes_but_cannot_enter_diagnosis(module):
    envelope = request(EXECUTE)
    envelope["visibility"] = "restricted"
    envelope["payload"]["purpose"] = "final_acceptance"
    envelope["payload"]["test_artifact"]["kind"] = "final_hidden"
    fact = call(module, EXECUTE, envelope)["data"]
    assert fact["visibility"] == "restricted"
    assert fact["test_case_results"][0]["oracle_level"] == "final_hidden"
    protected = diagnostic(fact, envelope)
    with pytest.raises(TransportError) as error:
        module.call(DIAGNOSE, protected)
    assert error.value.response["error"]["details"] == {}
    assert module.runner.calls == 1


def test_diagnosis_error_retains_resolvable_original_fact(module, tmp_path):
    envelope = request(EXECUTE)
    fact = call(module, EXECUTE, envelope)["data"]
    store = ArtifactStore(tmp_path / "o-store")
    store.put(fact, "ExecutionResult", fact["execution_id"])
    with patch("srp_b.module.diagnose", side_effect=RuntimeError("private-detail")):
        outcome = call(module, DIAGNOSE, diagnostic(fact, envelope))
    reference = outcome["error"]["partial_result_ref"]
    assert outcome["error"]["error_code"] == "DIAGNOSIS_FAILED"
    assert store.get(reference) == fact
    assert module.resolve_fact(reference)["body_utf8"] == canonical(fact)
    assert "private-detail" not in canonical(outcome)
    assert module.runner.calls == 1


def test_history_reference_uses_scoped_resolver_and_hash(module, tmp_path):
    envelope = request(EXECUTE)
    fact = call(module, EXECUTE, envelope)["data"]
    current = diagnostic(fact, envelope)
    store = ArtifactStore(tmp_path / "store")
    ref = store.put(current["payload"]["code_artifact"], "CodeArtifact", "sample-code")
    current["payload"]["history_view"]["source_refs"] = [ref]
    transport = LocalTransport({"B": module})
    transport.bind_artifact_store(store)
    result = transport.call("B", DIAGNOSE, current)
    assert result["payload"]["status"] == "completed"
    assert getattr(module._bindings, "resolver", None) is None


def test_missing_resolver_blocks_instead_of_reading_private_state(module):
    envelope = request(EXECUTE)
    fact = call(module, EXECUTE, envelope)["data"]
    current = diagnostic(fact, envelope)
    current["payload"]["history_view"]["source_refs"] = [{"artifact_id": "missing", "artifact_type": "CodeArtifact",
        "sha256": "0" * 64, "media_type": "application/json", "visibility": "public", "resolver_key": "local-store"}]
    outcome = call(module, DIAGNOSE, current)
    assert outcome["status"] == "blocked"


@pytest.mark.parametrize("change", [
    lambda p: p["execution_policy"].update(network_policy="allowlist"),
    lambda p: p["execution_policy"].update(allowed_write_paths=["tmp", "tests"]),
    lambda p: p["execution_policy"].update(allowed_write_paths=["../tmp"]),
    lambda p: p["build_manifest"].update(test_command=["bash", "-c", "anything"]),
    lambda p: p["build_manifest"].update(test_command=["python", "-m", "pytest", "--override-ini=anything"]),
])
def test_unsupported_policy_never_starts_docker(change):
    payload = request(EXECUTE)["payload"]
    change(payload)
    runner = DockerRunner("unused", command=lambda *a, **k: pytest.fail("Docker must not start"))
    result = runner.execute(payload, timeout_seconds=5, execution_id="synthetic")
    assert result["execution_status"] == "policy_rejected" and result["execution_calls"] == 0


def test_pytest_report_preserves_every_outcome_and_rejects_entities():
    cases = parse_cases(b'<testsuite><testcase name="pass"/><testcase name="fail"><failure message="assert 1 == 2"/></testcase><testcase name="skip"><skipped/></testcase></testsuite>', "public")
    assert [c["status"] for c in cases] == ["passed", "failed", "skipped"]
    with pytest.raises(ValueError):
        parse_cases(b'<!DOCTYPE x [<!ENTITY y "z">]><testsuite/>', "public")


def test_docker_missing_returns_environment_fact_without_fake_runtime():
    def absent(*args, **kwargs):
        raise FileNotFoundError("docker")
    result = DockerRunner("unused", command=absent).execute(request(EXECUTE)["payload"], timeout_seconds=5, execution_id="synthetic")
    assert result["execution_status"] == "infrastructure_error"
    assert result["actual_runtime"] is None and result["execution_calls"] == 0
