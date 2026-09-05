"""Freeze a deterministic public SWE-bench Verified subset without gold data."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from evaluation.swebench import DATASET_NAME, DEFAULT_DIFFICULTY, DEFAULT_SUBSET_SIZE
from evaluation.swebench.common import write_json


def select_public_instances(
    rows: Iterable[dict[str, Any]],
    *,
    difficulty: str = DEFAULT_DIFFICULTY,
    limit: int = DEFAULT_SUBSET_SIZE,
) -> list[dict[str, Any]]:
    candidates = sorted(
        (row for row in rows if row.get("difficulty") == difficulty),
        key=lambda row: row["instance_id"],
    )
    selected = []
    for row in candidates[:limit]:
        selected.append(
            {
                "instance_id": row["instance_id"],
                "repo": row["repo"],
                "base_commit": row["base_commit"],
                "problem_statement": row["problem_statement"],
                "difficulty": row["difficulty"],
                "selection_reason": (
                    f"Public Verified difficulty={difficulty}; deterministic "
                    "ascending instance_id selection."
                ),
                "skip_reason": None,
            }
        )
    if len(selected) != limit:
        raise ValueError(f"only {len(selected)} matching instances; expected {limit}")
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_SUBSET_SIZE)
    parser.add_argument("--difficulty", default=DEFAULT_DIFFICULTY)
    args = parser.parse_args(argv)

    from datasets import load_dataset

    dataset = load_dataset(DATASET_NAME, split="test")
    write_json(
        args.output,
        select_public_instances(
            dataset,
            difficulty=args.difficulty,
            limit=args.limit,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
