from __future__ import annotations

from pathlib import Path

from .loader import Skill, load_skill
from .matcher import match_skills


class SkillRegistry:
    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root)
        self.skills_root = self.workspace_root / "skills"
        self._skills: list[Skill] = []

    def discover(self) -> list[Skill]:
        if not self.skills_root.is_dir():
            self._skills = []
            return []

        skills: list[Skill] = []
        for path in sorted(self.skills_root.glob("*/skill.md")):
            try:
                skills.append(load_skill(path))
            except OSError:
                continue

        self._skills = skills
        return list(self._skills)

    def match(
        self,
        user_request: str,
        limit: int = 2,
    ) -> list[Skill]:
        return match_skills(
            user_request,
            self._skills,
            limit=limit,
        )

    def render_for_prompt(
        self,
        user_request: str,
        limit: int = 2,
    ) -> tuple[str, list[str]]:
        selected = self.match(user_request, limit=limit)

        if not selected:
            return "Skills:\n- none", []

        names = [skill.skill_id for skill in selected]
        blocks = ["Skills:"]

        for skill in selected:
            blocks.append(
                f"[Skill: {skill.skill_id}]\n{skill.content}"
            )

        return "\n\n".join(blocks), names
