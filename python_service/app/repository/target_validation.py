"""Validation for untrusted pytest target selectors."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


class RepositoryTargetError(ValueError):
    """Raised when a pytest selector escapes the fixed runner profile."""


_SHELL_META_CHARACTERS = frozenset(";&|`$<>")


def validate_target_selector(target: str) -> str:
    """Validate the syntax of one client-supplied pytest node id."""
    value = target.strip()
    if not value:
        raise RepositoryTargetError("test target must not be blank")
    if value.startswith("-"):
        raise RepositoryTargetError("pytest options are not valid test targets")
    if "\x00" in value or any(ord(char) < 32 for char in value):
        raise RepositoryTargetError("test target contains a control character")
    if any(char in value for char in _SHELL_META_CHARACTERS):
        raise RepositoryTargetError("test target contains a forbidden character")

    path_text, *selectors = value.split("::")
    if not path_text or any(not selector for selector in selectors):
        raise RepositoryTargetError("test target has an invalid pytest node id")
    if "\\" in path_text or ":" in path_text:
        raise RepositoryTargetError("test target paths must use forward slashes")

    posix_path = PurePosixPath(path_text)
    windows_path = PureWindowsPath(path_text)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise RepositoryTargetError("test target path must be relative")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise RepositoryTargetError("test target path contains traversal")
    return value


def validate_test_targets(
    snapshot_path: Path,
    targets: tuple[str, ...],
) -> tuple[str, ...]:
    """Ensure selectors resolve only to existing paths inside the snapshot."""
    snapshot = snapshot_path.resolve(strict=True)
    validated: list[str] = []
    for target in targets:
        value = validate_target_selector(target)
        path_text = value.split("::", 1)[0]
        try:
            candidate = (snapshot / Path(*PurePosixPath(path_text).parts)).resolve(
                strict=False
            )
        except OSError as exc:
            raise RepositoryTargetError("test target path is invalid") from exc
        if not _is_relative_to(candidate, snapshot):
            raise RepositoryTargetError("test target escapes the snapshot")
        if not candidate.exists():
            raise RepositoryTargetError(f"test target does not exist: {path_text}")
        validated.append(value)
    return tuple(validated)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except (ValueError, OSError):
        return False
    return True
