import json
import subprocess

import pytest

from evaluation.swebench import (
    DEFAULT_SWEBENCH_MAX_STEPS,
    DEFAULT_SWEBENCH_WALL_TIMEOUT_SECONDS,
)
from evaluation.swebench.aggregate_results import (
    aggregate,
    parse_official_errors,
    parse_official_verdicts,
)
from evaluation.swebench.common import (
    is_runtime_artifact,
    load_selected,
    read_json,
    read_jsonl,
    record_skip_reason,
    upsert_jsonl,
    write_json,
)
from evaluation.swebench.export_prediction import export_model_patch, prediction_row
from evaluation.swebench.prepare_instance import remove_disposable_workspace
from evaluation.swebench.run_instance import classify_agent_status
from evaluation.swebench.select_instances import select_public_instances


def public_row(instance_id, difficulty="<15 min fix"):
    return {
        "instance_id": instance_id,
        "repo": "owner/repo",
        "base_commit": "a" * 40,
        "problem_statement": f"Fix {instance_id}",
        "difficulty": difficulty,
        "patch": "GOLD MUST NOT BE COPIED",
        "FAIL_TO_PASS": "HIDDEN",
    }


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "benchmark@example.invalid")
    git(tmp_path, "config", "user.name", "Benchmark Test")
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(tmp_path, "add", "module.py")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path, git(tmp_path, "rev-parse", "HEAD")


def test_instance_metadata_parsing_rejects_missing_public_fields(tmp_path):
    path = tmp_path / "selected.json"
    write_json(path, [{"instance_id": "only-id"}])
    with pytest.raises(ValueError, match="missing required"):
        load_selected(path)


def test_deterministic_selection_uses_public_difficulty_and_sorted_ids():
    rows = [public_row("z"), public_row("a"), public_row("b"), public_row("c", "1-4 hours")]
    selected = select_public_instances(rows, limit=2)
    assert [row["instance_id"] for row in selected] == ["a", "b"]
    assert all("patch" not in row and "FAIL_TO_PASS" not in row for row in selected)


def test_skip_reason_recording(tmp_path):
    selected = select_public_instances([public_row("a")], limit=1)
    path = tmp_path / "selected.json"
    write_json(path, selected)
    record_skip_reason(path, "a", "GOLD_ENV_FAILED")
    assert read_json(path)[0]["skip_reason"] == "GOLD_ENV_FAILED"


def test_remove_disposable_workspace_handles_readonly_files(tmp_path):
    target = tmp_path / "instance"
    target.mkdir()
    locked = target / "pack.idx"
    locked.write_bytes(b"git pack")
    locked.chmod(0o444)
    remove_disposable_workspace(target)
    assert not target.exists()


def test_patch_export_is_relative_to_base_commit(repo):
    root, base = repo
    (root / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    patch, files = export_model_patch(root, base)
    assert "-VALUE = 1" in patch
    assert "+VALUE = 2" in patch
    assert files == ["module.py"]


def test_patch_export_includes_untracked_source_file(repo):
    root, base = repo
    (root / "new_module.py").write_text("NEW = True\n", encoding="utf-8")
    patch, files = export_model_patch(root, base)
    assert "new_module.py" in patch
    assert "+NEW = True" in patch
    assert files == ["new_module.py"]


def test_patch_export_excludes_runtime_artifacts(repo):
    root, base = repo
    (root / ".pico").mkdir()
    (root / ".pico" / "session.json").write_text("{}")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"cache")
    patch, files = export_model_patch(root, base)
    assert patch == ""
    assert files == []
    assert is_runtime_artifact(".pico/session.json")


def test_empty_patch_is_preserved(repo):
    root, base = repo
    assert export_model_patch(root, base) == ("", [])


def test_predictions_jsonl_has_official_required_fields(tmp_path):
    path = tmp_path / "predictions.jsonl"
    row = prediction_row(
        instance_id="owner__repo-1",
        model_name_or_path="CodePilot-SRP/openai/model",
        model_patch="diff --git ...",
    )
    upsert_jsonl(path, row, "instance_id")
    assert read_jsonl(path) == [row]
    assert set(json.loads(path.read_text())) == {
        "instance_id",
        "model_name_or_path",
        "model_patch",
    }


def metric_run(instance_id, resolved, diagnoses=0):
    return {
        "instance_id": instance_id,
        "official_resolved": resolved,
        "tool_calls": 4,
        "repair_attempts": 1,
        "diagnosis_calls": diagnoses,
        "duration_seconds": 10,
        "patch_nonempty": True,
        "retrieval_requested": False,
        "max_steps": 60,
        "tool_budget_exhausted": False,
    }


def test_metrics_aggregation_and_resolve_rate():
    _runs, summary = aggregate(
        [metric_run("a", True), metric_run("b", False)], subset_size=2
    )
    assert summary["evaluated_tasks"] == 2
    assert summary["resolved_tasks"] == 1
    assert summary["resolve_rate"] == 0.5
    assert summary["avg_tool_calls"] == 4


def test_diagnosis_trigger_rate():
    _runs, summary = aggregate(
        [metric_run("a", True, 1), metric_run("b", False, 0)], subset_size=2
    )
    assert summary["diagnosis_trigger_rate"] == 0.5


def test_repair_after_diagnosis_success_rate():
    _runs, summary = aggregate(
        [metric_run("a", True, 1), metric_run("b", False, 2)], subset_size=2
    )
    assert summary["repair_after_diagnosis_success_rate"] == 0.5


def test_zero_denominators_are_null_not_fake_zero():
    _runs, summary = aggregate([], subset_size=3)
    assert summary["resolve_rate"] is None
    assert summary["diagnosis_trigger_rate"] is None
    assert summary["repair_after_diagnosis_success_rate"] is None
    assert summary["tool_budget_exhaustion_rate"] is None


def test_swebench_budget_defaults_are_repository_sized():
    assert DEFAULT_SWEBENCH_MAX_STEPS == 60
    assert DEFAULT_SWEBENCH_WALL_TIMEOUT_SECONDS == 1800


def test_no_patch_status_distinguishes_exhausted_budget():
    common = {
        "timed_out": False,
        "agent_completed": True,
        "patch_nonempty": False,
    }
    assert (
        classify_agent_status(**common, tool_budget_exhausted=True)
        == "NO_PATCH_TOOL_BUDGET"
    )
    assert (
        classify_agent_status(**common, tool_budget_exhausted=False) == "NO_PATCH"
    )


def test_tool_budget_exhaustion_metrics_are_inferred_for_baseline_rows():
    run = metric_run("a", None)
    run.pop("tool_budget_exhausted")
    run["max_steps"] = 12
    run["tool_calls"] = 12
    rows, summary = aggregate([run], subset_size=1)
    assert rows[0]["tool_budget_exhausted"] is True
    assert summary["tool_budget_exhausted_tasks"] == 1
    assert summary["tool_budget_exhaustion_rate"] == 1.0


def test_official_result_parser_supports_harness_summary_lists():
    verdicts = parse_official_verdicts(
        {"resolved_ids": ["a"], "unresolved_ids": ["b"], "error_ids": ["c"]}
    )
    assert verdicts == {"a": True, "b": False}
    assert parse_official_errors({"error_ids": ["c"]}) == {"c"}


def test_harness_infra_error_is_not_counted_as_unresolved():
    runs, summary = aggregate(
        [metric_run("a", None)],
        subset_size=1,
        official_errors={"a"},
    )
    assert runs[0]["official_resolved"] is None
    assert runs[0]["official_status"] == "EVAL_INFRA_BLOCKED"
    assert summary["evaluated_tasks"] == 0
    assert summary["unresolved_tasks"] == 0
    assert summary["evaluation_infra_blocked_tasks"] == 1
