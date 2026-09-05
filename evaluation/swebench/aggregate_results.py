"""Merge official Harness verdicts and produce preliminary subset metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import fmean
from typing import Any

from evaluation.swebench import DATASET_NAME
from evaluation.swebench.common import read_json, read_jsonl, write_json, write_jsonl


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    return fmean(float(row.get(key, 0)) for row in rows) if rows else None


def parse_official_verdicts(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    verdicts: dict[str, bool] = {}
    for key in ("resolved_ids", "resolved_instances"):
        items = value.get(key)
        if isinstance(items, list):
            verdicts.update({str(item): True for item in items})
    for key in ("unresolved_ids", "unresolved_instances"):
        items = value.get(key)
        if isinstance(items, list):
            verdicts.update({str(item): False for item in items})
    for instance_id, row in value.items():
        if isinstance(row, dict):
            resolved = row.get("resolved")
            if isinstance(resolved, bool):
                verdicts[str(instance_id)] = resolved
    return verdicts


def parse_official_errors(value: Any) -> set[str]:
    """Return Harness infrastructure/error IDs without treating them as failures."""
    if not isinstance(value, dict):
        return set()
    errors: set[str] = set()
    for key in ("error_ids", "infra_failure_ids"):
        items = value.get(key)
        if isinstance(items, list):
            errors.update(str(item) for item in items)
    return errors


def aggregate(
    runs: list[dict[str, Any]],
    *,
    subset_size: int,
    official_verdicts: dict[str, bool] | None = None,
    official_errors: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verdicts = official_verdicts or {}
    errors = official_errors or set()
    updated = []
    for source in runs:
        row = dict(source)
        if row["instance_id"] in verdicts:
            resolved = verdicts[row["instance_id"]]
            row["official_resolved"] = resolved
            row["official_status"] = (
                "RESOLVED" if resolved else "OFFICIAL_UNRESOLVED"
            )
        elif row["instance_id"] in errors:
            row["official_resolved"] = None
            row["official_status"] = "EVAL_INFRA_BLOCKED"
        updated.append(row)

    evaluated = [row for row in updated if isinstance(row.get("official_resolved"), bool)]
    resolved = [row for row in evaluated if row["official_resolved"]]
    diagnosed = [row for row in evaluated if int(row.get("diagnosis_calls", 0)) > 0]
    repaired_after_diagnosis = [row for row in diagnosed if row["official_resolved"]]
    summary = {
        "dataset": DATASET_NAME,
        "evaluation_scope": (
            f"Preliminary SWE-bench Verified fixed {subset_size}-instance subset"
        ),
        "selected_tasks": subset_size,
        "evaluated_tasks": len(evaluated),
        "pending_official_evaluation": subset_size - len(evaluated),
        "resolved_tasks": len(resolved),
        "unresolved_tasks": len(evaluated) - len(resolved),
        "evaluation_infra_blocked_tasks": sum(
            row.get("official_status") == "EVAL_INFRA_BLOCKED" for row in updated
        ),
        "resolve_rate": _ratio(len(resolved), len(evaluated)),
        "avg_tool_calls": _mean(evaluated, "tool_calls"),
        "avg_repair_attempts": _mean(evaluated, "repair_attempts"),
        "avg_diagnosis_calls": _mean(evaluated, "diagnosis_calls"),
        "diagnosis_triggered_tasks": len(diagnosed),
        "diagnosis_trigger_rate": _ratio(len(diagnosed), len(evaluated)),
        "repair_after_diagnosis_tasks": len(diagnosed),
        "repair_after_diagnosis_resolved": len(repaired_after_diagnosis),
        "repair_after_diagnosis_success_rate": _ratio(
            len(repaired_after_diagnosis), len(diagnosed)
        ),
        "avg_duration_seconds": _mean(evaluated, "duration_seconds"),
        "patch_generation_rate": _ratio(
            sum(bool(row.get("patch_nonempty")) for row in updated), len(updated)
        ),
        "retrieval_requested_count": sum(
            bool(row.get("retrieval_requested")) for row in updated
        ),
    }
    return updated, summary


def _format_metric(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "N/A"
    if percent:
        return f"{float(value):.2%}"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_summary(summary: dict[str, Any], runs: list[dict[str, Any]]) -> str:
    model = runs[0].get("model_name_or_path", "N/A") if runs else "N/A"
    lines = [
        "# SWE-bench Verified Preliminary Evaluation",
        "",
        f"Dataset: {summary['dataset']}",
        "",
        f"Subset: fixed {summary['selected_tasks']}-instance public subset",
        "",
        f"Model: {model}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    metrics = [
        ("Evaluated Tasks", "evaluated_tasks", False),
        ("Resolved Tasks", "resolved_tasks", False),
        ("Resolve Rate", "resolve_rate", True),
        ("Avg Tool Calls", "avg_tool_calls", False),
        ("Avg Repair Attempts", "avg_repair_attempts", False),
        ("Avg Diagnosis Calls", "avg_diagnosis_calls", False),
        ("Diagnosis Trigger Rate", "diagnosis_trigger_rate", True),
        (
            "Repair-after-Diagnosis Success Rate",
            "repair_after_diagnosis_success_rate",
            True,
        ),
        ("Avg Duration Seconds", "avg_duration_seconds", False),
        ("Patch Generation Rate", "patch_generation_rate", True),
    ]
    lines.extend(
        f"| {label} | {_format_metric(summary[key], percent=percent)} |"
        for label, key, percent in metrics
    )
    lines.extend(
        [
            "",
            "## Per-instance Results",
            "",
            "| Instance | Official Result | Tool Calls | Repairs | Diagnoses | Duration (s) |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in runs:
        lines.append(
            f"| {row['instance_id']} | {row.get('official_status', 'PENDING_OFFICIAL_EVAL')} "
            f"| {row.get('tool_calls', 0)} | {row.get('repair_attempts', 0)} "
            f"| {row.get('diagnosis_calls', 0)} | {row.get('duration_seconds', 0)} |"
        )
    lines.extend(
        [
            "",
            (
                "> This is a preliminary fixed-subset result, not the full "
                "500-instance SWE-bench Verified score."
            ),
            "",
            (
                "> Retrieval execution is not implemented in this MVP; only "
                "retrieval signals are counted."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_report_snapshot(summary: dict[str, Any], runs: list[dict[str, Any]]) -> str:
    model = runs[0].get("model_name_or_path", "N/A") if runs else "N/A"
    return "\n".join(
        [
            "# Phase 4.5-MVP 工作报告数据快照",
            "",
            (
                "当前完成能力：CLI Agent、Repository-safe Docker execution、Rule-first "
                "Error Diagnosis、Repair Loop、SWE-bench Adapter、Official Harness evaluation。"
            ),
            "",
            f"本次评测模型：{model}",
            f"固定子集：{summary['selected_tasks']} 个公开 SWE-bench Verified 实例",
            f"正式评测：{summary['evaluated_tasks']} 个",
            f"Resolved：{summary['resolved_tasks']} 个",
            f"Resolve Rate：{_format_metric(summary['resolve_rate'], percent=True)}",
            f"Avg Tool Calls：{_format_metric(summary['avg_tool_calls'])}",
            f"Avg Diagnosis Calls：{_format_metric(summary['avg_diagnosis_calls'])}",
            f"Avg Repairs：{_format_metric(summary['avg_repair_attempts'])}",
            "",
            "已知限制：small fixed subset、Python-first、无真实 Retrieval、无 Java/Maven。",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--official-results", type=Path)
    args = parser.parse_args(argv)
    runs = read_jsonl(args.results_dir / "agent_runs.jsonl")
    selected = read_json(args.selected)
    verdicts = {}
    errors: set[str] = set()
    if args.official_results and args.official_results.exists():
        official_results = read_json(args.official_results)
        verdicts = parse_official_verdicts(official_results)
        errors = parse_official_errors(official_results)
    updated, summary = aggregate(
        runs,
        subset_size=len(selected),
        official_verdicts=verdicts,
        official_errors=errors,
    )
    write_jsonl(args.results_dir / "agent_runs.jsonl", updated)
    write_json(args.results_dir / "summary.json", summary)
    (args.results_dir / "summary.md").write_text(
        render_summary(summary, updated), encoding="utf-8"
    )
    (args.results_dir / "report_snapshot.md").write_text(
        render_report_snapshot(summary, updated), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
