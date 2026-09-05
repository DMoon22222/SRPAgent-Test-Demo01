import json
from typing import ClassVar

import pytest

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.agent_loop import (
    AgentLoop,
    should_reject_patchless_final,
    source_patch_from_tool,
    tool_budget_guidance,
    tool_strategy_guidance,
)


def build_agent(tmp_path, outputs, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def test_agent_loop_runs_same_control_flow_as_pico_ask(tmp_path):
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
            "<final>Done.</final>",
        ],
    )

    answer = AgentLoop(agent).run("Inspect hello.txt")

    assert answer == "Done."
    assert agent.current_task_state.status == "completed"
    assert agent.run_store.report_path(agent.current_task_state.run_id).exists()


def test_pico_ask_delegates_to_agent_loop(tmp_path):
    agent = build_agent(tmp_path, ["<final>Facade works.</final>"])

    assert agent.ask("Use facade") == "Facade works."


def test_agent_loop_reserves_a_final_answer_after_tool_budget_is_exhausted(tmp_path):
    (tmp_path / "facts.txt").write_text("one\ntwo\nthree\nfour\nfive\nsix\n", encoding="utf-8")
    tool_outputs = [
        f'<tool>{{"name":"read_file","args":{{"path":"facts.txt","start":{line},"end":{line}}}}}</tool>'
        for line in range(1, 7)
    ]
    agent = build_agent(
        tmp_path,
        [*tool_outputs, "<final>All six facts were inspected.</final>"],
        max_steps=6,
    )

    answer = agent.ask("Inspect all facts and summarize them")

    assert answer == "All six facts were inspected."
    assert agent.current_task_state.status == "completed"
    assert agent.current_task_state.tool_steps == 6
    assert agent.current_task_state.attempts == 7
    trace_path = agent.run_store.trace_path(agent.current_task_state)
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(
        event["event"] == "model_requested" and event.get("purpose") == "finalization"
        for event in trace_events
    )
    assert "tool budget is exhausted" in agent.model_client.prompts[-1]
    assert "remaining = 0" in agent.model_client.prompts[-1]


def test_tool_budget_guidance_above_twenty_is_metadata_only():
    guidance, remaining, tier = tool_budget_guidance(60, 39)
    assert remaining == 21
    assert tier == "metadata"
    assert "used = 39; remaining = 21" in guidance
    assert "Runtime budget notice" not in guidance


@pytest.mark.parametrize(
    ("used", "expected_tier", "expected_notice"),
    [
        (40, "convergence", "20 or fewer tool calls remain"),
        (50, "modification", "prioritize applying the repository modification"),
        (55, "critical", "Stop nonessential exploration"),
    ],
)
def test_tool_budget_guidance_thresholds(used, expected_tier, expected_notice):
    guidance, _remaining, tier = tool_budget_guidance(60, used)
    assert tier == expected_tier
    assert expected_notice in guidance


@pytest.mark.parametrize(
    ("used", "phase", "notice"),
    [
        (25, "EXPLORE", "exploration phase"),
        (26, "CONVERGE", "convergence phase"),
        (36, "ACT", "prioritize applying a concrete source patch"),
    ],
)
def test_tool_strategy_phases(used, phase, notice):
    guidance, actual_phase = tool_strategy_guidance(used)
    assert actual_phase == phase
    assert notice in guidance


def test_source_patch_enters_verify_guidance():
    guidance, phase = tool_strategy_guidance(12, source_patch_seen=True)
    assert phase == "VERIFY"
    assert "execute_repository_and_diagnose" in guidance


def test_created_reproduction_test_is_not_a_source_patch():
    metadata = {
        "workspace_changed": True,
        "affected_paths": ["tests/test_reproduction.py"],
        "diff_summary": ["created:tests/test_reproduction.py"],
    }
    assert not source_patch_from_tool("write_file", metadata)
    assert source_patch_from_tool(
        "patch_file",
        {
            "workspace_changed": True,
            "affected_paths": ["package/implementation.py"],
            "diff_summary": ["modified:package/implementation.py"],
        },
    )


def test_environment_failure_guidance_prevents_repeat_validation():
    guidance, phase = tool_strategy_guidance(
        40,
        source_patch_seen=True,
        validation_attempted=True,
        validation_environment_limited=True,
    )
    assert phase == "VERIFY"
    assert "Do not repeatedly retry the same environment failure" in guidance


def test_early_final_guard_rejects_first_patchless_final_before_eight_tools():
    assert should_reject_patchless_final(
        source_patch_seen=False,
        tool_steps=3,
        patchless_final_guard_triggered=False,
    )


def test_early_final_guard_allows_second_patchless_final():
    assert not should_reject_patchless_final(
        source_patch_seen=False,
        tool_steps=3,
        patchless_final_guard_triggered=True,
    )


def test_early_final_guard_allows_final_after_source_patch():
    assert not should_reject_patchless_final(
        source_patch_seen=True,
        tool_steps=3,
        patchless_final_guard_triggered=False,
    )


def test_early_final_guard_allows_patchless_final_after_eight_tools():
    assert not should_reject_patchless_final(
        source_patch_seen=False,
        tool_steps=10,
        patchless_final_guard_triggered=False,
    )


def test_agent_loop_persists_model_failure_before_reraising(tmp_path):
    class FailingModelClient:
        supports_prompt_cache = False
        last_completion_metadata: ClassVar = {
            "stop_reason": "max_tokens",
            "content_block_types": ["thinking"],
        }

        def complete(self, *args, **kwargs):
            raise RuntimeError(
                "Anthropic-compatible response ended before a text block "
                "(stop_reason=max_tokens, content_types=thinking)"
            )

    agent = build_agent(tmp_path, [])
    agent.model_client = FailingModelClient()

    with pytest.raises(RuntimeError, match="ended before a text block"):
        agent.ask("Inspect the tests")

    state = agent.current_task_state
    assert state.status == "failed"
    assert state.stop_reason == "model_error"
    assert state.attempts == 1
    assert agent.run_store.task_state_path(state).exists()
    assert agent.run_store.report_path(state).exists()
    report = agent.run_store.load_report(state.run_id)
    assert report["stop_reason"] == "model_error"
    assert report["prompt_metadata"]["stop_reason"] == "max_tokens"
