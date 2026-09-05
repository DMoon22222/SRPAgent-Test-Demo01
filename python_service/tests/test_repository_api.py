from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import _execute_repository_request, app
from app.repository.workspace import (
    RepositoryWorkspaceError,
    RepositoryWorkspaceManager,
)
from app.schemas import (
    RepositoryExecution,
    RepositoryExecutionRequest,
    RepositoryObservation,
    RepositoryTestSummary,
)

client = TestClient(app)


def successful_execution():
    return RepositoryExecution(
        success=True,
        status="SUCCESS",
        failedStage="NONE",
        runner="pytest",
        timeout=False,
        exitCode=0,
        executionTimeMs=20,
        summary=RepositoryTestSummary(total=1, passed=1),
        observation=RepositoryObservation(runner="pytest", status="SUCCESS"),
    )


def test_repository_endpoint_executes_snapshot_and_returns_analysis_null():
    manager = MagicMock()
    snapshot = SimpleNamespace(snapshot_path=Path(r"F:\temp\snapshot"))
    manager.snapshot_workspace.return_value.__enter__.return_value = snapshot
    runner = MagicMock()
    runner.run.return_value = successful_execution()

    with (
        patch("app.main.RepositoryWorkspaceManager", return_value=manager),
        patch("app.main.DockerPytestRepositoryRunner", return_value=runner),
    ):
        response = client.post(
            "/api/execute-repository",
            json={
                "workspacePath": r"F:\temp\project",
                "runner": "pytest",
                "testTargets": ["tests/test_math.py"],
                "timeoutSeconds": 60,
            },
        )

    assert response.status_code == 200
    assert response.json()["execution"]["status"] == "SUCCESS"
    assert response.json()["analysis"] is None
    manager.snapshot_workspace.assert_called_once_with(r"F:\temp\project")
    snapshot_arg, run_spec = runner.run.call_args.args
    assert snapshot_arg == snapshot.snapshot_path
    assert run_spec.test_targets == ("tests/test_math.py",)
    assert not hasattr(run_spec, "workspacePath")


def test_workspace_error_is_structured_environment_error():
    manager = MagicMock()
    manager.snapshot_workspace.side_effect = RepositoryWorkspaceError(
        "workspace outside allowed root"
    )

    with patch("app.main.RepositoryWorkspaceManager", return_value=manager):
        response = client.post(
            "/api/execute-repository",
            json={"workspacePath": r"F:\outside"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["status"] == "ENVIRONMENT_ERROR"
    assert body["execution"]["failedStage"] == "PRE_CHECK"
    assert body["analysis"] is None


def test_repository_endpoint_rejects_invalid_timeout_before_handler():
    response = client.post(
        "/api/execute-repository",
        json={"workspacePath": r"F:\temp\project", "timeoutSeconds": 0},
    )

    assert response.status_code == 422


def test_repository_endpoint_rejects_unsupported_runner_before_handler():
    response = client.post(
        "/api/execute-repository",
        json={"workspacePath": r"F:\temp\project", "runner": "maven"},
    )

    assert response.status_code == 422


def test_repository_endpoint_rejects_arbitrary_command():
    response = client.post(
        "/api/execute-repository",
        json={
            "workspacePath": r"F:\temp\project",
            "command": "pytest && remove-files",
        },
    )

    assert response.status_code == 422


def test_repository_endpoint_rejects_unsafe_test_target_before_handler():
    response = client.post(
        "/api/execute-repository",
        json={
            "workspacePath": r"F:\temp\project",
            "testTargets": ["--maxfail=1"],
        },
    )

    assert response.status_code == 422


def test_real_snapshot_manager_fake_runner_preserves_original(tmp_path):
    allowed = tmp_path / "allowed"
    source = allowed / "repo"
    source.mkdir(parents=True)
    original_file = source / "module.py"
    original_file.write_text("original\n", encoding="utf-8")
    manager = RepositoryWorkspaceManager(
        allowed_root=allowed,
        snapshot_root=tmp_path / "snapshots",
    )
    seen_snapshot = None

    class FakeRunner:
        def run(self, snapshot_path, run_spec):
            nonlocal seen_snapshot
            seen_snapshot = snapshot_path
            (snapshot_path / "module.py").write_text("changed\n", encoding="utf-8")
            assert run_spec.runner == "pytest"
            return successful_execution()

    result = _execute_repository_request(
        RepositoryExecutionRequest(workspacePath=str(source)),
        manager,
        FakeRunner(),
    )

    assert result.execution.success is True
    assert original_file.read_text(encoding="utf-8") == "original\n"
    assert seen_snapshot is not None
    assert not seen_snapshot.exists()
