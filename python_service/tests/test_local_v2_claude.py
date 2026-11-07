"""Real Anthropic SDK over an in-memory HTTP transport; no provider/network calls."""

from copy import deepcopy
import builtins
import json
from types import SimpleNamespace

import pytest

from reliable_codegen.budget import BudgetLedger
from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public, check_response
from reliable_codegen.transport import TransportError, build_transport
from srp_b import create_module
from srp_b.claude import ClaudeDiagnosis
from srp_b.module import BModule, Blocked, DIAGNOSE, EXECUTE, STATIC
from srp_b.samples import diagnostic, request
from test_local_v2 import SyntheticRunner


@pytest.fixture
def wire(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    original = anthropic.Anthropic
    state = SimpleNamespace(requests=[], constructors=[], clients=[], count=20,
                            status=200, timeout=False, stop_reason="end_turn", after_count=None,
                            explanation={"root_cause": "The recorded assertion contradicts the returned sum.",
                                         "suggestions": ["Compare the expression with the fixed assertion."],
                                         "evidence_indices": [0]},
                            usage={"input_tokens": 11, "output_tokens": 17,
                                   "cache_creation_input_tokens": 3, "cache_read_input_tokens": 5})

    def handle(current):
        state.requests.append(current)
        if current.url.path.endswith("/count_tokens"):
            if state.after_count:
                state.after_count()
            return httpx2.Response(200, json={"input_tokens": state.count})
        if state.timeout:
            raise httpx2.ReadTimeout("SENSITIVE_PROVIDER_EXCEPTION", request=current)
        if state.status != 200:
            return httpx2.Response(state.status, json={"type": "error", "error": {
                "type": "api_error", "message": "SENSITIVE_PROVIDER_EXCEPTION"}})
        text = state.explanation if isinstance(state.explanation, str) else json.dumps(state.explanation)
        return httpx2.Response(200, headers={"request-id": "req_offline"}, json={
            "id": "msg_offline", "type": "message", "role": "assistant", "model": "claude-test",
            "content": [{"type": "text", "text": text}], "stop_reason": state.stop_reason,
            "stop_sequence": None, "usage": state.usage})

    def construct(**options):
        state.constructors.append({k: v for k, v in options.items() if k != "api_key"})
        client = original(**options, http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
        state.clients.append(client)
        return client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-credential")
    monkeypatch.setattr(anthropic, "Anthropic", construct)
    return state


def configured(tmp_path, **options):
    return BModule(state_dir=tmp_path / "state", runner=SyntheticRunner(),
                   diagnosis_backend="anthropic", anthropic_model="claude-test", **options)


def diagnosis_request(module, *, static=True, source="def add(a, b)\n    return a + b\n"):
    original = request(STATIC if static else EXECUTE, source=source)
    fact = module.call(STATIC if static else EXECUTE, original)["payload"]["data"]
    current = diagnostic(fact, original, static=static)
    p = current["payload"]
    p["call_grant"].update(max_model_calls=1, max_rounds=1, max_input_tokens=8000, max_output_tokens=1024)
    p["budget"]["limits"]["tokens"] = p["budget"]["remaining"]["tokens"] = 100000
    p["budget"]["used"]["tokens"] = p["budget"]["reserved"]["tokens"] = 0
    return current


def checked(module, current):
    result = module.call(DIAGNOSE, current)
    ContractRegistry().validate_response(DIAGNOSE, result)
    check_response(current, result)
    check_public(result)
    return result["payload"]


@pytest.mark.parametrize("static", [True, False])
def test_sdk_explanation_preserves_facts_and_counts_actual_usage(tmp_path, wire, static):
    module = configured(tmp_path)
    current = diagnosis_request(module, static=static)
    before = deepcopy(current)
    executions = module.runner.calls
    result = checked(module, current)
    assert result["status"] == "completed"
    assert current == before and module.runner.calls == executions
    assert result["data"]["failure_source"] == current["payload"]["failure_source"]
    report = result["data"]["diagnosis_report"]
    assert report["root_cause"] == wire.explanation["root_cause"] and report["confidence"] is None
    assert report["hypotheses"][0]["evidence_refs"] == [report["evidence_refs"][0]]
    assert report["extensions"]["srp_b"]["provider"] == "anthropic"
    usage = result["usage"]
    assert (usage["model_calls"], usage["input_tokens"], usage["output_tokens"], usage["execution_calls"]) == (1, 19, 17, 0)
    assert usage["measurement_status"] == "complete"
    assert len(wire.requests) == 2
    assert wire.constructors[0]["max_retries"] == 0
    assert wire.constructors[0]["open_telemetry"] is False
    assert wire.constructors[0]["base_url"] == "https://api.anthropic.com"
    assert all(client.is_closed() for client in wire.clients)
    sent = json.loads(wire.requests[-1].content)
    assert sent["stream"] is False and sent["max_tokens"] == 1024
    assert "tools" not in sent and "cache_control" not in sent
    context = json.loads(sent["messages"][0]["content"])
    assert context["failure_source"] == current["payload"]["failure_source"]
    assert context["history_view"] == current["payload"]["history_view"]
    with module.journal.connection() as db:
        record = json.loads(db.execute("SELECT body FROM model_observations WHERE call_id=?", (current["call_id"],)).fetchone()[0])
    assert record["response"]["id"] == "msg_offline" and record["preflight_input_tokens"] == 20
    assert "unit-test-credential" not in json.dumps(record)


def test_rules_default_never_uses_anthropic_even_with_key(tmp_path, wire):
    module = BModule(state_dir=tmp_path / "rules", runner=SyntheticRunner())
    result = checked(module, diagnosis_request(module))
    assert result["usage"]["model_calls"] == 0 and not wire.requests
    assert module.capabilities()["extensions"]["srp_b"]["diagnosis"] == "rule_based"


def test_public_factory_and_original_o_loader_accept_sdk_options(tmp_path, wire):
    definitions = {name: {"factory": "reliable_codegen.mocks:create_mock_module",
                         "options": {"service": name}} for name in ("A", "C")}
    definitions["B"] = {
        "factory": "srp_b:create_module", "options": {"state_dir": str(tmp_path / "factory"),
        "diagnosis_backend": "anthropic", "anthropic_model": "claude-test"}}
    transport = build_transport({"transport": "local", "modules": definitions})
    capability = transport.capabilities("B")
    assert capability["extensions"]["srp_b"]["model"] == "claude-test"
    assert capability["extensions"]["srp_b"]["max_model_calls_per_diagnosis"] == 1
    assert capability["supported_diagnosis_modes"] == ["static_feedback", "feedback_only"]
    assert not wire.requests


def test_sdk_not_installed_is_explicitly_blocked(tmp_path, wire, monkeypatch):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    original = builtins.__import__
    def without_sdk(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("SENSITIVE_IMPORT_DETAILS")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_sdk)
    result = checked(module, current)
    assert result["data"]["reason"] == "ANTHROPIC_SDK_NOT_INSTALLED" and not wire.requests


def test_actual_o_two_round_history_with_sdk_wire_transport(tmp_path, wire):
    from reliable_codegen.mocks import create_mock_module
    from reliable_codegen.transport import LocalTransport
    from scripts.verify_p2_lineage import run_scenario
    from test_local_v2_p2_lineage import ScriptedRunner

    runner = ScriptedRunner(["failed", "failed", "passed", "passed"])
    module = BModule(state_dir=tmp_path / "b", runner=runner, diagnosis_backend="anthropic",
                     anthropic_model="claude-test")
    transport = LocalTransport({"A": create_mock_module(service="A"), "B": module,
                                "C": create_mock_module(service="C")}, timeout=15)
    result = run_scenario(transport, tmp_path / "o", "two_execution_failures")
    assert result["diagnosis_calls"] == 2 and result["physical_execution_calls"] == 4
    assert len(wire.requests) == 4
    last_input = json.loads(json.loads(wire.requests[-1].content)["messages"][0]["content"])
    assert last_input["prior_diagnosis"]["extensions"]["srp_b"]["model_calls"] == 1


def test_custom_environment_key_and_explicit_endpoint(tmp_path, wire, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("B_CLAUDE_KEY", "offline-custom-credential")
    module = configured(tmp_path, anthropic_api_key_env="B_CLAUDE_KEY",
                        anthropic_base_url="https://approved-gateway.invalid")
    result = checked(module, diagnosis_request(module))
    assert result["status"] == "completed"
    assert wire.constructors[0]["base_url"] == "https://approved-gateway.invalid"
    assert "offline-custom-credential" not in json.dumps(result)


@pytest.mark.parametrize("field,value,reason", [
    ("max_model_calls", 0, "MODEL_NOT_AUTHORIZED"),
    ("max_rounds", 0, "MODEL_NOT_AUTHORIZED"),
    ("max_input_tokens", 0, "MODEL_TOKENS_NOT_AUTHORIZED"),
    ("max_output_tokens", 0, "MODEL_TOKENS_NOT_AUTHORIZED"),
])
def test_no_provider_request_without_grant(tmp_path, wire, field, value, reason):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    current["payload"]["call_grant"][field] = value
    result = checked(module, current)
    assert result["status"] == "blocked" and result["data"]["reason"] == reason
    assert result["usage"]["model_calls"] == 0 and not wire.requests


def test_input_preflight_blocks_generation_above_grant(tmp_path, wire):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    wire.count = 8001
    result = checked(module, current)
    assert result["status"] == "blocked" and result["data"]["reason"] == "MODEL_INPUT_EXCEEDS_GRANT"
    assert len(wire.requests) == 1 and result["usage"]["model_calls"] == 0


def test_missing_key_is_explicit_and_never_sent(tmp_path, wire, monkeypatch):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    result = checked(module, current)
    assert result["status"] == "blocked" and result["data"]["reason"] == "ANTHROPIC_API_KEY_MISSING"
    assert not wire.requests and result["usage"]["model_calls"] == 0


def test_no_observations_does_not_create_model_hypotheses(tmp_path, wire):
    module = configured(tmp_path)
    result = checked(module, diagnosis_request(module, source="def add(a,b):\n    return a+b\n"))
    assert result["status"] == "completed" and not result["data"]["diagnosis_report"]["hypotheses"]
    assert result["usage"]["model_calls"] == 0 and not wire.requests


def test_completed_replay_survives_restart_without_second_model_charge(tmp_path, wire):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    ledger = BudgetLedger(seconds=60)
    current["payload"]["call_grant"] = ledger.issue(current["call_id"], DIAGNOSE, {
        "max_input_tokens": 8000, "reserved_output_tokens": 1024,
        "max_evidence_tokens": 0, "target_tokenizer_id": "provider-count-fixture"})
    current["payload"]["budget"] = ledger.snapshot()
    first = module.call(DIAGNOSE, current)
    ledger.settle(current["call_id"], first["payload"]["usage"])
    second = configured(tmp_path).call(DIAGNOSE, current)
    ledger.settle(current["call_id"], second["payload"]["usage"])
    assert first == second and len(wire.requests) == 2
    assert ledger.used["model_calls"] == 1 and ledger.used["tokens"] == 36 and not ledger.pending


def test_unknown_delivery_retains_budget_and_is_not_automatically_retried(tmp_path, wire):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    ledger = BudgetLedger(seconds=60)
    current["payload"]["call_grant"] = ledger.issue(current["call_id"], DIAGNOSE, {
        "max_input_tokens": 8000, "reserved_output_tokens": 1024,
        "max_evidence_tokens": 0, "target_tokenizer_id": "provider-count-fixture"})
    current["payload"]["budget"] = ledger.snapshot()
    wire.timeout = True
    first = module.call(DIAGNOSE, current)
    payload = first["payload"]
    assert payload["error"]["error_code"] == "ANTHROPIC_OUTCOME_UNKNOWN"
    assert payload["usage"]["input_tokens"] is payload["usage"]["model_calls"] is None
    assert payload["usage"]["execution_calls"] == 0
    ledger.settle(current["call_id"], payload["usage"])
    assert ledger.snapshot()["reserved"]["tokens"] == 9024
    assert ledger.snapshot()["reserved"]["model_calls"] == 1
    assert configured(tmp_path).call(DIAGNOSE, current) == first and len(wire.requests) == 2
    reference = payload["error"]["partial_result_ref"]
    assert module.resolve_fact(reference)["content_kind"] == "json"
    assert "SENSITIVE_PROVIDER_EXCEPTION" not in json.dumps(first)


@pytest.mark.parametrize("status,known", [(401, True), (429, True), (408, False), (500, False)])
def test_http_failures_do_not_retry_or_leak_provider_body(tmp_path, wire, status, known):
    module = configured(tmp_path)
    wire.status = status
    result = checked(module, diagnosis_request(module))
    assert result["status"] == "error" and len(wire.requests) == 2
    assert result["usage"]["model_calls"] == (0 if known else None)
    assert result["usage"]["execution_calls"] == 0
    assert "SENSITIVE_PROVIDER_EXCEPTION" not in json.dumps(result)


@pytest.mark.parametrize("change,code", [
    (lambda w: setattr(w, "explanation", "not JSON"), "ANTHROPIC_OUTPUT_INVALID"),
    (lambda w: w.explanation.update(evidence_indices=[999]), "ANTHROPIC_OUTPUT_INVALID"),
    (lambda w: w.explanation.update(evidence_indices=[True]), "ANTHROPIC_OUTPUT_INVALID"),
    (lambda w: w.explanation.update(evidence_indices=[0, 0]), "ANTHROPIC_OUTPUT_INVALID"),
    (lambda w: w.explanation.update(failure_source={}), "ANTHROPIC_OUTPUT_INVALID"),
    (lambda w: setattr(w, "stop_reason", "max_tokens"), "ANTHROPIC_OUTPUT_INCOMPLETE"),
    (lambda w: setattr(w, "stop_reason", "refusal"), "ANTHROPIC_OUTPUT_INCOMPLETE"),
])
def test_unusable_model_output_keeps_real_usage_and_original_facts(tmp_path, wire, change, code):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    change(wire)
    result = checked(module, current)
    assert result["status"] == "error" and result["error"]["error_code"] == code
    assert result["usage"]["model_calls"] == 1 and result["usage"]["input_tokens"] == 19
    original = module.resolve_fact(result["error"]["partial_result_ref"])
    assert json.loads(original["body_utf8"]) == current["payload"]["failure_source"]["static_report"]


def test_provider_overspend_is_reported_with_actual_usage(tmp_path, wire):
    module = configured(tmp_path, anthropic_max_tokens=32)
    wire.usage["output_tokens"] = 33
    result = checked(module, diagnosis_request(module))
    assert json.loads(wire.requests[-1].content)["max_tokens"] == 32
    assert result["error"]["error_code"] == "ANTHROPIC_PROVIDER_EXCEEDED_GRANT"
    assert result["usage"]["output_tokens"] == 33 and result["usage"]["model_calls"] == 1


@pytest.mark.parametrize("field,value", [("input_tokens", None), ("output_tokens", None),
                                        ("cache_read_input_tokens", -1)])
def test_incomplete_provider_usage_preserves_unknown_budget(tmp_path, wire, field, value):
    module = configured(tmp_path)
    wire.usage[field] = value
    result = checked(module, diagnosis_request(module))
    assert result["error"]["error_code"] == "ANTHROPIC_USAGE_UNKNOWN"
    assert result["usage"]["model_calls"] == 1 and result["usage"]["measurement"] == "unknown"
    assert result["usage"]["input_tokens"] is None or result["usage"]["output_tokens"] is None
    assert len(wire.requests) == 2


def test_expired_grant_never_calls_provider(tmp_path, wire):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    current["payload"]["call_grant"]["deadline_at"] = "2000-01-01T00:00:00Z"
    result = checked(module, current)
    assert result["data"]["reason"] == "DEADLINE_EXCEEDED" and not wire.requests


def test_deadline_is_rechecked_after_token_preflight(tmp_path, wire, monkeypatch):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    def expired(_):
        raise Blocked("DEADLINE_EXCEEDED")
    wire.after_count = lambda: monkeypatch.setattr(module, "_authorize", expired)
    result = checked(module, current)
    assert result["data"]["reason"] == "DEADLINE_EXCEEDED"
    assert result["usage"]["model_calls"] == 0 and len(wire.requests) == 1


def test_protected_diagnosis_is_rejected_before_sdk(tmp_path, wire):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    current["visibility"] = "restricted"
    with pytest.raises(TransportError):
        module.call(DIAGNOSE, current)
    assert not wire.requests


def test_pending_diagnosis_remains_unknown_across_backend_changes(tmp_path, wire):
    module = configured(tmp_path)
    current = diagnosis_request(module)
    module.journal.begin(DIAGNOSE, current)
    rules = BModule(state_dir=tmp_path / "state", runner=SyntheticRunner())
    result = checked(rules, current)
    assert result["error"]["error_code"] == "OUTCOME_UNKNOWN"
    assert result["usage"]["model_calls"] is result["usage"]["input_tokens"] is None
    assert result["usage"]["execution_calls"] == 0 and not wire.requests


@pytest.mark.parametrize("options", [
    {"anthropic_model": None}, {"anthropic_max_tokens": 0}, {"anthropic_max_tokens": True},
    {"anthropic_timeout_seconds": float("nan")}, {"anthropic_timeout_seconds": 0},
    {"anthropic_base_url": "http://api.example.com"},
    {"anthropic_base_url": "https://user:secret@api.example.com"},
    {"anthropic_base_url": "https://api.example.com?api_key=secret"},
    {"anthropic_api_key_env": "a secret value"},
])
def test_invalid_factory_configuration_is_rejected(tmp_path, options):
    config = {"diagnosis_backend": "anthropic", "anthropic_model": "claude-test", **options}
    with pytest.raises(ValueError):
        create_module(state_dir=str(tmp_path / "invalid"), **config)
