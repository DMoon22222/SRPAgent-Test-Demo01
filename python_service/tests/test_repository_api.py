from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_repository_endpoint_returns_not_implemented_for_valid_request():
    with patch("app.main._select_sandbox") as select_sandbox:
        response = client.post(
            "/api/execute-repository",
            json={
                "workspacePath": r"F:\temp\project",
                "runner": "pytest",
                "testTargets": ["tests/test_math.py"],
                "timeoutSeconds": 60,
            },
        )

    assert response.status_code == 501
    assert "Repository Runner is not implemented" in response.json()["detail"]
    select_sandbox.assert_not_called()


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
