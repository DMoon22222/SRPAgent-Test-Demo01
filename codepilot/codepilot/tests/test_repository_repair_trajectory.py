import json

from pico.repair_trajectory import RepairTrajectory


def patch(trajectory, *paths):
    trajectory.observe_tool(
        "patch_file",
        {},
        "patched",
        {
            "tool_status": "ok",
            "workspace_changed": True,
            "affected_paths": list(paths),
        },
    )


def diagnose(
    trajectory,
    *,
    status="TEST_FAILED",
    subtype="ALGORITHM_ERROR",
    location="tests/test_demo.py:7",
    need_retrieval=False,
):
    success = status == "SUCCESS"
    diagnosis = None if success else {
        "errorType": "WRONG_ANSWER",
        "errorSubtype": subtype,
        "suspectedLocation": location,
        "needRetrieval": need_retrieval,
        "retrievalQuery": "pytest assertion semantics" if need_retrieval else "",
    }
    content = {
        "executionStatus": status,
        "failedStage": "NONE" if success else "TEST",
        "success": success,
        "failingTests": [] if success else ["tests/test_demo.py::test_value"],
    }
    if diagnosis:
        content["diagnosis"] = diagnosis
    return trajectory.observe_tool(
        "execute_repository_and_diagnose",
        {},
        json.dumps(content),
        {
            "tool_status": "ok",
            "execution_status": status,
            "failed_stage": content["failedStage"],
            "error_type": "" if success else "WRONG_ANSWER",
            "error_subtype": "" if success else subtype,
        },
    )


def test_repository_boundary_counts_multiple_pending_files_as_one_attempt():
    trajectory = RepairTrajectory(None, max_rounds=3)
    patch(trajectory, "src/a.py", "src/b.py")
    diagnose(trajectory)
    summary = trajectory.summary()
    assert summary["repair_attempts"] == 1
    assert summary["pending_patch_paths"] == []
    assert summary["trajectory"][0]["patch_affected_paths"] == [
        "src/a.py",
        "src/b.py",
    ]
    assert summary["trajectory"][0]["diagnosis_mode"] == "repository"


def test_repository_same_fingerprint_twice_marks_repeated_diagnosis():
    trajectory = RepairTrajectory(None, max_rounds=3)
    patch(trajectory, "src/a.py")
    diagnose(trajectory)
    patch(trajectory, "src/b.py")
    content, metadata = diagnose(trajectory)
    assert json.loads(content)["repeatedDiagnosis"] is True
    assert metadata["repeated_diagnosis"] is True
    assert trajectory.summary()["repair_attempts"] == 2


def test_repository_changed_diagnosis_resets_repeat_counter():
    trajectory = RepairTrajectory(None, max_rounds=3)
    diagnose(trajectory, subtype="ALGORITHM_ERROR")
    diagnose(trajectory, subtype="DEPENDENCY_MISSING")
    summary = trajectory.summary()
    assert summary["repeated_diagnosis"] is False
    assert summary["diagnosis_transitions"][-1]["changed"] is True


def test_repository_infrastructure_failure_does_not_count_diagnosis_or_attempt():
    trajectory = RepairTrajectory(None, max_rounds=3)
    patch(trajectory, "src/a.py", "src/b.py")
    trajectory.observe_tool(
        "execute_repository_and_diagnose",
        {},
        json.dumps({"executionStatus": "SANDBOX_ERROR"}),
        {
            "tool_status": "ok",
            "repository_infrastructure_failure": True,
            "tool_error_code": "repository_sandbox_error",
        },
    )
    summary = trajectory.summary()
    assert summary["diagnosis_calls"] == 0
    assert summary["repair_attempts"] == 0
    assert summary["pending_patch_paths"] == ["src/a.py", "src/b.py"]
    assert len(summary["infrastructure_failures"]) == 1


def test_repository_retrieval_signal_is_preserved():
    trajectory = RepairTrajectory(None, max_rounds=3)
    diagnose(trajectory, need_retrieval=True)
    summary = trajectory.summary()
    assert summary["retrieval_requested"] is True
    assert summary["retrieval_queries"] == ["pytest assertion semantics"]


def test_repository_success_closes_pending_attempt_and_marks_repair_success():
    trajectory = RepairTrajectory(None, max_rounds=3)
    patch(trajectory, "src/a.py", "tests/test_a.py")
    diagnose(trajectory, status="SUCCESS")
    summary = trajectory.summary()
    assert summary["repair_attempts"] == 1
    assert summary["repair_succeeded"] is True
    assert summary["final_execution_status"] == "SUCCESS"


def test_repository_third_failed_attempt_reaches_existing_round_limit():
    trajectory = RepairTrajectory(None, max_rounds=3)
    for index in range(3):
        patch(trajectory, f"src/change_{index}.py")
        _content, metadata = diagnose(
            trajectory,
            subtype=f"ERROR_{index}",
            location=f"src/change_{index}.py:1",
        )
    assert metadata["repair_round_limit_exceeded"] is True
    assert trajectory.summary()["repair_stop_reason"] == "repair_round_limit"
