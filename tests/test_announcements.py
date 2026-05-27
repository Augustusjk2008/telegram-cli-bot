from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.web.announcement_store import AnnouncementStore


def _announcement(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "ann-new",
        "published_at": "2026-05-13T09:00:00+08:00",
        "publisher": "CLI Bridge",
        "title": "新公告",
        "category": "feature",
        "severity": "info",
        "summary": "新公告摘要",
        "sections": [{"label": "新增", "items": ["新内容"]}],
        **overrides,
    }


def test_store_returns_items_sorted_by_publish_time(tmp_path: Path) -> None:
    store = AnnouncementStore(tmp_path / "announcements.json")
    store.upsert_item(_announcement(
        id="ann-old",
        published_at="2026-05-12T09:00:00+08:00",
        title="旧公告",
        category="notice",
        summary="旧公告摘要",
        sections=[{"label": "说明", "items": ["旧内容"]}],
    ))
    store.upsert_item(_announcement(
        id="ann-new",
        published_at="2026-05-13T09:00:00+08:00",
        title="新公告",
        severity="success",
        summary="新公告摘要",
        sections=[{"label": "新增", "items": ["新内容"]}],
    ))

    result = store.list_for_user("admin")

    assert [item["id"] for item in result["items"]] == ["ann-new", "ann-old"]
    assert result["latest_id"] == "ann-new"
    assert result["has_unseen"] is True


def test_store_marks_latest_seen_per_user(tmp_path: Path) -> None:
    store = AnnouncementStore(tmp_path / "announcements.json")
    store.upsert_item(_announcement(id="ann-new"))

    result = store.mark_seen("admin", "ann-new")

    assert result["has_unseen"] is False
    assert store.list_for_user("other")["has_unseen"] is True


def test_store_mark_seen_writes_sidecar_without_touching_content_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.web.announcement_store as announcement_store

    content_path = tmp_path / "announcements.json"
    reads_path = tmp_path / "reads.json"
    store = AnnouncementStore(content_path, reads_path=reads_path)
    store.upsert_item(_announcement(id="ann-new"))
    content_before = json.loads(content_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(announcement_store, "_now_iso", lambda: "2099-01-01T00:00:00+08:00", raising=False)

    store.mark_seen("admin", "ann-new")

    content_after = json.loads(content_path.read_text(encoding="utf-8"))
    reads_after = json.loads(reads_path.read_text(encoding="utf-8"))
    assert "reads" not in content_after
    assert content_after["updated_at"] == content_before["updated_at"]
    assert reads_after == {
        "version": 1,
        "updated_at": "2099-01-01T00:00:00+08:00",
        "reads": {
            "admin": {
                "last_seen_id": "ann-new",
                "seen_at": "2099-01-01T00:00:00+08:00",
            },
        },
    }


def test_store_reads_legacy_content_reads_and_drops_them_on_next_content_save(tmp_path: Path) -> None:
    content_path = tmp_path / "announcements.json"
    content_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-05-13T09:00:00+08:00",
                "items": [_announcement(id="ann-new")],
                "reads": {
                    "admin": {
                        "last_seen_id": "ann-new",
                        "seen_at": "2026-05-13T10:00:00+08:00",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = AnnouncementStore(content_path, reads_path=tmp_path / "reads.json")

    result = store.list_for_user("admin")
    store.upsert_item(_announcement(id="ann-next", published_at="2026-05-14T09:00:00+08:00"))

    content_after = json.loads(content_path.read_text(encoding="utf-8"))
    assert result["has_unseen"] is False
    assert "reads" not in content_after


def test_store_create_item_generates_id_and_publish_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.web.announcement_store as announcement_store

    frozen = datetime(2026, 5, 18, 9, 31, 42, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(announcement_store, "_now_announcement_datetime", lambda: frozen, raising=False)
    store = AnnouncementStore(tmp_path / "announcements.json")

    created = store.create_item(_announcement(id="", published_at=""))

    assert created["id"] == "ann-2026-05-18-09-31"
    assert created["published_at"] == "2026-05-18T09:31:00+08:00"


def test_store_create_item_deduplicates_same_minute_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.web.announcement_store as announcement_store

    frozen = datetime(2026, 5, 18, 9, 31, 42, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(announcement_store, "_now_announcement_datetime", lambda: frozen, raising=False)
    store = AnnouncementStore(tmp_path / "announcements.json")

    first = store.create_item(_announcement(id="", published_at="", title="第一条"))
    second = store.create_item(_announcement(id="", published_at="", title="第二条"))

    assert first["id"] == "ann-2026-05-18-09-31"
    assert second["id"] == "ann-2026-05-18-09-31-02"


class _FakeAuth:
    def __init__(self, account_id: str, capabilities: set[str]) -> None:
        self.account_id = account_id
        self.capabilities = capabilities


class _FakeServer:
    def __init__(self, store: AnnouncementStore, account_id: str = "admin", admin: bool = True) -> None:
        self.announcement_store = store
        self._account_id = account_id
        self._admin = admin

    async def _with_auth(self, request: web.Request) -> _FakeAuth:
        capabilities = {"admin_ops"} if self._admin else set()
        return _FakeAuth(self._account_id, capabilities)

    async def _with_capability(self, request: web.Request, capability: str) -> _FakeAuth:
        if not self._admin:
            raise web.HTTPForbidden(text="权限不足")
        return await self._with_auth(request)


@pytest.mark.asyncio
async def test_mark_seen_suppresses_unseen_for_same_user(tmp_path: Path) -> None:
    from bot.web.routes.announcement_routes import get_announcements, post_announcements_seen

    store = AnnouncementStore(tmp_path / "announcements.json")
    store.upsert_item(_announcement(id="ann-new"))
    server = _FakeServer(store)
    list_request = make_mocked_request("GET", "/api/announcements", app={"server": server})

    before = await get_announcements(list_request)
    assert before.status == 200
    assert store.list_for_user("admin")["has_unseen"] is True

    seen_request = make_mocked_request("POST", "/api/announcements/seen", app={"server": server})
    seen_request._read_bytes = b'{"latest_id":"ann-new"}'
    await post_announcements_seen(seen_request)

    assert store.list_for_user("admin")["has_unseen"] is False


@pytest.mark.asyncio
async def test_admin_upsert_requires_admin_capability(tmp_path: Path) -> None:
    from bot.web.routes.announcement_routes import post_admin_announcement

    server = _FakeServer(AnnouncementStore(tmp_path / "announcements.json"), admin=False)
    request = make_mocked_request("POST", "/api/admin/announcements", app={"server": server})
    request._read_bytes = json.dumps(_announcement()).encode("utf-8")

    with pytest.raises(web.HTTPForbidden):
        await post_admin_announcement(request)


@pytest.mark.asyncio
async def test_admin_post_generates_announcement_id_and_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.web.announcement_store as announcement_store
    from bot.web.routes.announcement_routes import post_admin_announcement

    frozen = datetime(2026, 5, 18, 9, 31, 42, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(announcement_store, "_now_announcement_datetime", lambda: frozen, raising=False)
    store = AnnouncementStore(tmp_path / "announcements.json")
    server = _FakeServer(store)
    payload = _announcement()
    payload.pop("id")
    payload.pop("published_at")
    request = make_mocked_request("POST", "/api/admin/announcements", app={"server": server})
    request._read_bytes = json.dumps(payload).encode("utf-8")

    response = await post_admin_announcement(request)
    body = json.loads(response.text or "{}")

    assert response.status == 200
    assert body["data"]["id"] == "ann-2026-05-18-09-31"
    assert body["data"]["published_at"] == "2026-05-18T09:31:00+08:00"
