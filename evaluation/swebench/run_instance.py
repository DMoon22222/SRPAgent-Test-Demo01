"""Run the existing Pilot CLI for one selected SWE-bench instance."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from evaluation.swebench import (
    DEFAULT_SWEBENCH_MAX_STEPS,
    DEFAULT_SWEBENCH_WALL_TIMEOUT_SECONDS,
)
from evaluation.swebench.common import (
    find_instance,
    load_selected,
    scrub_secrets,
    upsert_jsonl,
    utc_now,
)
from evaluation.swebench.export_prediction import export_model_patch, prediction_row
from evaluation.swebench.prepare_instance import prepare_instance

PROMPT_TEMPLATE = """You are working on a SWE-bench repository task.

Fix the issue described below in the current repository.

Use the available repository tools to inspect and modify the code.
Use execution/diagnosis tools when useful.
Make the smallest justified code change.
Do not modify unrelated files.
Do not access benchmark gold patches or reference solutions.
Do not claim success merely because a patch was applied.

You have a finite repository tool budget.
Use early tool calls to locate the relevant implementation, but avoid exhaustive
repository exploration. Once you have enough evidence for a concrete fix, stop
broad browsing and modify the repository. Do not finish by merely describing a
patch if a justified code fix can be applied with the available tools.
Reserve sufficient tool budget for:
1. at least one concrete code modification, and
2. when feasible, one validation or diagnosis attempt.

If repository execution is unavailable because the lightweight SRP sandbox lacks
project dependencies, do not repeatedly retry the same environment failure.
Continue using repository inspection and reasoning to make a justified source
patch when possible. Final benchmark correctness will be judged by the external
official SWE-bench harness.

Issue:

{problem_statement}
"""


def _latest_run_report(workspace: Path) -> tuple[dict[str, Any], Path | None]:
    reports = list((workspace / ".pico" / "runs").glob("*/report.json"))
    if not reports:
        return {}, None
    path = max(reports, key=lambda item: item.stat().st_mtime_ns)
    return json.loads(path.read_text(encoding="utf-8")), path


def _tool_call_count(report_path: Path | None) -> int:
    if report_path is None:
        return 0
    trace_path = report_path.with_name("trace.jsonl")
    if not trace_path.exists():
        return 0
    count = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(line).get("event") == "tool_executed":
                count += 1
        except json.JSONDecodeError:
            continue
    return count


def classify_agent_status(
    *,
    timed_out: bool,
    agent_completed: bool,
    patch_nonempty: bool,
    tool_budget_exhausted: bool,
) -> str:
    if timed_out:
        return "AGENT_TIMEOUT"
    if not agent_completed:
        return "AGENT_FAILED"
    if not patch_nonempty:
        return "NO_PATCH_TOOL_BUDGET" if tool_budget_exhausted else "NO_PATCH"
    return "AGENT_COMPLETED"


def run_instance(
    instance: dict[str, Any],
    *,
    workspaces_root: Path,
    codepilot_root: Path,
    results_dir: Path,
    provider: str,
    model: str,
    base_url: str | None,
    temperature: float,
    max_steps: int,
    max_new_tokens: int,
    max_repair_rounds: int,
    srp_enabled: bool,
    wall_timeout_seconds: int,
) -> dict[str, Any]:
    workspace = prepare_instance(instance, workspaces_root)
    prompt = PROMPT_TEMPLATE.format(
        problem_statement=instance["problem_statement"].strip()
    )
    pilot = codepilot_root / ".venv" / "Scripts" / "pilot.exe"
    command = [
        str(pilot),
        "--cwd",
        str(workspace),
        "--provider",
        provider,
        "--model",
        model,
        "--approval",
        "auto",
        "--max-steps",
        str(max_steps),
        "--max-new-tokens",
        str(max_new_tokens),
        "--temperature",
        str(temperature),
    ]
    if base_url:
        command.extend(["--base-url", base_url])
    command.append(prompt)

    run_env = os.environ.copy()
    run_env["PICO_SRP_ENABLED"] = "true" if srp_enabled else "false"
    run_env["PICO_SRP_MAX_REPAIR_ROUNDS"] = str(max_repair_rounds)
    started_at = utc_now()
    started = time.monotonic()
    timed_out = False
    return_code = 1
    output = ""
    try:
        completed = subprocess.run(
            command,
            cwd=codepilot_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=wall_timeout_seconds,
            check=False,
            env=run_env,
        )
        return_code = completed.returncode
        output = f"{completed.stdout}\n{completed.stderr}"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = f"{exc.stdout or ''}\n{exc.stderr or ''}"
    duration = time.monotonic() - started
    safe_output = scrub_secrets(output, run_env)
    logs_dir = results_dir / "agent_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{instance['instance_id']}.txt").write_text(
        safe_output[-20_000:], encoding="utf-8"
    )

    report, report_path = _latest_run_report(workspace)
    repair = report.get("repair_summary")
    if not isinstance(repair, dict):
        repair = {}
    patch, changed_files = export_model_patch(workspace, instance["base_commit"])
    model_name = f"CodePilot-SRP/{provider}/{model}"
    upsert_jsonl(
        results_dir / "predictions.jsonl",
        prediction_row(
            instance_id=instance["instance_id"],
            model_name_or_path=model_name,
            model_patch=patch,
        ),
        "instance_id",
    )

    final_answer = str(report.get("final_answer") or "")
    agent_completed = return_code == 0 and not timed_out
    tool_calls = _tool_call_count(report_path)
    tool_budget_exhausted = tool_calls >= max_steps
    agent_status = classify_agent_status(
        timed_out=timed_out,
        agent_completed=agent_completed,
        patch_nonempty=bool(patch),
        tool_budget_exhausted=tool_budget_exhausted,
    )
    row = {
        "instance_id": instance["instance_id"],
        "provider": provider,
        "model": model,
        "model_name_or_path": model_name,
        "temperature": temperature,
        "max_steps": max_steps,
        "max_repair_rounds": max_repair_rounds,
        "srp_enabled": srp_enabled,
        "started_at": started_at,
        "duration_seconds": round(duration, 3),
        "agent_completed": agent_completed,
        "agent_status": agent_status,
        "tool_calls": tool_calls,
        "tool_budget_exhausted": tool_budget_exhausted,
        "repair_attempts": int(repair.get("repair_attempts", 0)),
        "diagnosis_calls": int(repair.get("diagnosis_calls", 0)),
        "diagnosis_transitions": repair.get("diagnosis_transitions", []),
        "repeated_diagnosis": bool(repair.get("repeated_diagnosis", False)),
        "retrieval_requested": bool(repair.get("retrieval_requested", False)),
        "final_execution_status": str(repair.get("final_execution_status", "")),
        "patch_nonempty": bool(patch),
        "patch_chars": len(patch),
        "changed_files": changed_files,
        "agent_reported_success": bool(repair.get("repair_succeeded", False))
        or any(word in final_answer.lower() for word in ("fixed", "resolved", "success")),
        "official_resolved": None,
        "official_status": "PENDING_OFFICIAL_EVAL",
    }
    upsert_jsonl(results_dir / "agent_runs.jsonl", row, "instance_id")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--workspaces-root", type=Path, required=True)
    parser.add_argument("--codepilot-root", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--max-steps", type=int, default=DEFAULT_SWEBENCH_MAX_STEPS
    )
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--max-repair-rounds", type=int, default=3)
    parser.add_argument("--no-srp", action="store_true")
    parser.add_argument(
        "--wall-timeout",
        type=int,
        default=DEFAULT_SWEBENCH_WALL_TIMEOUT_SECONDS,
    )
    args = parser.parse_args(argv)
    instance = find_instance(load_selected(args.selected), args.instance_id)
    row = run_instance(
        instance,
        workspaces_root=args.workspaces_root,
        codepilot_root=args.codepilot_root.resolve(),
        results_dir=args.results_dir,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        max_repair_rounds=args.max_repair_rounds,
        srp_enabled=not args.no_srp,
        wall_timeout_seconds=args.wall_timeout,
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0 if row["agent_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
