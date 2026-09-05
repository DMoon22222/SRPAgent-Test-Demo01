import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings
from app.repository.workspace import (
    DEFAULT_EXCLUDED_NAMES,
    DEFAULT_SNAPSHOT_ROOT_NAME,
    RepositorySnapshot,
    RepositoryWorkspaceError,
    RepositoryWorkspaceManager,
    _is_unsafe_link,
)


def workspace_tree(tmp_path):
    allowed = tmp_path / "allowed"
    repo = allowed / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("original\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_app():\n    assert True\n",
        encoding="utf-8",
    )
    return allowed, repo


def manager_for(tmp_path, allowed):
    return RepositoryWorkspaceManager(
        allowed_root=allowed,
        snapshot_root=tmp_path / "snapshots",
    )


def test_allowed_root_must_be_configured(tmp_path):
    manager = RepositoryWorkspaceManager(
        allowed_root="",
        snapshot_root=tmp_path / "snapshots",
    )

    with pytest.raises(
        RepositoryWorkspaceError,
        match="repository allowed root is not configured",
    ):
        manager.create_snapshot("repo")


def test_repository_allowed_root_loads_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("REPOSITORY_ALLOWED_ROOT", str(tmp_path))

    configured = Settings(_env_file=None)

    assert configured.repository_allowed_root == str(tmp_path)


def test_valid_absolute_workspace_resolves_canonically(tmp_path):
    allowed, repo = workspace_tree(tmp_path)

    resolved = manager_for(tmp_path, allowed).resolve_workspace(repo)

    assert resolved == repo.resolve()


def test_valid_relative_workspace_is_relative_to_allowed_root(tmp_path):
    allowed, repo = workspace_tree(tmp_path)

    resolved = manager_for(tmp_path, allowed).resolve_workspace("repo")

    assert resolved == repo.resolve()


def test_missing_workspace_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    with pytest.raises(RepositoryWorkspaceError, match="workspace does not exist"):
        manager_for(tmp_path, allowed).resolve_workspace("missing")


def test_workspace_file_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    file_path = allowed / "file.py"
    file_path.write_text("pass\n", encoding="utf-8")

    with pytest.raises(RepositoryWorkspaceError, match="not a directory"):
        manager_for(tmp_path, allowed).resolve_workspace(file_path)


def test_absolute_workspace_outside_allowed_root_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    with pytest.raises(RepositoryWorkspaceError, match="outside allowed root"):
        manager_for(tmp_path, allowed).resolve_workspace(outside)


def test_dotdot_escape_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    (tmp_path / "secret").mkdir()
    allowed.mkdir()

    with pytest.raises(RepositoryWorkspaceError, match="outside allowed root"):
        manager_for(tmp_path, allowed).resolve_workspace("../secret")


def test_different_drive_or_root_is_rejected_without_crashing(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    if os.name == "nt":
        foreign = Path(
            r"C:\foreign-repository"
            if allowed.drive.upper() != "C:"
            else r"D:\foreign-repository"
        )
    else:
        foreign = Path("/foreign-repository")

    with pytest.raises(RepositoryWorkspaceError, match="outside allowed root"):
        manager_for(tmp_path, allowed).resolve_workspace(foreign)


def test_workspace_root_link_is_rejected_deterministically(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    original = _is_unsafe_link

    with patch(
        "app.repository.workspace._is_unsafe_link",
        side_effect=lambda path: path == repo or original(path),
    ), pytest.raises(RepositoryWorkspaceError, match="unsafe link"):
        manager_for(tmp_path, allowed).resolve_workspace(repo)


def test_internal_link_is_rejected_deterministically(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    linked = repo / "secret_link"
    linked.write_text("placeholder\n", encoding="utf-8")
    original = _is_unsafe_link

    with patch(
        "app.repository.workspace._is_unsafe_link",
        side_effect=lambda path: path == linked or original(path),
    ), pytest.raises(RepositoryWorkspaceError, match="unsafe link"):
        manager_for(tmp_path, allowed).create_snapshot(repo)


def test_junction_detection_branch_is_deterministic(tmp_path):
    junction = tmp_path / "junction"
    junction.mkdir()

    with (
        patch.object(Path, "is_symlink", return_value=False),
        patch.object(Path, "is_junction", return_value=True),
    ):
        assert _is_unsafe_link(junction) is True


def test_snapshot_copies_regular_and_nested_files(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)

    snapshot = manager.create_snapshot(repo)
    try:
        assert (snapshot.snapshot_path / "src" / "app.py").read_text(
            encoding="utf-8"
        ) == "original\n"
        assert (snapshot.snapshot_path / "tests" / "test_app.py").is_file()
    finally:
        manager.cleanup_snapshot(snapshot)


def test_snapshot_excludes_server_owned_runtime_directories(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    for name in (".git", ".venv", "__pycache__", ".pico"):
        excluded = repo / name
        excluded.mkdir()
        (excluded / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    manager = manager_for(tmp_path, allowed)

    snapshot = manager.create_snapshot(repo)
    try:
        for name in (".git", ".venv", "__pycache__", ".pico"):
            assert not (snapshot.snapshot_path / name).exists()
            assert name in snapshot.excluded_paths
        assert DEFAULT_EXCLUDED_NAMES.issuperset(
            {".git", ".venv", "__pycache__"}
        )
    finally:
        manager.cleanup_snapshot(snapshot)


def test_snapshot_keeps_tests_and_project_manifests(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    manager = manager_for(tmp_path, allowed)

    snapshot = manager.create_snapshot(repo)
    try:
        assert (snapshot.snapshot_path / "tests").is_dir()
        assert (snapshot.snapshot_path / "pyproject.toml").is_file()
    finally:
        manager.cleanup_snapshot(snapshot)


def test_modifying_snapshot_does_not_modify_source(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)

    with manager.snapshot_workspace(repo) as snapshot:
        (snapshot.snapshot_path / "src" / "app.py").write_text(
            "modified\n",
            encoding="utf-8",
        )
        assert (repo / "src" / "app.py").read_text(encoding="utf-8") == (
            "original\n"
        )


def test_deleting_snapshot_file_does_not_delete_source(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)

    with manager.snapshot_workspace(repo) as snapshot:
        (snapshot.snapshot_path / "src" / "app.py").unlink()
        assert (repo / "src" / "app.py").is_file()


def test_context_manager_cleans_snapshot_on_normal_exit(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)

    with manager.snapshot_workspace(repo) as snapshot:
        snapshot_path = snapshot.snapshot_path
        assert snapshot_path.is_dir()

    assert not snapshot_path.exists()
    assert repo.is_dir()


def test_context_manager_cleans_snapshot_after_exception(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)
    snapshot_path = None

    with (
        pytest.raises(RuntimeError, match="future runner failed"),
        manager.snapshot_workspace(repo) as snapshot,
    ):
        snapshot_path = snapshot.snapshot_path
        raise RuntimeError("future runner failed")

    assert snapshot_path is not None
    assert not snapshot_path.exists()
    assert repo.is_dir()


def test_snapshot_path_is_outside_source_workspace(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)

    snapshot = manager.create_snapshot(repo)
    try:
        assert not snapshot.snapshot_path.is_relative_to(repo)
        assert snapshot.snapshot_path.parent == (tmp_path / "snapshots").resolve()
    finally:
        manager.cleanup_snapshot(snapshot)


def test_snapshot_root_inside_source_is_rejected(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = RepositoryWorkspaceManager(
        allowed_root=allowed,
        snapshot_root=repo / "snapshots",
    )

    with pytest.raises(
        RepositoryWorkspaceError,
        match="snapshot root must be outside",
    ):
        manager.create_snapshot(repo)


def test_cleanup_refuses_source_workspace(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)
    forged = RepositorySnapshot(
        snapshot_id="forged",
        source_path=repo,
        snapshot_path=repo,
    )

    with pytest.raises(RepositoryWorkspaceError, match="refusing to delete source"):
        manager.cleanup_snapshot(forged)

    assert repo.is_dir()
    assert (repo / "src" / "app.py").is_file()


def test_cleanup_refuses_unowned_directory(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = manager_for(tmp_path, allowed)
    foreign = tmp_path / "snapshots" / "repo_foreign"
    foreign.mkdir(parents=True)
    forged = RepositorySnapshot(
        snapshot_id="foreign",
        source_path=repo,
        snapshot_path=foreign,
    )

    with pytest.raises(RepositoryWorkspaceError, match="not owned"):
        manager.cleanup_snapshot(forged)

    assert foreign.is_dir()


def test_default_snapshot_root_uses_system_temp_directory(tmp_path):
    allowed, repo = workspace_tree(tmp_path)
    manager = RepositoryWorkspaceManager(allowed_root=allowed)

    snapshot = manager.create_snapshot(repo)
    try:
        assert snapshot.snapshot_path.parent == (
            Path(tempfile.gettempdir()) / DEFAULT_SNAPSHOT_ROOT_NAME
        )
    finally:
        manager.cleanup_snapshot(snapshot)
