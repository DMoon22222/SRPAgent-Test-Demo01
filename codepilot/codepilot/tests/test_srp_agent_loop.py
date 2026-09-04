import json

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.integrations import SrpToolProvider
from pico.tool_provider import BuiltinToolProvider


class FakeSrpClient:
    enabled = True

    def __init__(self):
        self.calls = []

    def execute_and_analyze(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "execution": {
                "success": False,
                "status": "WRONG_ANSWER",
                "failedStage": "TEST",
                "timeout": False,
                "exitCode": 0,
                "executionTimeMs": 8,
            },
            "analysis": {
                "failedStage": "TEST",
                "errorType": "WRONG_ANSWER",
                "errorSubtype": "ALGORITHM_ERROR",
                "rootCause": "The loop skips the final array element.",
                "evidence": ["expected 6 but got 5"],
                "suspectedLocation": "solution.py:2",
                "repairSuggestion": "Include the final index in the loop.",
                "needRetrieval": False,
                "retrievalQuery": "",
                "confidence": 0.96,
            },
        }


def test_agent_loop_receives_srp_diagnosis_before_next_decision(tmp_path):
    (tmp_path / "solution.py").write_text(
        "print(sum([1, 2, 3][:-1]))\n", encoding="utf-8"
    )
    model = FakeModelClient(
        [
            (
                '<tool>{"name":"execute_and_diagnose","args":'
                '{"path":"solution.py","problem":"sum values",'
                '"language":"python","expected_output":"6"}}</tool>'
            ),
            "<final>The SRP diagnosis is available for the next repair step.</final>",
        ]
    )
    client = FakeSrpClient()
    workspace = WorkspaceContext.build(tmp_path)
    agent = Pico(
        model_client=model,
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        tool_providers=[BuiltinToolProvider(), SrpToolProvider(client)],
    )

    answer = agent.ask("Run the solution in SRP and inspect its result")

    assert answer == "The SRP diagnosis is available for the next repair step."
    assert client.calls[0]["code"] == "print(sum([1, 2, 3][:-1]))\n"
    tool_message = next(
        item for item in agent.session["history"] if item.get("role") == "tool"
    )
    assert "The loop skips the final array element." in tool_message["content"]
    assert "The loop skips the final array element." in model.prompts[1]

    trace = agent.run_store.trace_path(agent.current_task_state).read_text(
        encoding="utf-8"
    )
    tool_event = next(
        event
        for event in map(json.loads, trace.splitlines())
        if event["event"] == "tool_executed"
    )
    assert tool_event["name"] == "execute_and_diagnose"
    assert tool_event["tool_status"] == "ok"
    assert tool_event["execution_status"] == "WRONG_ANSWER"
    assert tool_event["error_type"] == "WRONG_ANSWER"
