from __future__ import annotations

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
