import sqlite3
from pathlib import Path

from bot.web.native_history_locator import (
    build_claude_bucket_candidates,
    locate_claude_transcript,
    locate_codex_transcript,
)


def test_locate_codex_transcript_uses_sqlite_rollout_index(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    db_path = codex_home / "state_5.sqlite"
    transcript = codex_home / "sessions" / "2026" / "04" / "14" / "rollout-test.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"session_meta"}\n', encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, cwd TEXT)")
        conn.execute(
            "INSERT INTO threads (id, rollout_path, cwd) VALUES (?, ?, ?)",
            ("thread-1", str(transcript), "/srv/demo/repo"),
        )
        conn.commit()

    ref = locate_codex_transcript("thread-1", codex_home=codex_home)
    assert ref is not None
    assert ref.path == transcript
    assert ref.provider == "codex"


def test_build_claude_bucket_candidates_supports_windows_and_linux():
    windows_candidates = build_claude_bucket_candidates(
        r"C:\Users\JiangKai\telegram-cli-bridge\refactoring"
    )
    linux_candidates = build_claude_bucket_candidates("/srv/telegram-cli-bridge/refactoring")

    assert "C--Users-JiangKai-telegram-cli-bridge-refactoring" in windows_candidates
    assert "-srv-telegram-cli-bridge-refactoring" in linux_candidates


def test_locate_claude_transcript_falls_back_to_session_id_scan(tmp_path: Path):
    claude_home = tmp_path / ".claude"
    target = claude_home / "projects" / "unexpected-bucket" / "session-1.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text('{"type":"user"}\n', encoding="utf-8")

    ref = locate_claude_transcript(
        "session-1",
        cwd_hint="/srv/telegram-cli-bridge/refactoring",
        claude_home=claude_home,
    )

    assert ref is not None
    assert ref.path == target
    assert ref.provider == "claude"
