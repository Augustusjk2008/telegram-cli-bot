from __future__ import annotations

import json
from pathlib import Path

from bot.web.announcement_store import AnnouncementStore


def _write_announcements(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-08-28T10:00:00+08:00",
                "items": [
                    {
                        "id": "ann-old",
                        "published_at": "2026-08-27T10:00:00+08:00",
                        "publisher": "Orbit",
                        "title": "旧公告",
                        "category": "notice",
                        "severity": "info",
                        "summary": "旧内容",
                        "sections": [],
                    },
                    {
                        "id": "ann-new",
                        "published_at": "2026-08-28T10:00:00+08:00",
                        "publisher": "Orbit",
                        "title": "新公告",
                        "category": "notice",
                        "severity": "info",
                        "summary": "新内容",
                        "sections": [],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_mark_seen_is_shared_across_accounts(tmp_path: Path) -> None:
    content_path = tmp_path / "content.json"
    reads_path = tmp_path / "reads.json"
    _write_announcements(content_path)
    store = AnnouncementStore(content_path, reads_path=reads_path)

    store.mark_seen("alice", "ann-new")

    result = store.list_for_user("bob")
    assert result["last_seen_id"] == "ann-new"
    assert result["has_unseen"] is False


def test_stale_account_cannot_move_shared_read_watermark_backwards(tmp_path: Path) -> None:
    content_path = tmp_path / "content.json"
    reads_path = tmp_path / "reads.json"
    _write_announcements(content_path)
    store = AnnouncementStore(content_path, reads_path=reads_path)

    store.mark_seen("alice", "ann-new")
    store.mark_seen("bob", "ann-old")

    result = store.list_for_user("charlie")
    assert result["last_seen_id"] == "ann-new"
    assert result["has_unseen"] is False


def test_legacy_account_reads_seed_shared_read_watermark(tmp_path: Path) -> None:
    content_path = tmp_path / "content.json"
    reads_path = tmp_path / "reads.json"
    _write_announcements(content_path)
    reads_path.write_text(
        json.dumps(
            {
                "version": 1,
                "reads": {
                    "alice": {"last_seen_id": "ann-old", "seen_at": "2026-08-27T11:00:00+08:00"},
                    "bob": {"last_seen_id": "ann-new", "seen_at": "2026-08-28T11:00:00+08:00"},
                },
            }
        ),
        encoding="utf-8",
    )
    store = AnnouncementStore(content_path, reads_path=reads_path)

    result = store.list_for_user("charlie")

    assert result["last_seen_id"] == "ann-new"
    assert result["has_unseen"] is False
