from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.skills.loader import load_skill
from pico.skills.registry import SkillRegistry


def test_registry_discovers_matches_and_renders_skills(tmp_path):
    skill_path = tmp_path / "skills" / "code_review" / "skill.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\n"
        "keywords: review, architecture, 审查\n"
        "---\n\n"
        "# Code Review\n\n"
        "Read implementation and tests before reporting risks.\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path)

    discovered = registry.discover()
    selected = registry.match("Review the architecture")
    prompt, names = registry.render_for_prompt(
        "Review the architecture"
    )

    assert [skill.skill_id for skill in discovered] == ["code_review"]
    assert [skill.skill_id for skill in selected] == ["code_review"]
    assert names == ["code_review"]
    assert "[Skill: code_review]" in prompt
    assert "Read implementation" in prompt


def test_registry_handles_missing_skills_directory(tmp_path):
    registry = SkillRegistry(tmp_path)

    assert registry.discover() == []
    assert registry.render_for_prompt("Debug a failure") == (
        "Skills:\n- none",
        [],
    )


def test_loader_extracts_front_matter_title_and_limits_content(tmp_path):
    path = tmp_path / "skills" / "debugging" / "skill.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nkeywords: debug, bug\n---\n\n"
        "# Debugging\n\n"
        "Use the smallest reproduction.\n",
        encoding="utf-8",
    )

    skill = load_skill(path)

    assert skill.skill_id == "debugging"
    assert skill.title == "Debugging"
    assert skill.keywords == ("debug", "bug")
    assert "smallest reproduction" in skill.content


def test_pico_discovers_matches_and_injects_skills_for_each_request(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    agent = Pico(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
    )
    skill_path = tmp_path / "skills" / "code_review" / "skill.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nkeywords: review\n---\n\n"
        "# Code Review\n\n"
        "Inspect implementation and tests before reporting risks.\n",
        encoding="utf-8",
    )

    prompt, metadata = agent._build_prompt_and_metadata("Review this change")

    assert prompt.index("You are pico") < prompt.index("[Skill: code_review]")
    assert prompt.index("[Skill: code_review]") < prompt.index("Memory:")
    assert metadata["selected_skills"] == ["code_review"]
    assert metadata["skill_chars"] == metadata["sections"]["skills"]["raw_chars"]


def test_pico_replaces_skill_registry_when_switching_workspaces(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "README.md").write_text("first\n", encoding="utf-8")
    (second / "README.md").write_text("second\n", encoding="utf-8")
    agent = Pico(
        model_client=FakeModelClient([]),
        workspace=WorkspaceContext.build(first),
        session_store=SessionStore(first / ".pico" / "sessions"),
        approval_policy="auto",
    )

    agent.switch_workspace(second)

    assert agent.skill_registry.workspace_root == second.resolve()
