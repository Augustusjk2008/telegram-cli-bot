from __future__ import annotations

import re
from dataclasses import dataclass
import yaml

from bot.assistant_home import AssistantHome
from bot.assistant_compaction import build_compaction_memory_block

_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


@dataclass(frozen=True)
class AssistantPromptPayload:
    prompt_text: str
    managed_prompt_hash_seen: str | None


def _normalize_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _extract_status_and_content(text: str) -> tuple[str, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            frontmatter = parts[1]
            content = parts[2].lstrip()
            status = "approved" if "status: approved" in frontmatter else "proposed"
            return status, content
    status = "approved" if "status: approved" in text else "proposed"
    return status, text


def _extract_frontmatter_payload(text: str) -> dict:
    if not text.startswith("---"):
        return {}

    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}

    try:
        payload = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}

    return payload if isinstance(payload, dict) else {}


def _normalize_text(text: str, max_chars: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _read_working_file(home: AssistantHome, name: str) -> str:
    path = home.root / "memory" / "working" / f"{name}.md"
    if not path.exists():
        return ""
    raw_text = path.read_text(encoding="utf-8")
    _, content = _extract_status_and_content(raw_text)
    return content.strip()


def _parse_working_list(text: str, *, max_items: int, max_chars: int, prefer_recent: bool = False) -> list[str]:
    parsed: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = _LIST_MARKER_RE.sub("", line)
        line = _normalize_text(line, max_chars)
        if line:
            parsed.append(line)
    selected = parsed[-max_items:] if prefer_recent else parsed[:max_items]
    return selected


def _parse_working_goal(text: str, *, max_chars: int) -> str:
    lines = _parse_working_list(text, max_items=2, max_chars=max_chars)
    if not lines:
        return ""
    return _normalize_text(" ".join(lines), max_chars)


def _render_section(name: str, items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    lines = [f"{name}:"]
    lines.extend(f"- {item}" for item in cleaned)
    return "\n".join(lines)


def _list_skill_description_lines(home: AssistantHome) -> list[str]:
    items: list[str] = []
    skills_root = home.root / "memory" / "skills"
    for path in sorted(skills_root.rglob("SKILL.md")):
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        payload = _extract_frontmatter_payload(raw_text)
        description = " ".join(str(payload.get("description") or "").split())
        if not description:
            continue

        name = str(payload.get("name") or "").strip() or path.parent.name
        items.append(f"{name}: {description}")

    return items


def build_managed_memory_prompt(home: AssistantHome) -> str:
    sections: list[str] = []

    current_goal = _parse_working_goal(
        _read_working_file(home, "current_goal"),
        max_chars=160,
    )
    if current_goal:
        sections.append(_render_section("current_goal", [current_goal]))

    open_loops = _parse_working_list(
        _read_working_file(home, "open_loops"),
        max_items=5,
        max_chars=140,
    )
    if open_loops:
        sections.append(_render_section("open_loops", open_loops))

    user_preferences = _parse_working_list(
        _read_working_file(home, "user_prefs"),
        max_items=8,
        max_chars=140,
    )
    if user_preferences:
        sections.append(_render_section("user_preferences", user_preferences))

    recent_summary = _parse_working_list(
        _read_working_file(home, "recent_summary"),
        max_items=5,
        max_chars=140,
        prefer_recent=True,
    )
    if recent_summary:
        sections.append(_render_section("recent_summary", recent_summary))

    skill_descriptions = _list_skill_description_lines(home)
    if skill_descriptions:
        sections.append(
            _render_section(
                "assistant_skills",
                ["source_dir: .assistant/memory/skills", *skill_descriptions],
            )
        )

    return "\n\n".join(section for section in sections if section)


def build_managed_memory_tail(home: AssistantHome) -> str:
    sections = [
        build_managed_memory_prompt(home).strip(),
        build_compaction_memory_block(home).strip(),
    ]
    return "\n\n".join(section for section in sections if section)


def compile_assistant_prompt(
    user_text: str,
    *,
    managed_prompt_hash: str | None = None,
    seen_managed_prompt_hash: str | None = None,
) -> AssistantPromptPayload:
    managed_prompt_hash = _normalize_optional_str(managed_prompt_hash)
    seen_managed_prompt_hash = _normalize_optional_str(seen_managed_prompt_hash)

    return AssistantPromptPayload(
        prompt_text=user_text,
        managed_prompt_hash_seen=managed_prompt_hash or seen_managed_prompt_hash,
    )
