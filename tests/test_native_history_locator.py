import json
import sqlite3
from pathlib import Path

from bot.web import native_history_locator as native_history_locator_module
from bot.web.native_history_locator import (
    build_claude_bucket_candidates,
    clear_history_locator_cache,
    locate_claude_transcript,
    locate_codex_transcript,
    locate_kimi_last_session_id_for_workdir,
    locate_kimi_transcript,
)


class TrackingConnection:
    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "closed", False)

    def close(self):
        object.__setattr__(self, "closed", True)
        return self._conn.close()

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._conn.__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_locate_codex_transcript_uses_sqlite_rollout_index(tmp_path: Path):
    clear_history_locator_cache()
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


def test_locate_codex_transcript_closes_sqlite_connections(monkeypatch, tmp_path: Path):
    clear_history_locator_cache()
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    db_path = codex_home / "state_5.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, cwd TEXT)")
        conn.commit()

    original_connect = native_history_locator_module.sqlite3.connect
    tracked = []

    def tracked_connect(*args, **kwargs):
        conn = TrackingConnection(original_connect(*args, **kwargs))
        tracked.append(conn)
        return conn

    monkeypatch.setattr(native_history_locator_module.sqlite3, "connect", tracked_connect)

    assert locate_codex_transcript("missing-thread", codex_home=codex_home) is None
    assert tracked
    assert all(conn.closed for conn in tracked)


def test_build_claude_bucket_candidates_supports_windows_and_linux():
    windows_candidates = build_claude_bucket_candidates(
        r"C:\Users\JiangKai\telegram-cli-bridge\refactoring"
    )
    linux_candidates = build_claude_bucket_candidates("/srv/telegram-cli-bridge/refactoring")

    assert "C--Users-JiangKai-telegram-cli-bridge-refactoring" in windows_candidates
    assert "-srv-telegram-cli-bridge-refactoring" in linux_candidates


def test_locate_claude_transcript_falls_back_to_session_id_scan(tmp_path: Path):
    clear_history_locator_cache()
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


def test_locate_codex_transcript_reuses_cached_rollout_path(monkeypatch, tmp_path: Path):
    clear_history_locator_cache()
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

    first = locate_codex_transcript("thread-1", codex_home=codex_home)

    assert first is not None

    monkeypatch.setattr(
        native_history_locator_module.sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sqlite should not be reopened")),
    )

    second = locate_codex_transcript("thread-1", codex_home=codex_home)

    assert second == first


def test_locate_claude_transcript_reuses_cached_fallback_scan(monkeypatch, tmp_path: Path):
    clear_history_locator_cache()
    claude_home = tmp_path / ".claude"
    target = claude_home / "projects" / "unexpected-bucket" / "session-1.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text('{"type":"user"}\n', encoding="utf-8")

    first = locate_claude_transcript(
        "session-1",
        cwd_hint="/srv/telegram-cli-bridge/refactoring",
        claude_home=claude_home,
    )

    assert first is not None

    original_glob = Path.glob

    def fail_recursive_glob(path: Path, pattern: str):
        if path == claude_home / "projects" and pattern == "**/session-1.jsonl":
            raise AssertionError("recursive glob should not rerun")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", fail_recursive_glob)

    second = locate_claude_transcript(
        "session-1",
        cwd_hint="/srv/telegram-cli-bridge/refactoring",
        claude_home=claude_home,
    )

    assert second == first


def test_locate_kimi_transcript_scans_session_directory(tmp_path: Path):
    kimi_home = tmp_path / ".kimi"
    transcript = kimi_home / "sessions" / "work-hash" / "kimi-session-1" / "wire.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"metadata","protocol_version":"1.8"}\n', encoding="utf-8")

    ref = locate_kimi_transcript("kimi-session-1", kimi_home=kimi_home)

    assert ref is not None
    assert ref.provider == "kimi"
    assert ref.path == transcript


def test_locate_kimi_last_session_id_for_workdir_reads_metadata(tmp_path: Path):
    kimi_home = tmp_path / ".kimi"
    kimi_home.mkdir()
    (kimi_home / "kimi.json").write_text(
        json.dumps(
            {
                "work_dirs": [
                    {
                        "path": r"C:\repo",
                        "kaos": "local",
                        "last_session_id": "kimi-session-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert locate_kimi_last_session_id_for_workdir(r"c:\repo", kimi_home=kimi_home) == "kimi-session-1"
