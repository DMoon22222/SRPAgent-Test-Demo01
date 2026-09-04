from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MAX_SKILL_CHARS = 6000


@dataclass(frozen=True)
class Skill:
    skill_id: str
    path: Path
    title: str
    keywords: tuple[str, ...]
    content: str


def load_skill(path: Path) -> Skill:
    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).strip()

    if len(text) > MAX_SKILL_CHARS:
        text = text[:MAX_SKILL_CHARS] + "\n...[truncated]"

    metadata, body = parse_front_matter(text)
    title = extract_title(body) or path.parent.name
    keywords = tuple(
        item.strip().lower()
        for item in metadata.get("keywords", "").split(",")
        if item.strip()
    )

    return Skill(
        skill_id=path.parent.name,
        path=path,
        title=title,
        keywords=keywords,
        content=body.strip(),
    )


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---", 4)
    if end == -1:
        return {}, text

    metadata: dict[str, str] = {}
    for line in text[4:end].strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip()

    return metadata, text[end + 4:].lstrip("\n")


def extract_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""
