"""Independent Phase 4 MCP / Skill benchmark.

Unlike the locked harness benchmark, this module evaluates extension behavior.
Every case creates a fresh fixture copy and drives the normal ``Pico`` loop.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..mcp import MCPClient, MCPServerConfig
from ..mcp.provider import MCPToolProvider
from ..providers.clients import FakeModelClient
from ..run_store import RunStore
from ..runtime import Pico
from ..session_store import SessionStore
from ..tool_provider import BuiltinToolProvider
from ..workspace import WorkspaceContext

PHASE4_SCHEMA_VERSION = 1
CODE_REVIEW_SKILL = """---
keywords: review, code review, security, quality
---
# Code Review

Read the target before reaching a conclusion. Report input validation, exception
handling, security, and data-consistency risks with evidence and a repair idea.
"""
DEBUGGING_SKILL = """---
keywords: debug, debugging, bug, error, exception
---
# Debugging

First identify the observed failure, then inspect the smallest relevant code path,
state the root cause, and propose a minimal repair with a verification step.
"""


class ScenarioModelClient:
    """A deterministic prompt-aware model used only by Phase 4 evaluation.

    It does not call tools itself. It receives the actual prompt built by Pico and
    changes its declared strategy only when the real rendered Skill section exists.
    This makes the Skill comparison reproducible without claiming a provider-wide
    quality result.
    """

    supports_prompt_cache = False

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.prompts: list[str] = []
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, **kwargs):
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        step = len(self.prompts) - 1
        code_review = "[Skill: code_review]" in prompt
        debugging = "[Skill: debugging]" in prompt

        paths = {
            "review": "user_service.py",
            "debug": "calculator.py",
            "combination": "user_service.py",
            "integrated_review": "login.py",
            "integrated_both": "login.py",
        }
        if self.scenario in paths and step == 0:
            path = paths[self.scenario]
            return f'<tool>{{"name":"read_file","args":{{"path":"{path}","start":1,"end":120}}}}</tool>'
        if self.scenario == "integrated_both" and step == 1:
            return '<tool>{"name":"mcp.git-demo.git_diff","args":{}}</tool>'

        if self.scenario == "review":
            final = (
                "MISSING_PARAMETER_VALIDATION\nMISSING_EXCEPTION_HANDLING\n"
                "DATA_CONSISTENCY_RISK\nSECURITY_SQL_INJECTION"
                if code_review else "GENERAL_REVIEW_ONLY"
            )
        elif self.scenario == "debug":
            final = (
                "OBSERVED_FAILURE: division by zero\nROOT_CAUSE: count can be zero\n"
                "MINIMAL_REPAIR: validate count before division\nVERIFY: add zero-count test"
                if debugging else "GENERAL_DEBUG_ONLY"
            )
        elif self.scenario == "combination":
            final = (
                "COMBINED_REVIEW_AND_DEBUG\nMISSING_PARAMETER_VALIDATION\n"
                "ROOT_CAUSE: unsafe update path"
                if code_review and debugging else "PARTIAL_SKILL_RESULT"
            )
        elif self.scenario == "integrated_review":
            final = "LOGIN_REVIEW: SQL injection and plaintext password comparison" if code_review else "LOGIN_GENERAL_NOTE"
        elif self.scenario == "integrated_both":
            final = (
                "INTEGRATED_REPAIR: inspect git diff, parameterize the query, hash passwords, "
                "and reproduce login failure"
                if code_review and debugging else "INTEGRATED_PARTIAL"
            )
        else:
            final = "DONE"
        return f"<final>{final}</final>"


@dataclass
class Phase4BenchmarkRunner:
    """Runs Phase 4 extension cases without reading or changing locked benchmark data."""

    repo_root: Path | None = None
    output_root: Path | None = None
    workspace_root: Path | None = None

    def __post_init__(self):
        self.repo_root = Path(self.repo_root or Path(__file__).resolve().parents[2]).resolve()
        self.output_root = Path(self.output_root or self.repo_root / "benchmarks" / "reports").resolve()
        workspace_base = Path(self.workspace_root or self.output_root / "phase4-runs").resolve()
        run_label = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-%fZ")
        self.workspace_root = workspace_base / run_label
        self.fixture_root = self.repo_root / "benchmarks" / "phase4" / "fixtures"
        self.git_server = self.repo_root / "examples" / "mcp_server" / "git_analyzer.py"
        self.test_server = self.repo_root / "benchmarks" / "phase4" / "mcp" / "phase4_test_server.py"

    def run(self) -> dict:
        skill_rows = self._run_skill_cases()
        mcp_rows = self._run_mcp_cases()
        governance_rows = self._run_governance_cases()
        integrated_rows = self._run_integrated_cases()
        artifact = {
            "schema_version": PHASE4_SCHEMA_VERSION,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "python": sys.version.split()[0],
                "runtime": "Pico",
                "skill_mode": "deterministic prompt-aware client through Pico.ask",
                "mcp_mode": "real local stdio child processes",
                "mcp_servers": [str(self.git_server), str(self.test_server)],
                "workspace_root": str(self.workspace_root),
            },
            "skill": {"rows": skill_rows, "summary": self._skill_summary(skill_rows)},
            "mcp": {"rows": mcp_rows, "summary": self._mcp_summary(mcp_rows)},
            "tool_governance": {"rows": governance_rows, "summary": self._governance_summary(governance_rows)},
            "integrated": {"rows": integrated_rows, "summary": self._summary(integrated_rows)},
        }
        artifact["summary"] = self._summary(skill_rows + mcp_rows + governance_rows + integrated_rows)
        self.output_root.mkdir(parents=True, exist_ok=True)
        artifact_path = self.output_root / "phase4-benchmark-artifact.json"
        artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths = self._write_reports(artifact)
        artifact["report_paths"] = paths
        artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return artifact

    def _copy_fixture(self, case_id: str, fixture_name: str) -> Path:
        source = self.fixture_root / fixture_name
        target = self.workspace_root / case_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        # 让 WorkspaceContext 的 git 调用停在这份 fixture 内，而不是向上找到
        # CodePilot 主仓库；同时也使 Windows 下的 Git 输出保持局部、可重复。
        self._git(["init"], target)
        return target

    @staticmethod
    def _write_skills(workspace: Path, *skill_ids: str) -> None:
        content = {"code_review": CODE_REVIEW_SKILL, "debugging": DEBUGGING_SKILL}
        for skill_id in skill_ids:
            path = workspace / "skills" / skill_id / "skill.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content[skill_id], encoding="utf-8")

    def _agent(
        self,
        workspace: Path,
        model_client,
        *,
        providers=None,
        approval_policy="auto",
        allowed_tools=None,
        max_steps=4,
    ) -> Pico:
        return Pico(
            model_client=model_client,
            workspace=WorkspaceContext.build(workspace, repo_root_override=workspace),
            session_store=SessionStore(workspace / ".pico" / "sessions"),
            run_store=RunStore(workspace / ".pico" / "runs"),
            tool_providers=providers or [BuiltinToolProvider()],
            approval_policy=approval_policy,
            allowed_tools=allowed_tools,
            max_steps=max_steps,
        )

    @staticmethod
    def _trace(agent: Pico) -> list[dict]:
        path = agent.run_store.trace_path(agent.current_task_state.run_id)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    @staticmethod
    def _trace_complete(events: list[dict]) -> bool:
        names = {event.get("event") for event in events}
        return {"run_started", "model_requested", "model_parsed", "tool_executed", "run_finished"} <= names

    @staticmethod
    def _row(case_id, group, passed, *, agent=None, failure_category="", **details):
        row = {
            "id": case_id,
            "group": group,
            "status": "pass" if passed else "fail",
            "passed": bool(passed),
            "failure_category": "" if passed else (failure_category or "assertion_failed"),
            **details,
        }
        if agent is not None:
            events = Phase4BenchmarkRunner._trace(agent)
            row.update(
                {
                    "tool_steps": agent.current_task_state.tool_steps,
                    "tool_calls": [event.get("name") for event in events if event.get("event") == "tool_executed"],
                    "trace_path": str(agent.run_store.trace_path(agent.current_task_state.run_id)),
                    "report_path": str(agent.run_store.report_path(agent.current_task_state.run_id)),
                    "trace_complete": Phase4BenchmarkRunner._trace_complete(events),
                }
            )
        return row

    def _run_skill_case(
        self,
        case_id: str,
        fixture_name: str,
        scenario: str,
        prompt: str,
        expected_behavior,
        skill_ids=(),
        ground_truth=(),
    ):
        workspace = self._copy_fixture(case_id + ("_with_skill" if skill_ids else "_baseline"), fixture_name)
        self._write_skills(workspace, *skill_ids)
        client = ScenarioModelClient(scenario)
        agent = self._agent(workspace, client, allowed_tools=["read_file"], max_steps=3)
        try:
            answer = agent.ask(prompt)
            selected = agent.last_prompt_metadata.get("selected_skills", [])
            passed = all(marker in answer for marker in expected_behavior)
            return self._row(
                case_id,
                "skill",
                passed,
                agent=agent,
                failure_category="skill_behavior_missing",
                prompt=prompt,
                selected_skills=selected,
                skill_selection_matches_variant=bool(selected) == bool(skill_ids),
                issue_detection_count=sum(marker in answer for marker in ground_truth),
                expected_issue_count=len(ground_truth),
                final_answer=answer,
            )
        finally:
            agent.close()

    def _run_skill_cases(self) -> list[dict]:
        rows = []
        rows.extend(
            [
                self._run_skill_case(
                    "code_review_baseline", "review", "review", "Review this file for problems", ["GENERAL_REVIEW_ONLY"], ground_truth=("MISSING_PARAMETER_VALIDATION", "MISSING_EXCEPTION_HANDLING", "DATA_CONSISTENCY_RISK", "SECURITY_SQL_INJECTION")
                ),
                self._run_skill_case(
                    "code_review_with_skill", "review", "review", "Review this file for problems", ["MISSING_PARAMETER_VALIDATION", "MISSING_EXCEPTION_HANDLING", "DATA_CONSISTENCY_RISK", "SECURITY_SQL_INJECTION"], ("code_review",), ("MISSING_PARAMETER_VALIDATION", "MISSING_EXCEPTION_HANDLING", "DATA_CONSISTENCY_RISK", "SECURITY_SQL_INJECTION")
                ),
                self._run_skill_case(
                    "debug_baseline", "debug", "debug", "Debug this error", ["GENERAL_DEBUG_ONLY"], ground_truth=("ROOT_CAUSE", "MINIMAL_REPAIR", "VERIFY")
                ),
                self._run_skill_case(
                    "debug_with_skill", "debug", "debug", "Debug this error", ["ROOT_CAUSE", "MINIMAL_REPAIR", "VERIFY"], ("debugging",), ("ROOT_CAUSE", "MINIMAL_REPAIR", "VERIFY")
                ),
                self._run_skill_case(
                    "skill_combination", "review", "combination", "Debug and review this code", ["COMBINED_REVIEW_AND_DEBUG", "ROOT_CAUSE"], ("code_review", "debugging"), ("MISSING_PARAMETER_VALIDATION", "ROOT_CAUSE")
                ),
            ]
        )
        return rows

    def _mcp_provider(self, server_id: str, server_path: Path, workspace: Path, *, read_only, timeout=2):
        return MCPToolProvider(
            server_id,
            MCPClient(MCPServerConfig(command=[sys.executable, str(server_path)], cwd=str(workspace), timeout_seconds=timeout)),
            read_only_tools=set(read_only),
        )

    @staticmethod
    def _git(command, workspace: Path):
        subprocess.run(
            ["git", *command],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _initialize_git_fixture(self, workspace: Path):
        self._git(["config", "user.email", "phase4@example.test"], workspace)
        self._git(["config", "user.name", "Phase4 Benchmark"], workspace)
        self._git(["add", "."], workspace)
        self._git(["commit", "-m", "baseline login module"], workspace)
        path = workspace / "login.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# regression introduced in latest commit\n", encoding="utf-8")
        self._git(["add", "login.py"], workspace)
        self._git(["commit", "-m", "introduce login regression"], workspace)

    def _run_mcp_cases(self) -> list[dict]:
        rows = []
        workspace = self._copy_fixture("mcp_discovery", "integrated")
        self._initialize_git_fixture(workspace)
        provider = self._mcp_provider("git-demo", self.git_server, workspace, read_only={"git_diff", "git_history"})
        agent = self._agent(workspace, FakeModelClient([]), providers=[BuiltinToolProvider(), provider])
        try:
            names = set(agent.tools)
            rows.append(self._row("mcp_tool_discovery", "mcp", {"mcp.git-demo.git_diff", "mcp.git-demo.git_history"} <= names, discovered_tools=sorted(name for name in names if name.startswith("mcp."))))
        finally:
            agent.close()

        workspace = self._copy_fixture("mcp_invocation", "integrated")
        self._initialize_git_fixture(workspace)
        provider = self._mcp_provider("git-demo", self.git_server, workspace, read_only={"git_diff", "git_history"})
        agent = self._agent(
            workspace,
            FakeModelClient(['<tool>{"name":"mcp.git-demo.git_history","args":{"limit":1}}</tool>', "<final>Latest commit is introduce login regression.</final>"]),
            providers=[BuiltinToolProvider(), provider],
            allowed_tools=["mcp.git-demo.git_history"],
        )
        try:
            answer = agent.ask("查看最近一次 git 修改")
            events = self._trace(agent)
            tool = next((event for event in events if event.get("event") == "tool_executed"), {})
            passed = tool.get("name") == "mcp.git-demo.git_history" and "introduce login regression" in tool.get("result", "") and self._trace_complete(events)
            rows.append(self._row("mcp_tool_invocation", "mcp", passed, agent=agent, failure_category="mcp_invocation_or_trace_missing", final_answer=answer, observation=tool.get("result", "")))
        finally:
            agent.close()

        for name in ("tool_error", "invalid_json", "hang"):
            workspace = self._copy_fixture("mcp_error_" + name, "integrated")
            provider = self._mcp_provider("phase4", self.test_server, workspace, read_only={"echo", "tool_error", "invalid_json", "hang"}, timeout=0.1 if name == "hang" else 2)
            tool_name = f"mcp.phase4.{name}"
            agent = self._agent(
                workspace,
                FakeModelClient([f'<tool>{{"name":"{tool_name}","args":{{}}}}</tool>', "<final>Handled MCP error without crashing.</final>"]),
                providers=[BuiltinToolProvider(), provider],
                allowed_tools=[tool_name],
            )
            try:
                answer = agent.ask("Exercise MCP error handling")
                events = self._trace(agent)
                tool = next(event for event in events if event.get("event") == "tool_executed")
                passed = tool.get("tool_status") == "error" and "Handled MCP error" in answer and self._trace_complete(events)
                rows.append(self._row("mcp_error_" + name, "mcp", passed, agent=agent, failure_category="mcp_error_not_observed", tool_error_code=tool.get("tool_error_code"), observation=tool.get("result", ""), final_answer=answer))
            finally:
                agent.close()

        workspace = self._copy_fixture("mcp_multi_server", "integrated")
        self._initialize_git_fixture(workspace)
        git_provider = self._mcp_provider("git-demo", self.git_server, workspace, read_only={"git_diff", "git_history"})
        test_provider = self._mcp_provider("phase4", self.test_server, workspace, read_only={"echo"})
        agent = self._agent(workspace, FakeModelClient([]), providers=[BuiltinToolProvider(), git_provider, test_provider])
        try:
            names = set(agent.tools)
            expected = {"mcp.git-demo.git_diff", "mcp.git-demo.git_history", "mcp.phase4.echo"}
            rows.append(self._row("mcp_multi_server_isolation", "mcp", expected <= names, discovered_tools=sorted(name for name in names if name.startswith("mcp."))))
        finally:
            agent.close()
        return rows

    def _run_governance_cases(self) -> list[dict]:
        rows = []
        workspace = self._copy_fixture("governance_invalid_arguments", "integrated")
        provider = self._mcp_provider("phase4", self.test_server, workspace, read_only={"echo"})
        agent = self._agent(
            workspace,
            FakeModelClient(
                [
                    '<tool>{"name":"mcp.phase4.echo","args":{}}</tool>',
                    "<final>Invalid arguments were rejected.</final>",
                ]
            ),
            providers=[BuiltinToolProvider(), provider],
            allowed_tools=["mcp.phase4.echo"],
        )
        try:
            agent.ask("Attempt an invalid MCP invocation")
            event = next(event for event in self._trace(agent) if event.get("event") == "tool_executed")
            passed = event.get("tool_error_code") == "invalid_arguments" and not (workspace / "mutation.marker").exists()
            rows.append(self._row("governance_invalid_parameters", "tool_governance", passed, agent=agent, rejection=event.get("result", ""), metadata=event))
        finally:
            agent.close()

        workspace = self._copy_fixture("governance_path_escape", "integrated")
        self._initialize_git_fixture(workspace)
        provider = self._mcp_provider("git-demo", self.git_server, workspace, read_only={"git_diff", "git_history"})
        agent = self._agent(
            workspace,
            FakeModelClient(
                [
                    '<tool>{"name":"mcp.git-demo.git_diff","args":{"path":"../../secret"}}</tool>',
                    "<final>Path handling completed.</final>",
                ]
            ),
            providers=[BuiltinToolProvider(), provider],
            allowed_tools=["mcp.git-demo.git_diff"],
        )
        try:
            agent.ask("Attempt a path escape through an MCP tool")
            event = next(event for event in self._trace(agent) if event.get("event") == "tool_executed")
            rows.append(self._row("governance_path_escape", "tool_governance", event.get("security_event_type") == "path_escape", agent=agent, failure_category="mcp_path_escape_contract_missing", rejection=event.get("result", ""), metadata=event, enforcement_layer="MCP server path boundary"))
        finally:
            agent.close()

        workspace = self._copy_fixture("governance_approval", "integrated")
        provider = self._mcp_provider("phase4", self.test_server, workspace, read_only={"echo"})
        agent = self._agent(
            workspace,
            FakeModelClient(
                [
                    '<tool>{"name":"mcp.phase4.mutate","args":{"value":"must-not-write"}}</tool>',
                    "<final>Approval was required.</final>",
                ]
            ),
            providers=[BuiltinToolProvider(), provider],
            approval_policy="never",
            allowed_tools=["mcp.phase4.mutate"],
        )
        try:
            agent.ask("Attempt a high-risk MCP mutation")
            event = next(event for event in self._trace(agent) if event.get("event") == "tool_executed")
            passed = event.get("tool_error_code") == "approval_denied" and not (workspace / "mutation.marker").exists()
            rows.append(self._row("governance_risky_approval", "tool_governance", passed, agent=agent, rejection=event.get("result", ""), metadata=event))
        finally:
            agent.close()

        workspace = self._copy_fixture("governance_trace_integrity", "integrated")
        provider = self._mcp_provider("phase4", self.test_server, workspace, read_only={"echo"})
        agent = self._agent(
            workspace,
            FakeModelClient(['<tool>{"name":"mcp.phase4.echo","args":{"message":"trace"}}</tool>', "<final>Trace retained.</final>"]),
            providers=[BuiltinToolProvider(), provider],
            allowed_tools=["mcp.phase4.echo"],
        )
        try:
            agent.ask("Record a governed MCP invocation")
            rows.append(self._row("governance_trace_integrity", "tool_governance", self._trace_complete(self._trace(agent)), agent=agent))
        finally:
            agent.close()
        return rows

    def _run_integrated_cases(self) -> list[dict]:
        rows = []
        workspace = self._copy_fixture("integrated_review_login", "integrated")
        self._write_skills(workspace, "code_review")
        agent = self._agent(workspace, ScenarioModelClient("integrated_review"), allowed_tools=["read_file"])
        try:
            answer = agent.ask("Review the login module problems and propose a repair")
            rows.append(self._row("integrated_review_login", "integrated", "LOGIN_REVIEW" in answer and agent.last_prompt_metadata.get("selected_skills") == ["code_review"], agent=agent, final_answer=answer, selected_skills=agent.last_prompt_metadata.get("selected_skills", [])))
        finally:
            agent.close()

        workspace = self._copy_fixture("integrated_recent_commit", "integrated")
        self._initialize_git_fixture(workspace)
        provider = self._mcp_provider("git-demo", self.git_server, workspace, read_only={"git_diff", "git_history"})
        agent = self._agent(workspace, FakeModelClient(['<tool>{"name":"mcp.git-demo.git_history","args":{"limit":1}}</tool>', "<final>Recent commit introduced the regression.</final>"]), providers=[BuiltinToolProvider(), provider], allowed_tools=["mcp.git-demo.git_history"])
        try:
            answer = agent.ask("Locate the problem introduced by the latest commit")
            rows.append(self._row("integrated_recent_commit", "integrated", "regression" in answer and "mcp.git-demo.git_history" in [event.get("name") for event in self._trace(agent)], agent=agent, final_answer=answer))
        finally:
            agent.close()

        workspace = self._copy_fixture("integrated_skill_mcp", "integrated")
        self._initialize_git_fixture(workspace)
        self._write_skills(workspace, "code_review", "debugging")
        provider = self._mcp_provider("git-demo", self.git_server, workspace, read_only={"git_diff", "git_history"})
        agent = self._agent(workspace, ScenarioModelClient("integrated_both"), providers=[BuiltinToolProvider(), provider], allowed_tools=["read_file", "mcp.git-demo.git_diff"])
        try:
            answer = agent.ask("Debug and review the login code, then use git evidence for a repair proposal")
            selected = set(agent.last_prompt_metadata.get("selected_skills", []))
            calls = [event.get("name") for event in self._trace(agent) if event.get("event") == "tool_executed"]
            passed = "INTEGRATED_REPAIR" in answer and selected == {"code_review", "debugging"} and {"read_file", "mcp.git-demo.git_diff"} <= set(calls)
            rows.append(self._row("integrated_skill_mcp", "integrated", passed, agent=agent, final_answer=answer, selected_skills=sorted(selected)))
        finally:
            agent.close()
        return rows

    @staticmethod
    def _summary(rows: list[dict]) -> dict:
        total = len(rows)
        passed = sum(row["passed"] for row in rows)
        calls = [len(row.get("tool_calls", [])) for row in rows if "tool_calls" in row]
        steps = [row.get("tool_steps", 0) for row in rows if "tool_steps" in row]
        categories: dict[str, int] = {}
        for row in rows:
            if not row["passed"]:
                category = row["failure_category"] or "unknown"
                categories[category] = categories.get(category, 0) + 1
        return {
            "case_count": total,
            "passed": passed,
            "failed": total - passed,
            "task_success_rate": passed / total if total else 0.0,
            "average_tool_calls": sum(calls) / len(calls) if calls else 0.0,
            "average_tool_steps": sum(steps) / len(steps) if steps else 0.0,
            "trace_completeness_rate": sum(bool(row.get("trace_complete")) for row in rows if "trace_complete" in row) / len(calls) if calls else 0.0,
            "failure_category_counts": categories,
        }

    @classmethod
    def _skill_summary(cls, rows: list[dict]) -> dict:
        summary = cls._summary(rows)
        for label, subset in (("baseline", [row for row in rows if row["id"].endswith("baseline")]), ("with_skill", [row for row in rows if not row["id"].endswith("baseline")])):
            expected = sum(row.get("expected_issue_count", 0) for row in subset)
            detected = sum(row.get("issue_detection_count", 0) for row in subset)
            summary[f"{label}_issue_detection_recall"] = detected / expected if expected else 0.0
        summary["skill_selection_rate"] = sum(row.get("skill_selection_matches_variant", False) for row in rows) / len(rows)
        return summary

    @classmethod
    def _mcp_summary(cls, rows: list[dict]) -> dict:
        summary = cls._summary(rows)
        lookup = {row["id"]: row for row in rows}
        summary["tool_discovery_success_rate"] = float(lookup["mcp_tool_discovery"]["passed"])
        summary["invocation_success_rate"] = float(lookup["mcp_tool_invocation"]["passed"])
        errors = [row for row in rows if row["id"].startswith("mcp_error_")]
        summary["error_handling_rate"] = sum(row["passed"] for row in errors) / len(errors)
        summary["multi_server_isolation_rate"] = float(lookup["mcp_multi_server_isolation"]["passed"])
        return summary

    @classmethod
    def _governance_summary(cls, rows: list[dict]) -> dict:
        summary = cls._summary(rows)
        lookup = {row["id"]: row for row in rows}
        summary["schema_rejection_rate"] = float(lookup["governance_invalid_parameters"]["passed"])
        summary["path_escape_block_rate"] = float(lookup["governance_path_escape"]["passed"])
        summary["approval_gate_rate"] = float(lookup["governance_risky_approval"]["passed"])
        summary["unsafe_execution_count"] = int(not lookup["governance_risky_approval"]["passed"])
        return summary

    def _write_reports(self, artifact: dict) -> dict[str, str]:
        paths = {}
        for key, filename, title in (
            ("skill", "phase4-skill-report.md", "Phase 4 Skill Benchmark"),
            ("mcp", "phase4-mcp-report.md", "Phase 4 MCP Benchmark"),
            ("tool_governance", "phase4-tool-governance-report.md", "Phase 4 Tool Governance Benchmark"),
            ("integrated", "phase4-integrated-report.md", "Phase 4 Integrated Agent Benchmark"),
        ):
            path = self.output_root / filename
            path.write_text(self._markdown_report(title, artifact["environment"], artifact[key]), encoding="utf-8")
            paths[key] = str(path)
        final_path = self.output_root / "phase4-final-benchmark-report.md"
        final_path.write_text(self._final_report(artifact), encoding="utf-8")
        paths["final"] = str(final_path)
        return paths

    @staticmethod
    def _markdown_report(title: str, environment: dict, section: dict) -> str:
        summary = section["summary"]
        lines = [f"# {title}", "", "## Environment", "", f"- Runtime: {environment['runtime']}", f"- Skill mode: {environment['skill_mode']}", f"- MCP mode: {environment['mcp_mode']}", "", "## Metrics", "", f"- Task Success Rate: {summary['task_success_rate']:.2%}", f"- Average Tool Calls: {summary['average_tool_calls']:.2f}", f"- Average Tool Steps: {summary['average_tool_steps']:.2f}", f"- Trace Completeness Rate: {summary['trace_completeness_rate']:.2%}", "", "## Cases", "", "| Case | Status | Tool Steps | Trace |", "| --- | --- | ---: | --- |"]
        for row in section["rows"]:
            lines.append(f"| {row['id']} | {row['status']} | {row.get('tool_steps', 0)} | {row.get('trace_path', '-')} |")
        extras = {key: value for key, value in summary.items() if key not in {"case_count", "passed", "failed", "task_success_rate", "average_tool_calls", "average_tool_steps", "trace_completeness_rate", "failure_category_counts"}}
        for key, value in extras.items():
            rendered = f"{value:.2%}" if isinstance(value, float) else str(value)
            lines.append(f"- {key}: {rendered}")
        lines.extend(["", "## Failure Analysis", "", f"- Failure categories: {json.dumps(summary['failure_category_counts'], ensure_ascii=False) or '{}'}", ""])
        return "\n".join(lines)

    @staticmethod
    def _final_report(artifact: dict) -> str:
        lines = ["# CodePilot v2 Phase 4 Final Benchmark Report", "", "## Environment", "", f"- Python: {artifact['environment']['python']}", f"- MCP servers: {', '.join(artifact['environment']['mcp_servers'])}", "", "## Results", "", "| Area | Cases | Success Rate | Avg Tool Calls | Avg Tool Steps |", "| --- | ---: | ---: | ---: | ---: |"]
        for key, label in (("skill", "Skill"), ("mcp", "MCP"), ("tool_governance", "Tool Governance"), ("integrated", "Integrated Agent")):
            summary = artifact[key]["summary"]
            lines.append(f"| {label} | {summary['case_count']} | {summary['task_success_rate']:.2%} | {summary['average_tool_calls']:.2f} | {summary['average_tool_steps']:.2f} |")
        lines.extend(["", "## Evidence Boundary", "", "- Skill results use a deterministic prompt-aware client, so they prove prompt injection changes the evaluated strategy; they do not claim a universal provider-quality gain.", "- MCP rows start real local stdio processes and retain their actual Pico traces.", "- Failed rows are retained in the JSON artifact and the per-case trace paths.", ""])
        return "\n".join(lines)


def run_phase4_benchmark(output_root=None, workspace_root=None) -> dict:
    """Convenience entry point used by the CLI script and tests."""
    return Phase4BenchmarkRunner(output_root=output_root, workspace_root=workspace_root).run()
