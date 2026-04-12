from __future__ import annotations

import re
import sqlite3

from bot.assistant_home import AssistantHome
from bot.assistant_state import load_assistant_runtime_state

_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


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


def _parse_working_list(text: str, *, max_items: int, max_chars: int) -> list[str]:
    items: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = _LIST_MARKER_RE.sub("", line)
        line = _normalize_text(line, max_chars)
        if not line:
            continue
        items.append(line)
        if len(items) >= max_items:
            break
    return items


def _parse_working_goal(text: str, *, max_chars: int) -> str:
    lines = _parse_working_list(text, max_items=2, max_chars=max_chars)
    if not lines:
        return ""
    return _normalize_text(" ".join(lines), max_chars)


def _load_history_items(home: AssistantHome, user_id: int) -> list[dict]:
    state = load_assistant_runtime_state(home, user_id)
    history = state.get("history", [])
    return [dict(item) for item in history if isinstance(item, dict) and item.get("content")]


def _derive_current_goal(history: list[dict]) -> str:
    for item in reversed(history):
        if item.get("role") == "user":
            return _normalize_text(str(item.get("content", "")), 140)
    return ""


def _derive_recent_summary(history: list[dict], *, max_items: int = 4) -> list[str]:
    summary: list[str] = []
    for item in history[-max_items:]:
        role = "U" if item.get("role") == "user" else "A"
        text = _normalize_text(str(item.get("content", "")), 140)
        if not text:
            continue
        summary.append(f"{role}: {text}")
    return summary


def _render_section(name: str, items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    lines = [f"{name}:"]
    lines.extend(f"- {item}" for item in cleaned)
    return "\n".join(lines)


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
    )
    if recent_summary:
        sections.append(_render_section("recent_summary", recent_summary))

    return "\n\n".join(section for section in sections if section)


def _load_retrieved_knowledge(home: AssistantHome, user_text: str) -> list[str]:
    db_path = home.root / "indexes" / "chunks.sqlite"
    if not db_path.exists():
        rebuild_assistant_index(home)

    query = (user_text or "").strip()[:20]
    conn = sqlite3.connect(db_path)
    try:
        rows = []
        if query:
            rows = conn.execute(
                "SELECT content FROM chunks WHERE status = 'approved' AND content LIKE ? LIMIT 3",
                (f"%{query}%",),
            ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT content FROM chunks WHERE status = 'approved' ORDER BY source LIMIT 3"
            ).fetchall()
    finally:
        conn.close()

    items: list[str] = []
    for row in rows:
        if not row or not row[0]:
            continue
        items.append(_normalize_text(str(row[0]), 200))
    return items


def rebuild_assistant_index(home: AssistantHome) -> None:
    db_path = home.root / "indexes" / "chunks.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks (kind TEXT, source TEXT, status TEXT, content TEXT)"
        )
        conn.execute("DELETE FROM chunks")

        for path in sorted((home.root / "memory" / "knowledge").glob("*.md")):
            raw_text = path.read_text(encoding="utf-8")
            status, content = _extract_status_and_content(raw_text)
            conn.execute(
                "INSERT INTO chunks(kind, source, status, content) VALUES (?, ?, ?, ?)",
                ("knowledge", str(path), status, content),
            )

        conn.commit()
    finally:
        conn.close()


def compile_assistant_prompt(
    home: AssistantHome,
    user_id: int,
    user_text: str,
    *,
    has_native_session: bool = False,
) -> str:
    history = _load_history_items(home, user_id)
    sections: list[str] = []

    current_goal = _parse_working_goal(
        _read_working_file(home, "current_goal"),
        max_chars=160,
    )
    if not current_goal and not has_native_session:
        current_goal = _derive_current_goal(history)
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
    )
    if not recent_summary and not has_native_session:
        recent_summary = _derive_recent_summary(history, max_items=4)
    if recent_summary:
        sections.append(_render_section("recent_summary", recent_summary))

    retrieved_knowledge = _load_retrieved_knowledge(home, user_text)
    if retrieved_knowledge:
        sections.append(_render_section("retrieved_knowledge", retrieved_knowledge))

    body = "\n\n".join(section for section in sections if section)
    if body:
        return (
            "[LOCAL_ASSISTANT_CONTEXT]\n"
            f"{body}\n\n"
            "[USER_REQUEST]\n"
            f"{user_text}"
        )
    return (
        "[LOCAL_ASSISTANT_CONTEXT]\n\n"
        "[USER_REQUEST]\n"
        f"{user_text}"
    )
