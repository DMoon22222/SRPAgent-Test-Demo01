"""Shared, dependency-free helpers for the SWE-bench MVP scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_PATH_PARTS = {
    ".pico",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
}
RUNTIME_PREFIXES = (".srp", "benchmark_logs", "evaluation_metadata")
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token)(\s*[:=]\s*)(\S+)"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    target.write_text(text, encoding="utf-8")


def upsert_jsonl(path: str | Path, row: dict[str, Any], key: str) -> None:
    rows = read_jsonl(path)
    updated = False
    for index, existing in enumerate(rows):
        if existing.get(key) == row.get(key):
            rows[index] = row
            updated = True
            break
    if not updated:
        rows.append(row)
    write_jsonl(path, rows)


def run_command(
    args: list[str],
    *,
    cwd: str | Path,
    timeout: int | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=Path(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
    )
    if check and result.returncode != 0:
        detail = scrub_secrets((result.stderr or result.stdout)[-2000:])
        raise RuntimeError(f"command failed ({result.returncode}): {detail}")
    return result


def scrub_secrets(text: Any, env: dict[str, str] | None = None) -> str:
    cleaned = str(text or "")
    source = env or os.environ
    for name, value in source.items():
        upper = name.upper()
        if value and any(token in upper for token in ("KEY", "TOKEN", "SECRET")):
            cleaned = cleaned.replace(value, "<redacted>")
    return SECRET_PATTERN.sub(r"\1\2<redacted>", cleaned)


def is_runtime_artifact(path: str | Path) -> bool:
    normalized = str(path).replace("\\", "/").removeprefix("./")
    parts = [part for part in normalized.split("/") if part]
    if any(part in RUNTIME_PATH_PARTS for part in parts):
        return True
    return any(part.startswith(RUNTIME_PREFIXES) for part in parts)


def load_selected(path: str | Path) -> list[dict[str, Any]]:
    value = read_json(path)
    if not isinstance(value, list):
        raise TypeError("selected_instances.json must contain a JSON array")
    required = {
        "instance_id",
        "repo",
        "base_commit",
        "problem_statement",
        "selection_reason",
    }
    for row in value:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError("selected instance is missing required public metadata")
    return value


def find_instance(rows: list[dict[str, Any]], instance_id: str) -> dict[str, Any]:
    for row in rows:
        if row["instance_id"] == instance_id:
            return row
    raise KeyError(f"instance not selected: {instance_id}")


def record_skip_reason(
    selected_path: str | Path,
    instance_id: str,
    reason: str,
) -> None:
    rows = load_selected(selected_path)
    row = find_instance(rows, instance_id)
    row["skip_reason"] = str(reason).strip()
    write_json(selected_path, rows)
