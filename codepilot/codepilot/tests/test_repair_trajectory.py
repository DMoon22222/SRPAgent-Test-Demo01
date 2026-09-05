import json
from unittest.mock import patch

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.integrations import SrpConnectionError, SrpToolProvider
from pico.repair_trajectory import (
    RepairTrajectory,
    diagnosis_fingerprint,
    normalize_diagnosis_location,
)
from pico.tool_provider import BuiltinToolProvider


class FakeSrpClient:
    enabled = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute_and_analyze(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def srp_response(
    status,
    *,
    subtype="",
    location="solution.py:1",
    need_retrieval=False,
    retrieval_query="",
):
    success = status == "SUCCESS"
    stage = {
        "SUCCESS": "NONE",
        "COMPILE_ERROR": "COMPILE",
        "RUNTIME_ERROR": "RUNTIME",
        "WRONG_ANSWER": "TEST",
    }[status]
    analysis = None
    if not success:
        analysis = {
            "failedStage": stage,
            "errorType": status,
            "errorSubtype": subtype,
            "rootCause": f"Root cause for {subtype}",
            "evidence": [f"Evidence for {subtype}"],
            "suspectedLocation": location,
            "repairSuggestion": f"Repair suggestion for {subtype}",
            "needRetrieval": need_retrieval,
            "retrievalQuery": retrieval_query,
            "confidence": 0.9,
        }
    return {
        "execution": {
            "success": success,
            "status": status,
            "failedStage": stage,
            "timeout": False,
            "exitCode": 0 if success else 1,
            "executionTimeMs": 5,
        },
        "analysis": analysis,
    }


def patch_call(old, new):
    payload = {
        "name": "patch_file",
        "args": {
            "path": "solution.py",
            "old_text": f"value = {old}",
            "new_text": f"value = {new}",
        },
    }
    return f"<tool>{json.dumps(payload)}</tool>"


def diagnose_call():
    payload = {
        "name": "execute_and_diagnose",
        "args": {"path": "solution.py", "language": "python"},
    }
    return f"<tool>{json.dumps(payload)}</tool>"


def build_agent(
    tmp_path,
    outputs,
    responses,
    *,
    max_steps=8,
    max_repair_rounds=3,
):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "solution.py").write_text("value = 0\n", encoding="utf-8")
    model = FakeModelClient(outputs)
    client = FakeSrpClient(responses)
    workspace = WorkspaceContext.build(tmp_path)
    agent = Pico(
        model_client=model,
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        max_steps=max_steps,
        max_repair_rounds=max_repair_rounds,
        tool_providers=[BuiltinToolProvider(), SrpToolProvider(client)],
    )
    return agent, model, client


def load_report(agent):
    return agent.run_store.load_report(agent.current_task_state.run_id)


def test_one_repair_attempt_records_verified_success(tmp_path):
    agent, model, _client = build_agent(
        tmp_path,
        [patch_call(0, 1), diagnose_call(), "<final>Verified fixed.</final>"],
        [srp_response("SUCCESS")],
    )

    assert agent.ask("Repair and verify solution.py") == "Verified fixed."

    summary = load_report(agent)["repair_summary"]
    assert summary["repair_attempts"] == 1
    assert summary["diagnosis_calls"] == 1
    assert summary["final_execution_status"] == "SUCCESS"
    assert summary["repair_succeeded"] is True
    assert summary["trajectory"][0]["patch_affected_paths"] == ["solution.py"]
    assert "Do not claim repair success" in model.prompts[0]


def test_two_repair_attempts_record_failure_then_success(tmp_path):
    agent, _model, _client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            patch_call(1, 2),
            diagnose_call(),
            "<final>Second repair verified.</final>",
        ],
        [
            srp_response("WRONG_ANSWER", subtype="ALGORITHM_ERROR"),
            srp_response("SUCCESS"),
        ],
    )

    agent.ask("Repair until SRP succeeds")

    summary = load_report(agent)["repair_summary"]
    assert summary["repair_attempts"] == 2
    assert summary["diagnosis_calls"] == 2
    assert [item["execution_status"] for item in summary["trajectory"]] == [
        "WRONG_ANSWER",
        "SUCCESS",
    ]
    assert summary["diagnosis_transitions"][0]["changed"] is True
    assert summary["repair_succeeded"] is True


def test_diagnosis_transition_records_change_without_quality_judgment(tmp_path):
    agent, _model, _client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            patch_call(1, 2),
            diagnose_call(),
            "<final>Stopped with a new remaining diagnosis.</final>",
        ],
        [
            srp_response("COMPILE_ERROR", subtype="SYNTAX_ERROR"),
            srp_response("RUNTIME_ERROR", subtype="DIVIDE_BY_ZERO"),
        ],
    )

    agent.ask("Attempt two repairs")

    summary = load_report(agent)["repair_summary"]
    transition = summary["diagnosis_transitions"][0]
    assert transition["changed"] is True
    assert "COMPILE_ERROR|COMPILE|COMPILE_ERROR|SYNTAX_ERROR" in transition["from"]
    assert "RUNTIME_ERROR|RUNTIME|RUNTIME_ERROR|DIVIDE_BY_ZERO" in transition["to"]
    assert "improved" not in transition
    assert summary["trajectory"][1]["diagnosis_changed"] is True


def test_repeated_diagnosis_adds_reconsideration_guidance(tmp_path):
    repeated = srp_response("WRONG_ANSWER", subtype="ALGORITHM_ERROR")
    agent, model, _client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            patch_call(1, 2),
            diagnose_call(),
            "<final>Stopping repeated approach.</final>",
        ],
        [repeated, repeated],
    )

    agent.ask("Repair without repeating an ineffective approach")

    summary = load_report(agent)["repair_summary"]
    assert summary["repeated_diagnosis"] is True
    assert summary["trajectory"][0]["repeated_diagnosis"] is False
    assert summary["trajectory"][1]["repeated_diagnosis"] is True
    assert "Previous repair attempts produced the same diagnosis" in model.prompts[-1]


def test_repair_round_limit_is_recorded_and_existing_step_limit_bounds_loop(tmp_path):
    failure = srp_response("WRONG_ANSWER", subtype="ALGORITHM_ERROR")
    agent, model, _client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            patch_call(1, 2),
            diagnose_call(),
            patch_call(2, 3),
            diagnose_call(),
            "<final>Repair round limit reached.</final>",
        ],
        [failure, failure, failure],
        max_steps=6,
        max_repair_rounds=3,
    )

    assert agent.ask("Try at most three repairs") == "Repair round limit reached."

    summary = load_report(agent)["repair_summary"]
    assert summary["repair_attempts"] == 3
    assert summary["repair_round_limit_exceeded"] is True
    assert summary["repair_stop_reason"] == "repair_round_limit"
    assert len(model.prompts) == 7
    assert agent.current_task_state.tool_steps == 6


def test_srp_unavailable_records_infrastructure_failure_not_diagnosis(tmp_path):
    agent, _model, _client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            "<final>SRP unavailable; code status is unknown.</final>",
        ],
        [SrpConnectionError("connection refused")],
    )

    agent.ask("Repair and diagnose")

    summary = load_report(agent)["repair_summary"]
    assert summary["repair_attempts"] == 0
    assert summary["diagnosis_calls"] == 0
    assert summary["diagnosis_transitions"] == []
    assert summary["infrastructure_failures"][0]["tool_error_code"] == "srp_unavailable"
    assert summary["pending_patch_paths"] == ["solution.py"]


def test_need_retrieval_is_recorded_without_calling_retrieval(tmp_path):
    agent, _model, client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            "<final>Dependency information is still needed.</final>",
        ],
        [
            srp_response(
                "RUNTIME_ERROR",
                subtype="DEPENDENCY_MISSING",
                need_retrieval=True,
                retrieval_query="install package demo-lib",
            )
        ],
    )

    agent.ask("Repair and diagnose dependency failure")

    summary = load_report(agent)["repair_summary"]
    assert summary["retrieval_requested"] is True
    assert summary["retrieval_queries"] == ["install package demo-lib"]
    assert summary["trajectory"][0]["need_retrieval"] is True
    assert len(client.calls) == 1
    assert "retrieval" not in agent.tools


def test_unrelated_patch_does_not_count_as_repair_attempt():
    trajectory = RepairTrajectory(None, max_rounds=3)
    trajectory.observe_tool(
        "patch_file",
        {"path": "README.md"},
        "patched README.md",
        {
            "tool_status": "ok",
            "workspace_changed": True,
            "affected_paths": ["README.md"],
        },
    )
    content = json.dumps(
        {
            "executionStatus": "SUCCESS",
            "failedStage": "NONE",
            "success": True,
        }
    )

    trajectory.observe_tool(
        "execute_and_diagnose",
        {"path": "solution.py"},
        content,
        {"tool_status": "ok", "execution_status": "SUCCESS"},
    )

    assert trajectory.summary()["repair_attempts"] == 0
    assert trajectory.summary()["pending_patch_paths"] == ["README.md"]


def test_fingerprint_uses_stable_fields_not_root_cause_text():
    stable = {
        "execution_status": "RUNTIME_ERROR",
        "failed_stage": "RUNTIME",
        "error_type": "RUNTIME_ERROR",
        "error_subtype": "DIVIDE_BY_ZERO",
        "suspected_location": "solution.py:2",
    }

    first = diagnosis_fingerprint({**stable, "root_cause": "wording one"})
    second = diagnosis_fingerprint({**stable, "root_cause": "wording two"})

    assert first == second
    assert first == (
        "RUNTIME_ERROR|RUNTIME|RUNTIME_ERROR|DIVIDE_BY_ZERO|solution.py:2"
    )


def test_fingerprint_ignores_random_srp_sandbox_directory():
    prefix = {
        "execution_status": "RUNTIME_ERROR",
        "failed_stage": "RUNTIME",
        "error_type": "API_MISUSE",
        "error_subtype": "DEPENDENCY_MISSING",
    }
    first_location = (
        r"F:\repo\python_service\.sandbox_tmp\srp_local_eb57c8af\Main.py:7"
    )
    second_location = (
        r"F:\repo\python_service\.sandbox_tmp\srp_local_911723d1\Main.py:7"
    )

    assert normalize_diagnosis_location(first_location) == "Main.py:7"
    assert diagnosis_fingerprint(
        {**prefix, "suspected_location": first_location}
    ) == diagnosis_fingerprint({**prefix, "suspected_location": second_location})
    assert normalize_diagnosis_location("astropy/utils/misc.py:123") == (
        "astropy/utils/misc.py:123"
    )


def test_repair_state_is_saved_in_checkpoint_and_restored_from_session(tmp_path):
    agent, _model, _client = build_agent(
        tmp_path,
        [
            patch_call(0, 1),
            diagnose_call(),
            "<final>Resume later.</final>",
        ],
        [srp_response("RUNTIME_ERROR", subtype="DIVIDE_BY_ZERO")],
    )
    agent.ask("Start a repair that may be resumed")
    checkpoint = agent.current_checkpoint()

    assert checkpoint["repair_summary"]["repair_attempts"] == 1
    assert "attempts=1" in agent.render_checkpoint_text()

    restored_client = FakeSrpClient([srp_response("SUCCESS")])
    restored = Pico.from_session(
        model_client=FakeModelClient([]),
        workspace=agent.workspace,
        session_store=agent.session_store,
        session_id=agent.session["id"],
        approval_policy="auto",
        max_repair_rounds=3,
        tool_providers=[BuiltinToolProvider(), SrpToolProvider(restored_client)],
    )

    assert restored.repair_summary()["repair_attempts"] == 1
    assert restored.repair_summary()["final_execution_status"] == "RUNTIME_ERROR"


def test_max_repair_rounds_uses_environment_configuration(tmp_path):
    with patch.dict(
        "os.environ", {"PICO_SRP_MAX_REPAIR_ROUNDS": "2"}, clear=False
    ):
        agent, _model, _client = build_agent(
            tmp_path,
            ["<final>No repair needed.</final>"],
            [],
            max_repair_rounds=None,
        )

    assert agent.max_repair_rounds == 2
