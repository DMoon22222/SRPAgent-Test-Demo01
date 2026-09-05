"""Prepare one fresh, isolated SWE-bench repository checkout."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from evaluation.swebench.common import find_instance, load_selected, run_command


def workspace_path(workspaces_root: str | Path, instance_id: str) -> Path:
    root = Path(workspaces_root).resolve()
    target = (root / instance_id).resolve()
    if target.parent != root or not instance_id or any(
        token in instance_id for token in ("/", "\\", "..")
    ):
        raise ValueError("unsafe instance workspace name")
    return target


def prepare_instance(
    instance: dict[str, Any],
    workspaces_root: str | Path,
) -> Path:
    root = Path(workspaces_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = workspace_path(root, instance["instance_id"])
    if target.exists():
        shutil.rmtree(target)

    repo_url = f"https://github.com/{instance['repo']}.git"
    run_command(
        ["git", "clone", "--filter=blob:none", "--no-checkout", repo_url, str(target)],
        cwd=root,
        timeout=600,
    )
    run_command(
        ["git", "checkout", "--detach", instance["base_commit"]],
        cwd=target,
        timeout=600,
    )
    head = run_command(["git", "rev-parse", "HEAD"], cwd=target).stdout.strip()
    if head != instance["base_commit"]:
        raise RuntimeError(f"base commit mismatch: {head}")
    if run_command(["git", "status", "--porcelain"], cwd=target).stdout.strip():
        raise RuntimeError("fresh instance workspace is unexpectedly dirty")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--workspaces-root", type=Path, required=True)
    args = parser.parse_args(argv)
    instance = find_instance(load_selected(args.selected), args.instance_id)
    print(prepare_instance(instance, args.workspaces_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
