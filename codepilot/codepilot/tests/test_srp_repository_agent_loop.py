from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.integrations import SrpToolProvider
from pico.tool_provider import BuiltinToolProvider


class FakeRepositorySrpClient:
    enabled = True

    def __init__(self):
        self.calls = []

    def execute_repository(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) > 1:
            return {
                "execution": {
                    "success": True,
                    "status": "SUCCESS",
                    "failedStage": "NONE",
                    "runner": "pytest",
                    "timeout": False,
                    "exitCode": 0,
                    "executionTimeMs": 12,
                    "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                    "failures": [],
                },
                "analysis": None,
            }
        return {
            "execution": {
                "success": False,
                "status": "TEST_FAILED",
                "failedStage": "TEST",
                "runner": "pytest",
                "timeout": False,
                "exitCode": 1,
                "executionTimeMs": 18,
                "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
                "failures": [
                    {
                        "testId": "tests/test_total.py::test_total",
                        "location": "tests/test_total.py:5",
                        "message": "assert 5 == 6",
                        "excerpt": "assert total(values) == 6",
                    }
                ],
                "stdout": "RAW-STDOUT-SENTINEL",
                "stderr": "RAW-STDERR-SENTINEL",
            },
            "analysis": {
                "failedStage": "TEST",
                "errorType": "WRONG_ANSWER",
                "errorSubtype": "ALGORITHM_ERROR",
                "rootCause": "The repository implementation skips one value.",
                "evidence": ["assert 5 == 6"],
                "suspectedLocation": "tests/test_total.py:5",
                "repairSuggestion": "Inspect the total loop.",
                "needRetrieval": False,
                "retrievalQuery": "",
                "confidence": 0.9,
            },
        }


def test_agent_loop_receives_compact_repository_diagnosis(tmp_path):
    (tmp_path / "solution.py").write_text("def total(xs): return sum(xs[:-1])\n")
    model = FakeModelClient(
        [
            (
                '<tool>{"name":"patch_file","args":{"path":"solution.py",'
                '"old_text":"return sum(xs[:-1])","new_text":'
                '"return sum(xs[:len(xs)-1])"}}</tool>'
            ),
            (
                '<tool>{"name":"execute_repository_and_diagnose","args":'
                '{"timeout_seconds":60}}</tool>'
            ),
            (
                '<tool>{"name":"patch_file","args":{"path":"solution.py",'
                '"old_text":"return sum(xs[:len(xs)-1])","new_text":'
                '"return sum(xs)"}}</tool>'
            ),
            (
                '<tool>{"name":"execute_repository_and_diagnose","args":'
                '{"timeout_seconds":60}}</tool>'
            ),
            "<final>Repository diagnosis received.</final>",
        ]
    )
    client = FakeRepositorySrpClient()
    workspace = WorkspaceContext.build(tmp_path)
    agent = Pico(
        model_client=model,
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        tool_providers=[BuiltinToolProvider(), SrpToolProvider(client)],
    )

    answer = agent.ask("Run the repository tests through SRP")

    assert answer == "Repository diagnosis received."
    assert client.calls
    assert client.calls[0]["workspace_path"] == str(tmp_path.resolve())
    assert len(client.calls) == 2
    tool_contents = [
        item["content"] for item in agent.session["history"] if item["role"] == "tool"
    ]
    diagnostic_content = next(
        content for content in tool_contents if "The repository implementation" in content
    )
    assert "RAW-STDOUT-SENTINEL" not in diagnostic_content
    assert "RAW-STDERR-SENTINEL" not in diagnostic_content
    assert "execute_repository_and_diagnose" in model.prompts[0]
    assert "The repository implementation skips one value." in model.prompts[2]
    assert (tmp_path / "solution.py").read_text() == "def total(xs): return sum(xs)\n"
    summary = agent.repair_trajectory.summary()
    assert summary["repair_attempts"] == 2
    assert summary["repair_succeeded"] is True
    assert summary["final_execution_status"] == "SUCCESS"
