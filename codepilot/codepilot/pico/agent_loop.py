"""Agent control loop extracted from the runtime facade."""

import time
from pathlib import PurePosixPath

from .checkpoint import (
    CHECKPOINT_NONE_STATUS,
    CHECKPOINT_PARTIAL_STALE_STATUS,
    CHECKPOINT_WORKSPACE_MISMATCH_STATUS,
)
from .task_state import TaskState
from .workspace import clip, now


def tool_budget_guidance(max_steps, used_steps):
    remaining = max(int(max_steps) - int(used_steps), 0)
    lines = [f"Tool budget: used = {used_steps}; remaining = {remaining}."]
    tier = "metadata"
    if remaining <= 5:
        tier = "critical"
        lines.extend(
            [
                "Runtime budget notice: 5 or fewer tool calls remain.",
                (
                    "Stop nonessential exploration. If a justified fix has been "
                    "identified, prioritize applying it now. Reserve the remaining "
                    "budget for at most the essential patch and validation actions."
                ),
            ]
        )
    elif remaining <= 10:
        tier = "modification"
        lines.extend(
            [
                "Runtime budget notice: 10 or fewer tool calls remain.",
                (
                    "If the available evidence supports a concrete fix, prioritize "
                    "applying the repository modification and validating it instead "
                    "of continuing broad exploration."
                ),
            ]
        )
    elif remaining <= 20:
        tier = "convergence"
        lines.extend(
            [
                "Runtime budget notice: 20 or fewer tool calls remain.",
                "Begin converging on a concrete fix. Avoid unnecessary exploratory browsing.",
            ]
        )
    return "\n".join(lines), remaining, tier


EXPLORATION_TOOLS = {"list_files", "search", "read_file"}
VALIDATION_TOOLS = {"execute_repository_and_diagnose"}
EARLY_FINAL_GUIDANCE = """This is a repository repair benchmark task.

The agent attempted to finalize before producing any repository source patch.

Only a small amount of investigation has been performed.

Do not finalize prematurely.

Continue investigating the repository and identify the most likely implementation
location that requires modification.

A final answer without a source patch is only appropriate after sufficient
investigation shows that no justified repository change can be made."""
SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
}


def source_patch_from_tool(name, metadata):
    if name not in {"patch_file", "write_file"} or not metadata.get(
        "workspace_changed"
    ):
        return False
    created_paths = {
        str(item).split(":", 1)[1].replace("\\", "/").lower()
        for item in metadata.get("diff_summary", [])
        if str(item).startswith("created:")
    }
    for raw_path in metadata.get("affected_paths", []):
        path = str(raw_path).replace("\\", "/").lstrip("./")
        lowered = path.lower()
        parts = PurePosixPath(lowered).parts
        name_lower = PurePosixPath(lowered).name
        if any(
            part in {".pico", ".pytest_cache", "__pycache__"}
            or part.startswith(".srp")
            or part in {"benchmark", "benchmarks"}
            for part in parts
        ):
            continue
        if lowered.startswith("evaluation/swebench/"):
            continue
        if any(word in name_lower for word in ("debug", "repro", "reproduction")):
            continue
        if lowered in created_paths and (
            name_lower.startswith("test_") or "tests" in parts
        ):
            continue
        if PurePosixPath(lowered).suffix in SOURCE_SUFFIXES:
            return True
    return False


def validation_environment_failure(metadata):
    status = str(metadata.get("execution_status", "")).upper()
    subtype = str(metadata.get("error_subtype", "")).upper()
    return status in {"ENVIRONMENT_ERROR", "SANDBOX_ERROR"} or subtype == (
        "DEPENDENCY_MISSING"
    )


def should_reject_patchless_final(
    *, source_patch_seen, tool_steps, patchless_final_guard_triggered
):
    return (
        not source_patch_seen
        and tool_steps < 8
        and not patchless_final_guard_triggered
    )


def tool_strategy_guidance(
    used_steps,
    *,
    source_patch_seen=False,
    validation_attempted=False,
    validation_environment_limited=False,
    stagnant_exploration_steps=0,
):
    if source_patch_seen:
        phase = "VERIFY"
        lines = [
            "A repository source patch has been applied.",
            "Prioritize validation over further broad exploration.",
            "Preferred next step: execute_repository_and_diagnose.",
            (
                "If validation produces useful new failure evidence, make one "
                "focused repair. If validation succeeds, finalize."
            ),
            (
                "Do not return to broad repository search unless validation provides "
                "new evidence that the current patch targets the wrong implementation."
            ),
        ]
    elif used_steps <= 25:
        phase = "EXPLORE"
        lines = [
            "You are still in the exploration phase.",
            "Locate the smallest relevant implementation surface.",
            "Avoid reading unrelated files.",
        ]
    elif used_steps <= 35:
        phase = "CONVERGE"
        lines = [
            "You are now in the convergence phase.",
            "Stop broad repository exploration.",
            (
                "If current evidence identifies a likely faulty implementation, focus "
                "on at most one or two candidate source files."
            ),
            (
                "Prefer targeted read then concrete patch over additional broad search "
                "and unrelated file inspection."
            ),
            (
                "Do not delay a justified source modification merely to gather "
                "redundant evidence."
            ),
        ]
    else:
        phase = "ACT"
        lines = [
            "You have spent substantial tool budget exploring the repository.",
            (
                "If a plausible root cause and target implementation have been "
                "identified, prioritize applying a concrete source patch now."
            ),
            "Do not continue broad list/search/read loops.",
            (
                "Limit further investigation to the smallest set of files directly "
                "related to the suspected implementation."
            ),
            (
                "A reproduction script, debug file, or standalone test alone does not "
                "count as a completed fix."
            ),
        ]
    if stagnant_exploration_steps >= 4:
        lines.extend(
            [
                "Recent exploration has not produced new actionable evidence.",
                "Do not repeat the same search/read pattern.",
                (
                    "Either apply the best justified source patch or inspect one "
                    "directly relevant unresolved location."
                ),
            ]
        )
    if validation_environment_limited:
        lines.extend(
            [
                (
                    "Repository validation is currently limited by the lightweight "
                    "SRP environment."
                ),
                "Do not repeatedly retry the same environment failure.",
                (
                    "Preserve the best justified source patch and finalize so that the "
                    "external SWE-bench Harness can perform authoritative evaluation."
                ),
            ]
        )
    elif source_patch_seen and validation_attempted:
        lines.extend(
            [
                (
                    "A source patch has already been produced and evaluated as far as "
                    "the current environment allows."
                ),
                "Avoid redundant exploration and finalize when no new evidence remains.",
            ]
        )
    return "\n".join(lines), phase


class AgentLoop:
    def __init__(self, agent):
        self.agent = agent

    def _persist_model_failure(self, task_state, user_message, exc, run_started_at, prompt_metadata):
        agent = self.agent
        error_text = agent.redact_text(str(exc))
        final = f"Model request failed: {error_text}"
        task_state.stop_model_error(final)
        agent.run_store.write_task_state(task_state)
        checkpoint = agent.create_checkpoint(task_state, user_message, trigger="model_error")
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            "model_failed",
            {
                "error": error_text,
                "completion_metadata": dict(agent.last_completion_metadata),
            },
        )
        agent.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.last_prompt_metadata = dict(prompt_metadata)
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))

    def _request_model(self, task_state, user_message, prompt, prompt_metadata, run_started_at, purpose):
        agent = self.agent
        agent.emit_trace(
            task_state,
            "model_requested",
            {
                "attempts": task_state.attempts,
                "tool_steps": task_state.tool_steps,
                "prompt_cache_key": prompt_metadata.get("prompt_cache_key"),
                "purpose": purpose,
            },
        )
        prompt_cache_key = None
        prompt_cache_retention = None
        if getattr(agent.model_client, "supports_prompt_cache", False):
            prompt_cache_key = prompt_metadata.get("prompt_cache_key")
            prompt_cache_retention = "in_memory"
        model_started_at = time.monotonic()
        try:
            raw = agent.model_client.complete(
                prompt,
                agent.max_new_tokens,
                prompt_cache_key=prompt_cache_key,
                prompt_cache_retention=prompt_cache_retention,
            )
        except Exception as exc:
            completion_metadata = dict(getattr(agent.model_client, "last_completion_metadata", {}) or {})
            if completion_metadata:
                prompt_metadata.update(completion_metadata)
            agent.last_completion_metadata = completion_metadata
            agent.last_prompt_metadata = prompt_metadata
            self._persist_model_failure(task_state, user_message, exc, run_started_at, prompt_metadata)
            raise
        completion_metadata = dict(getattr(agent.model_client, "last_completion_metadata", {}) or {})
        if completion_metadata:
            prompt_metadata.update(completion_metadata)
        agent.last_completion_metadata = completion_metadata
        agent.last_prompt_metadata = prompt_metadata
        kind, payload = agent.parse(raw)
        agent.emit_trace(
            task_state,
            "model_parsed",
            {
                "kind": kind,
                "completion_metadata": completion_metadata,
                "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                "purpose": purpose,
            },
        )
        return raw, kind, payload

    def _finish_success(self, task_state, user_message, final, run_started_at):
        agent = self.agent
        agent.record({"role": "assistant", "content": final, "created_at": now()})
        task_state.finish_success(final)
        agent.promote_durable_memory(user_message, final)
        checkpoint = agent.create_checkpoint(task_state, user_message, trigger="run_finished")
        agent.run_store.write_task_state(task_state)
        agent.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": "run_finished",
            },
        )
        agent.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
        return final

    def run(self, user_message):
        agent = self.agent
        run_started_at = time.monotonic()
        agent.memory.set_task_summary(user_message)
        agent.record({"role": "user", "content": user_message, "created_at": now()})

        task_state = TaskState.create(run_id=agent.new_run_id(), task_id=agent.new_task_id(), user_request=user_message)
        task_state.resume_status = agent.resume_state.get("status", CHECKPOINT_NONE_STATUS)
        agent.current_task_state = task_state
        agent.current_run_dir = agent.run_store.start_run(task_state)
        agent.emit_trace(
            task_state,
            "run_started",
            {
                "task_id": task_state.task_id,
                "user_request": clip(user_message, 300),
            },
        )

        tool_steps = 0
        attempts = 0
        source_patch_seen = False
        validation_attempted = False
        validation_environment_limited = False
        stagnant_exploration_steps = 0
        patchless_final_guard_triggered = False
        early_final_guidance_pending = False
        max_attempts = max(agent.max_steps * 3, agent.max_steps + 4)

        # 这是 agent 的主循环，可以按“感知 -> 决策 -> 行动 -> 记录”来理解：
        # 1. 感知：重新组 prompt，把当前状态整理给模型看
        # 2. 决策：让模型返回一个工具调用，或一个最终答案
        # 3. 行动：如果是工具调用，就执行工具
        # 4. 记录：把结果写回 history / task_state / trace / memory
        # 然后进入下一轮，直到停机条件满足
        while tool_steps < agent.max_steps and attempts < max_attempts:
            attempts += 1
            task_state.record_attempt()
            agent.run_store.write_task_state(task_state)
            prompt_started_at = time.monotonic()
            prompt, prompt_metadata = agent._build_prompt_and_metadata(user_message)
            budget_guidance, remaining_steps, budget_tier = tool_budget_guidance(
                agent.max_steps, tool_steps
            )
            prompt += f"\n\n{budget_guidance}"
            strategy_guidance, strategy_phase = tool_strategy_guidance(
                tool_steps,
                source_patch_seen=source_patch_seen,
                validation_attempted=validation_attempted,
                validation_environment_limited=validation_environment_limited,
                stagnant_exploration_steps=stagnant_exploration_steps,
            )
            prompt += f"\n\n{strategy_guidance}"
            if early_final_guidance_pending:
                prompt += f"\n\n{EARLY_FINAL_GUIDANCE}"
                early_final_guidance_pending = False
            prompt_metadata.update(
                {
                    "tool_budget_used": tool_steps,
                    "tool_budget_remaining": remaining_steps,
                    "tool_budget_notice_tier": budget_tier,
                    "tool_strategy_phase": strategy_phase,
                    "source_patch_seen": source_patch_seen,
                }
            )
            agent.emit_trace(
                task_state,
                "prompt_built",
                {
                    "prompt_metadata": prompt_metadata,
                    "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
                },
            )
            if prompt_metadata.get("resume_status") == CHECKPOINT_PARTIAL_STALE_STATUS:
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="freshness_mismatch")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "freshness_mismatch",
                    },
                )
            elif prompt_metadata.get("resume_status") == CHECKPOINT_WORKSPACE_MISMATCH_STATUS:
                agent.emit_trace(
                    task_state,
                    "runtime_identity_mismatch",
                    {
                        "fields": list(prompt_metadata.get("runtime_identity_mismatch_fields", [])),
                    },
                )
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="workspace_mismatch")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "workspace_mismatch",
                    },
                )
            if prompt_metadata.get("budget_reductions"):
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="context_reduction")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "context_reduction",
                    },
                )
            raw, kind, payload = self._request_model(
                task_state,
                user_message,
                prompt,
                prompt_metadata,
                run_started_at,
                purpose="action",
            )

            if kind == "tool":
                tool_steps += 1
                name = payload.get("name", "")
                args = payload.get("args", {})
                task_state.record_tool(name)
                tool_started_at = time.monotonic()
                tool_result = agent.execute_tool(name, args)
                result = tool_result.content
                tool_metadata = dict(tool_result.metadata or {})
                if source_patch_from_tool(name, tool_metadata):
                    source_patch_seen = True
                if name in VALIDATION_TOOLS and source_patch_seen:
                    validation_attempted = True
                    if validation_environment_failure(tool_metadata):
                        validation_environment_limited = True
                if name in EXPLORATION_TOOLS and not tool_metadata.get(
                    "workspace_changed"
                ):
                    stagnant_exploration_steps += 1
                else:
                    stagnant_exploration_steps = 0
                agent.record(
                    {
                        "role": "tool",
                        "name": name,
                        "args": args,
                        "content": result,
                        "created_at": now(),
                    }
                )
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "tool_executed",
                    {
                        "name": name,
                        "args": args,
                        "result": clip(result, 500),
                        "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                        **tool_metadata,
                    },
                )
                checkpoint = agent.create_checkpoint(task_state, user_message, trigger="tool_executed")
                agent.run_store.write_task_state(task_state)
                agent.emit_trace(
                    task_state,
                    "checkpoint_created",
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "trigger": "tool_executed",
                    },
                )
                continue

            if kind == "retry":
                agent.record({"role": "assistant", "content": payload, "created_at": now()})
                agent.run_store.write_task_state(task_state)
                continue

            if should_reject_patchless_final(
                source_patch_seen=source_patch_seen,
                tool_steps=tool_steps,
                patchless_final_guard_triggered=patchless_final_guard_triggered,
            ):
                patchless_final_guard_triggered = True
                early_final_guidance_pending = True
                agent.emit_trace(
                    task_state,
                    "early_final_rejected",
                    {"tool_steps": tool_steps, "source_patch_seen": False},
                )
                continue

            final = (payload or raw).strip()
            return self._finish_success(task_state, user_message, final, run_started_at)

        if tool_steps >= agent.max_steps:
            task_state.record_attempt()
            agent.run_store.write_task_state(task_state)
            prompt_started_at = time.monotonic()
            prompt, prompt_metadata = agent._build_prompt_and_metadata(user_message)
            budget_guidance, remaining_steps, budget_tier = tool_budget_guidance(
                agent.max_steps, tool_steps
            )
            prompt += f"\n\n{budget_guidance}"
            prompt += (
                "\n\nRuntime notice: the tool budget is exhausted. Do not call another tool. "
                "Use the evidence already present in the tool history and return exactly one "
                "non-empty <final>...</final> answer."
            )
            prompt_metadata.update(
                {
                    "finalization": True,
                    "tool_budget_used": tool_steps,
                    "tool_budget_remaining": remaining_steps,
                    "tool_budget_notice_tier": budget_tier,
                }
            )
            agent.emit_trace(
                task_state,
                "prompt_built",
                {
                    "prompt_metadata": prompt_metadata,
                    "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
                    "purpose": "finalization",
                },
            )
            raw, kind, payload = self._request_model(
                task_state,
                user_message,
                prompt,
                prompt_metadata,
                run_started_at,
                purpose="finalization",
            )
            if kind == "final":
                final = (payload or raw).strip()
                return self._finish_success(task_state, user_message, final, run_started_at)

        if attempts >= max_attempts and tool_steps < agent.max_steps:
            final = "Stopped after too many malformed model responses without a valid tool call or final answer."
            task_state.stop_retry_limit(final)
        else:
            final = "Stopped after reaching the step limit without a final answer."
            task_state.stop_step_limit(final)
        agent.record({"role": "assistant", "content": final, "created_at": now()})
        agent.promote_durable_memory(user_message, final)
        agent.run_store.write_task_state(task_state)
        checkpoint = agent.create_checkpoint(task_state, user_message, trigger=task_state.stop_reason or "run_stopped")
        agent.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": task_state.stop_reason or "run_stopped",
            },
        )
        agent.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        agent.run_store.write_report(task_state, agent.redact_artifact(agent.build_report(task_state)))
        return final
