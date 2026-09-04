from pico.evaluation.phase4 import run_phase4_benchmark


def test_phase4_benchmark_exercises_real_extension_paths(tmp_path):
    artifact = run_phase4_benchmark(
        output_root=tmp_path / "reports",
        workspace_root=tmp_path / "workspaces",
    )

    assert artifact["summary"]["case_count"] == 18
    assert artifact["skill"]["summary"]["with_skill_issue_detection_recall"] == 1.0
    assert artifact["skill"]["summary"]["baseline_issue_detection_recall"] == 0.0
    assert artifact["mcp"]["summary"]["tool_discovery_success_rate"] == 1.0
    assert artifact["mcp"]["summary"]["error_handling_rate"] == 1.0
    assert artifact["tool_governance"]["summary"]["approval_gate_rate"] == 1.0
    assert artifact["integrated"]["summary"]["task_success_rate"] == 1.0

    path_escape = next(
        row
        for row in artifact["tool_governance"]["rows"]
        if row["id"] == "governance_path_escape"
    )
    assert path_escape["passed"] is False
    assert path_escape["failure_category"] == "mcp_path_escape_contract_missing"
    assert "response id does not match" in path_escape["rejection"]

    final_report = artifact["report_paths"]["final"]
    assert final_report.endswith("phase4-final-benchmark-report.md")
    assert (tmp_path / "reports" / "phase4-benchmark-artifact.json").is_file()
