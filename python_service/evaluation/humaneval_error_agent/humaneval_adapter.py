from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_LOCAL_HUMANEVAL_REPO = Path("D:/human-eval")


def load_humaneval_problems() -> dict:
    read_problems = _import_read_problems()
    return read_problems()


def _import_read_problems():
    try:
        from human_eval.data import read_problems

        return read_problems
    except ImportError as exc:
        import_error = exc

    for repo_dir in _candidate_repo_dirs():
        package_dir = repo_dir / "human_eval"
        if package_dir.exists():
            sys.path.insert(0, str(repo_dir))
            try:
                from human_eval.data import read_problems

                return read_problems
            except ImportError as exc:
                import_error = exc

    raise RuntimeError(
        "human-eval is not installed and no local repo was found. "
        "Set HUMANEVAL_REPO_DIR to your local repo, or run "
        "`python -m pip install -e D:\\human-eval`."
    ) from import_error


def _candidate_repo_dirs() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("HUMANEVAL_REPO_DIR")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_LOCAL_HUMANEVAL_REPO)
    return candidates


def build_full_code(prompt: str, completion: str, test: str, entry_point: str, pass_marker: str) -> str:
    if not completion.endswith("\n"):
        completion += "\n"
    return (
        prompt
        + completion
        + "\n\n"
        + test
        + f"\n\ncheck({entry_point})\n"
        + f"print('{pass_marker}')\n"
    )
