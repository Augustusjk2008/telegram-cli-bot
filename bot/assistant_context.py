from __future__ import annotations

import sqlite3

from bot.assistant_home import AssistantHome
from bot.assistant_state import load_assistant_runtime_state


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


def compile_assistant_prompt(home: AssistantHome, user_id: int, user_text: str) -> str:
    db_path = home.root / "indexes" / "chunks.sqlite"
    if not db_path.exists():
        rebuild_assistant_index(home)

    state = load_assistant_runtime_state(home, user_id)
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

    knowledge = "\n".join(row[0] for row in rows if row and row[0])
    recent = "\n".join(
        item.get("content", "")
        for item in state.get("history", [])[-4:]
        if isinstance(item, dict) and item.get("content")
    )
    return (
        "[LOCAL_ASSISTANT_CONTEXT]\n"
        f"recent_memory:\n{recent}\n"
        f"retrieved_knowledge:\n{knowledge}\n\n"
        "[USER_REQUEST]\n"
        f"{user_text}"
    )
