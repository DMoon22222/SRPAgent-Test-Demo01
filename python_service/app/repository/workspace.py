"""Safe workspace validation and disposable repository snapshots."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import settings

DEFAULT_EXCLUDED_NAMES = frozenset(
    {
        ".git",
        ".idea",
        ".mypy_cache",
        ".pico",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)
DEFAULT_SNAPSHOT_ROOT_NAME = "srp_repository_snapshots"


class RepositoryWorkspaceError(ValueError):
    """Raised when a workspace or snapshot violates server policy."""


@dataclass(frozen=True)
class RepositorySnapshot:
    snapshot_id: str
    source_path: Path
    snapshot_path: Path
    excluded_paths: tuple[str, ...] = ()


class RepositoryWorkspaceManager:
    """Validate trusted local workspaces and create isolated copies."""

    def __init__(
        self,
        allowed_root: str | Path | None = None,
        *,
        snapshot_root: str | Path | None = None,
        excluded_names: frozenset[str] = DEFAULT_EXCLUDED_NAMES,
    ) -> None:
        configured_root = (
            settings.repository_allowed_root
            if allowed_root is None
            else str(allowed_root)
        )
        self._configured_allowed_root = configured_root
        self.snapshot_root = _absolute_path(
            snapshot_root
            if snapshot_root is not None
            else Path(tempfile.gettempdir()) / DEFAULT_SNAPSHOT_ROOT_NAME
        )
        self.excluded_names = frozenset(excluded_names)
        self._owned_snapshot_paths: set[Path] = set()

    def resolve_workspace(self, workspace_path: str | Path) -> Path:
        allowed_root = self._resolve_allowed_root()
        raw_workspace = str(workspace_path).strip()
        if not raw_workspace:
            raise RepositoryWorkspaceError("workspace path is empty")

        requested = Path(raw_workspace).expanduser()
        candidate = requested if requested.is_absolute() else allowed_root / requested
        lexical_candidate = _absolute_path(candidate)
        if not _is_relative_to(lexical_candidate, allowed_root):
            raise RepositoryWorkspaceError("workspace outside allowed root")

        _assert_path_components_safe(allowed_root, lexical_candidate)
        resolved = lexical_candidate.resolve(strict=False)
        if not _is_relative_to(resolved, allowed_root):
            raise RepositoryWorkspaceError("workspace outside allowed root")
        if not resolved.exists():
            raise RepositoryWorkspaceError("workspace does not exist")
        if not resolved.is_dir():
            raise RepositoryWorkspaceError("workspace is not a directory")
        if _is_unsafe_link(resolved):
            raise RepositoryWorkspaceError(f"unsafe link or reparse point: {resolved}")
        return resolved

    def validate_workspace(self, workspace_path: str | Path) -> Path:
        workspace = self.resolve_workspace(workspace_path)
        _scan_for_unsafe_links(workspace, self.excluded_names)
        return workspace

    def create_snapshot(self, workspace_path: str | Path) -> RepositorySnapshot:
        source = self.validate_workspace(workspace_path)
        snapshot_root = self.snapshot_root.resolve(strict=False)
        if _is_relative_to(snapshot_root, source):
            raise RepositoryWorkspaceError(
                "snapshot root must be outside the source workspace"
            )
        if _is_unsafe_link(snapshot_root):
            raise RepositoryWorkspaceError("snapshot root is an unsafe link")

        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot_root = snapshot_root.resolve(strict=True)
        snapshot_id = uuid4().hex
        snapshot_path = snapshot_root / f"repo_{snapshot_id}"
        snapshot_path.mkdir()
        self._owned_snapshot_paths.add(snapshot_path)
        excluded_paths: list[str] = []

        try:
            _copy_workspace(
                source,
                snapshot_path,
                excluded_names=self.excluded_names,
                excluded_paths=excluded_paths,
            )
            _scan_for_unsafe_links(snapshot_path, frozenset())
        except Exception:
            self._remove_owned_snapshot(snapshot_path)
            raise

        return RepositorySnapshot(
            snapshot_id=snapshot_id,
            source_path=source,
            snapshot_path=snapshot_path,
            excluded_paths=tuple(sorted(excluded_paths)),
        )

    def cleanup_snapshot(self, snapshot: RepositorySnapshot) -> None:
        candidate = _absolute_path(snapshot.snapshot_path)
        source = _absolute_path(snapshot.source_path)
        if candidate == source:
            raise RepositoryWorkspaceError("refusing to delete source workspace")
        if candidate not in self._owned_snapshot_paths:
            raise RepositoryWorkspaceError("snapshot is not owned by this manager")
        self._remove_owned_snapshot(candidate)

    @contextmanager
    def snapshot_workspace(
        self,
        workspace_path: str | Path,
    ) -> Iterator[RepositorySnapshot]:
        snapshot = self.create_snapshot(workspace_path)
        try:
            yield snapshot
        finally:
            self.cleanup_snapshot(snapshot)

    def _resolve_allowed_root(self) -> Path:
        if not self._configured_allowed_root.strip():
            raise RepositoryWorkspaceError(
                "repository allowed root is not configured"
            )
        lexical_root = _absolute_path(Path(self._configured_allowed_root).expanduser())
        if _is_unsafe_link(lexical_root):
            raise RepositoryWorkspaceError("repository allowed root is an unsafe link")
        resolved_root = lexical_root.resolve(strict=False)
        if not resolved_root.exists():
            raise RepositoryWorkspaceError("repository allowed root does not exist")
        if not resolved_root.is_dir():
            raise RepositoryWorkspaceError(
                "repository allowed root is not a directory"
            )
        return resolved_root

    def _remove_owned_snapshot(self, snapshot_path: Path) -> None:
        snapshot_root = self.snapshot_root.resolve(strict=False)
        candidate = _absolute_path(snapshot_path)
        if candidate not in self._owned_snapshot_paths:
            raise RepositoryWorkspaceError("snapshot is not owned by this manager")
        if candidate.parent != snapshot_root or not candidate.name.startswith("repo_"):
            raise RepositoryWorkspaceError("snapshot path failed cleanup validation")
        if _is_unsafe_link(candidate):
            raise RepositoryWorkspaceError("refusing to remove linked snapshot path")
        try:
            shutil.rmtree(candidate)
        finally:
            self._owned_snapshot_paths.discard(candidate)


def _absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _assert_path_components_safe(root: Path, candidate: Path) -> None:
    current = root
    if _is_unsafe_link(current):
        raise RepositoryWorkspaceError(f"unsafe link or reparse point: {current}")
    for part in candidate.relative_to(root).parts:
        current /= part
        if _is_unsafe_link(current):
            raise RepositoryWorkspaceError(
                f"unsafe link or reparse point: {current}"
            )


def _scan_for_unsafe_links(root: Path, excluded_names: frozenset[str]) -> None:
    with os.scandir(root) as entries:
        for entry in entries:
            path = Path(entry.path)
            if _is_unsafe_link(path):
                raise RepositoryWorkspaceError(
                    f"unsafe link or reparse point: {path}"
                )
            if entry.name in excluded_names:
                continue
            if entry.is_dir(follow_symlinks=False):
                _scan_for_unsafe_links(path, excluded_names)


def _copy_workspace(
    source: Path,
    destination: Path,
    *,
    excluded_names: frozenset[str],
    excluded_paths: list[str],
) -> None:
    with os.scandir(source) as entries:
        for entry in entries:
            source_path = Path(entry.path)
            relative_path = source_path.relative_to(source).as_posix()
            if _is_unsafe_link(source_path):
                raise RepositoryWorkspaceError(
                    f"unsafe link or reparse point: {source_path}"
                )
            if entry.name in excluded_names:
                excluded_paths.append(relative_path)
                continue

            destination_path = destination / entry.name
            if entry.is_dir(follow_symlinks=False):
                destination_path.mkdir()
                nested_excluded: list[str] = []
                _copy_workspace(
                    source_path,
                    destination_path,
                    excluded_names=excluded_names,
                    excluded_paths=nested_excluded,
                )
                excluded_paths.extend(
                    f"{entry.name}/{path}" for path in nested_excluded
                )
            elif entry.is_file(follow_symlinks=False):
                shutil.copy2(source_path, destination_path, follow_symlinks=False)
            else:
                raise RepositoryWorkspaceError(
                    f"unsupported filesystem entry: {source_path}"
                )


def _is_unsafe_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(attributes & reparse_flag)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RepositoryWorkspaceError(
            f"unable to inspect filesystem entry: {path}: {exc}"
        ) from exc
