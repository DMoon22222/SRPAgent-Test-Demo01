import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.repository.workspace import DEFAULT_SNAPSHOT_ROOT_NAME

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REPOSITORY_DOCKER_SMOKE") != "1",
    reason="set RUN_REPOSITORY_DOCKER_SMOKE=1 for real Docker acceptance",
)

client = TestClient(app)


def _snapshot_entries() -> set[Path]:
    root = Path(tempfile.gettempdir()) / DEFAULT_SNAPSHOT_ROOT_NAME
    return set(root.glob("repo_*")) if root.exists() else set()


def _post_repository(workspace: Path, *, timeout: int = 30):
    return client.post(
        "/api/execute-repository",
        json={
            "workspacePath": str(workspace),
            "runner": "pytest",
            "testTargets": ["tests/test_calc.py"],
            "timeoutSeconds": timeout,
        },
    )


def test_real_success_and_original_workspace_isolation(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    repo = allowed / "repo_success"
    (repo / "tests").mkdir(parents=True)
    source = repo / "calc.py"
    original = "def add(a, b):\n    return a + b\n"
    source.write_text(original, encoding="utf-8")
    (repo / "tests" / "test_calc.py").write_text(
        "from pathlib import Path\n"
        "from calc import add\n\n"
        "def test_add_and_write_snapshot():\n"
        "    assert add(2, 3) == 5\n"
        "    Path('calc.py').write_text('snapshot changed\\n', encoding='utf-8')\n"
        "    Path('snapshot_marker.txt').write_text('created', encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "repository_allowed_root", str(allowed))
    before = _snapshot_entries()

    response = _post_repository(repo)

    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["success"] is True
    assert body["execution"]["status"] == "SUCCESS"
    assert body["execution"]["summary"]["passed"] >= 1
    assert body["execution"]["summary"]["failed"] == 0
    assert body["analysis"] is None
    assert source.read_text(encoding="utf-8") == original
    assert not (repo / "snapshot_marker.txt").exists()
    assert _snapshot_entries() == before


def test_real_test_failure_is_structured(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    repo = allowed / "repo_failed"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "repository_allowed_root", str(allowed))

    response = _post_repository(repo)

    assert response.status_code == 200
    body = response.json()
    execution = body["execution"]
    assert execution["success"] is False
    assert execution["status"] == "TEST_FAILED"
    assert execution["failedStage"] == "TEST"
    assert execution["summary"]["failed"] >= 1
    assert execution["failures"]
    assert execution["observation"]["failingTests"]
    assert body["analysis"] is None


def test_real_timeout_force_cleans_container(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    repo = allowed / "repo_timeout"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_calc.py").write_text(
        "def test_loop():\n"
        "    while True:\n"
        "        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "repository_allowed_root", str(allowed))

    response = _post_repository(repo, timeout=1)

    assert response.status_code == 200
    execution = response.json()["execution"]
    assert execution["status"] == "TIME_LIMIT_EXCEEDED"
    assert execution["failedStage"] == "TEST"
    assert execution["timeout"] is True
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=^/srp-repo-",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert containers.returncode == 0
    assert not containers.stdout.strip()
