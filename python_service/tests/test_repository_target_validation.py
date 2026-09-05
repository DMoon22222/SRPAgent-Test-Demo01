from pathlib import Path

import pytest

from app.repository.target_validation import (
    RepositoryTargetError,
    validate_target_selector,
    validate_test_targets,
)


@pytest.mark.parametrize(
    "target",
    [
        "tests/test_x.py",
        "tests/test_x.py::test_a",
        "tests/test_x.py::TestA::test_b",
    ],
)
def test_normal_pytest_node_ids_are_allowed(target):
    assert validate_target_selector(target) == target


@pytest.mark.parametrize(
    "target",
    [
        "",
        "   ",
        "-p",
        "--maxfail=1",
        "../test_x.py",
        "tests/../test_x.py",
        r"C:\secret\test.py",
        "/secret/test.py",
        "tests/test_x.py::",
        "tests/test_x.py\x00::test_a",
        "tests/test_x.py;whoami",
        "tests/test:x.py",
        "tests\\test_x.py",
    ],
)
def test_unsafe_pytest_targets_are_rejected(target):
    with pytest.raises(RepositoryTargetError):
        validate_target_selector(target)


def test_targets_must_exist_inside_snapshot(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "tests").mkdir(parents=True)
    (snapshot / "tests" / "test_x.py").write_text("pass\n", encoding="utf-8")

    assert validate_test_targets(
        snapshot,
        ("tests/test_x.py::test_a",),
    ) == ("tests/test_x.py::test_a",)

    with pytest.raises(RepositoryTargetError, match="does not exist"):
        validate_test_targets(snapshot, ("tests/test_missing.py",))


def test_snapshot_path_itself_is_resolved(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()

    assert validate_test_targets(Path(snapshot), ()) == ()
