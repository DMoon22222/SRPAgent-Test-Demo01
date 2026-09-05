"""Export a clean SWE-bench model_patch from a disposable Agent workspace."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evaluation.swebench.common import (
    is_runtime_artifact,
    run_command,
    upsert_jsonl,
)


def _nul_paths(output: str) -> list[str]:
    return [item for item in output.split("\0") if item]


def export_model_patch(
    workspace: str | Path,
    base_commit: str,
) -> tuple[str, list[str]]:
    root = Path(workspace).resolve()
    head = run_command(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if head != base_commit:
        raise RuntimeError("Agent changed HEAD; model_patch must remain based on base_commit")

    tracked = _nul_paths(
        run_command(
            ["git", "diff", "--name-only", "-z", base_commit],
            cwd=root,
        ).stdout
    )
    untracked = _nul_paths(
        run_command(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root,
        ).stdout
    )
    allowed_untracked = [path for path in untracked if not is_runtime_artifact(path)]
    for path in allowed_untracked:
        run_command(["git", "add", "--intent-to-add", "--", path], cwd=root)

    changed_files = sorted(
        {
            path
            for path in [*tracked, *allowed_untracked]
            if not is_runtime_artifact(path)
        }
    )
    if not changed_files:
        return "", []
    patch = run_command(
        ["git", "diff", "--binary", base_commit, "--", *changed_files],
        cwd=root,
    ).stdout
    return patch, changed_files


def prediction_row(
    *,
    instance_id: str,
    model_name_or_path: str,
    model_patch: str,
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "model_name_or_path": model_name_or_path,
        "model_patch": model_patch,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args(argv)
    patch, _files = export_model_patch(args.workspace, args.base_commit)
    upsert_jsonl(
        args.predictions,
        prediction_row(
            instance_id=args.instance_id,
            model_name_or_path=args.model_name,
            model_patch=patch,
        ),
        "instance_id",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
