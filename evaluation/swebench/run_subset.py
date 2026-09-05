"""Run the frozen subset sequentially with durable per-instance output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.swebench.common import load_selected, read_jsonl
from evaluation.swebench.run_instance import run_instance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--workspaces-root", type=Path, required=True)
    parser.add_argument("--codepilot-root", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--max-repair-rounds", type=int, default=3)
    parser.add_argument("--wall-timeout", type=int, default=900)
    parser.add_argument("--no-srp", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    completed_ids = {
        row["instance_id"]
        for row in read_jsonl(args.results_dir / "agent_runs.jsonl")
        if row.get("agent_status") in {
            "AGENT_COMPLETED",
            "NO_PATCH",
            "AGENT_TIMEOUT",
            "AGENT_FAILED",
        }
    }
    failures = 0
    for instance in load_selected(args.selected):
        instance_id = instance["instance_id"]
        if instance_id in completed_ids and not args.force:
            print(f"skip completed: {instance_id}")
            continue
        try:
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
            print(json.dumps(row, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 - preserve completed subset results
            failures += 1
            print(f"instance failed without losing prior results: {instance_id}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
