import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pico.integrations import SrpClient, SrpToolProvider
from pico.repair_trajectory import RepairTrajectory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SRP_REPOSITORY_TOOL_SMOKE") != "1",
    reason="set RUN_SRP_REPOSITORY_TOOL_SMOKE=1 with a real local SRP service",
)


def test_real_repository_tool_failure_then_repair_success():
    workspace = Path(os.environ["SRP_REPOSITORY_SMOKE_WORKSPACE"]).resolve()
    source = workspace / "calc.py"
    original = source.read_text(encoding="utf-8")
    provider = SrpToolProvider(
        SrpClient(
            base_url=os.getenv("PICO_SRP_BASE_URL", "http://127.0.0.1:8080"),
            timeout_seconds=90,
            enabled=True,
        )
    )
    context = SimpleNamespace(root=workspace)
    trajectory = RepairTrajectory(None, max_rounds=3)

    try:
        failed = provider.execute_repository(context, {"timeout_seconds": 30})
        failed_body = json.loads(failed.content)
        assert failed_body["executionStatus"] == "TEST_FAILED"
        assert failed_body["diagnosis"]["errorType"] != "UNKNOWN"
        assert failed_body["failingTests"]

        source.write_text(
            "def add(left, right):\n    return left + right\n",
            encoding="utf-8",
        )
        trajectory.observe_tool(
            "patch_file",
            {"path": "calc.py"},
            "patched calc.py",
            {
                "tool_status": "ok",
                "workspace_changed": True,
                "affected_paths": ["calc.py"],
            },
        )
        succeeded = provider.execute_repository(context, {"timeout_seconds": 30})
        success_body = json.loads(succeeded.content)
        content, _metadata = trajectory.observe_tool(
            "execute_repository_and_diagnose",
            {},
            succeeded.content,
            {"tool_status": "ok", **succeeded.metadata},
        )

        assert success_body["executionStatus"] == "SUCCESS"
        assert success_body["summary"]["failed"] == 0
        assert "diagnosis" not in success_body
        assert json.loads(content)["repairSucceeded"] is True
        assert trajectory.summary()["repair_attempts"] == 1
    finally:
        source.write_text(original, encoding="utf-8")
