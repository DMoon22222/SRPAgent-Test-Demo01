from __future__ import annotations

import re

from .loader import Skill


def match_skills(
    user_request: str,
    skills: list[Skill],
    limit: int = 2,
) -> list[Skill]:
    request = str(user_request).lower()
    request_tokens = set(
        re.findall(r"[a-z0-9_+-]+", request)
    )
    scored: list[tuple[int, Skill]] = []

    for skill in skills:
        score = score_skill(request, request_tokens, skill)
        if score > 0:
            scored.append((score, skill))

    scored.sort(
        key=lambda item: (-item[0], item[1].skill_id)
    )
    return [skill for _, skill in scored[:limit]]


def score_skill(
    request: str,
    request_tokens: set[str],
    skill: Skill,
) -> int:
    score = 0
    skill_id = skill.skill_id.lower()
    title = skill.title.lower()

    if skill_id in request:
        score += 8

    if title and title in request:
        score += 6

    for keyword in skill.keywords:
        if keyword in request:
            score += 5

        keyword_tokens = set(
            re.findall(r"[a-z0-9_+-]+", keyword)
        )
        if keyword_tokens and keyword_tokens <= request_tokens:
            score += 2

    return score
