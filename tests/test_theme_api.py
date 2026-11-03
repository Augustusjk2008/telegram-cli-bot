from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot.web import server as server_module
from bot.web.auth_store import CAP_ADMIN_OPS, WebAccount, WebAuthSession
from bot.web.server import WebApiServer, error_middleware
from bot.web.theme_store import ThemeStore


@pytest.fixture
def api(tmp_path, monkeypatch):
    server = object.__new__(WebApiServer)
    server.manager = SimpleNamespace(main_profile=SimpleNamespace(alias="main"), managed_profiles={})
    server.theme_store = ThemeStore(tmp_path / "themes" / "library.json")
    sessions = {
        key: WebAuthSession(
            token=key,
            account=WebAccount(
                account_id=key,
                username=key,
                role="guest" if key == "guest" else "member",
                session_user_id=index,
            ),
            created_at="2026-10-22T00:00:00Z",
            capabilities=(CAP_ADMIN_OPS,) if key == "admin" else (),
        )
        for index, key in enumerate(("alice", "admin", "guest"), start=100)
    }
    monkeypatch.setattr(
        server_module,
        "_WEB_AUTH_STORE",
        SimpleNamespace(get_session=lambda token: sessions.get(token), can_bootstrap_without_auth=lambda: False),
    )
    monkeypatch.setattr(server_module, "_BOT_PERMISSION_STORE", SimpleNamespace(
        allowed_bots_for_account=lambda account: set(), owned_bot_aliases=lambda account: set(),
    ))
    monkeypatch.setattr(server_module, "_is_loopback_auto_auth_allowed", lambda request: False)
    monkeypatch.setattr(server_module, "WEB_API_TOKEN", "")
    monkeypatch.setattr(server_module, "WEB_BASE_PATH", "/node/theme-test")
    monkeypatch.setattr(server_module, "WEB_PUBLIC_URL", "")
    return SimpleNamespace(server=server, app=server._build_app())


async def request(api, method, path="/api/ui/themes", *, token="alice", body=None, headers=None):
    request_headers = {"Host": "example.test", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    req = make_mocked_request(method, path, headers=request_headers, app=api.app)
    req._match_info = await api.app.router.resolve(req)
    req._match_info.add_app(api.app)
    req.json = AsyncMock(return_value=body)
    response = await error_middleware(req, req.match_info.handler)
    return response.status, json.loads(response.text)


def create_input() -> dict:
    return {
        "schemaVersion": 1,
        "expectedRevision": 0,
        "sourceId": "paper-daylight",
        "name": "个人主题",
    }


def import_input() -> dict:
    return {
        "expectedRevision": 0,
        "document": {
            "schemaVersion": 1,
            "name": "导入主题",
            "baseId": "paper-daylight",
            "appearance": {"colors": {"scheme": "light", "overrides": {}}},
        },
    }


@pytest.mark.asyncio
async def test_public_and_authenticated_reads_return_the_packaged_presets(api):
    status, public = await request(api, "GET", "/api/public/ui/themes", token="")
    assert status == 200
    assert [theme["name"] for theme in public["data"]["themes"]] == [
        "钢铁核心",
        "阿波罗计划",
        "薄荷柑橘",
    ]
    assert all(theme["readonly"] is True for theme in public["data"]["themes"])

    status, authenticated = await request(api, "GET")
    assert status == 200 and authenticated["data"] == public["data"]


@pytest.mark.asyncio
async def test_members_and_admins_can_select_but_cannot_modify_presets(api):
    _, listed = await request(api, "GET")
    selected_id = listed["data"]["themes"][-1]["id"]
    status, selected = await request(api, "PATCH", "/api/ui/theme-selection", body={
        "themeId": selected_id,
        "expectedRevision": listed["data"]["revision"],
    })
    assert status == 200 and selected["data"]["selectedThemeId"] == selected_id
    assert selected_id == "theme_92ba863d3714c089235dfcef47ce3415"

    operations = [
        ("POST", "/api/ui/themes", create_input()),
        ("POST", "/api/ui/themes/import", import_input()),
        ("PATCH", f"/api/ui/themes/{selected_id}", {"schemaVersion": 1, "expectedRevision": 1, "name": "修改"}),
        ("DELETE", f"/api/ui/themes/{selected_id}", {"expectedRevision": 1}),
        ("POST", "/api/ui/theme-assets", None),
    ]
    for token in ("alice", "admin"):
        for method, path, body in operations:
            status, payload = await request(api, method, path, token=token, body=body)
            assert status == 403, (token, method, path, payload)
            assert payload["error"]["code"] == "theme_readonly"


@pytest.mark.asyncio
async def test_guest_can_preview_but_cannot_change_shared_selection(api):
    status, payload = await request(api, "GET", "/api/public/ui/themes", token="")
    assert status == 200
    selected_id = payload["data"]["themes"][-1]["id"]
    status, payload = await request(api, "PATCH", "/api/ui/theme-selection", token="guest", body={
        "themeId": selected_id,
        "expectedRevision": 0,
    })
    assert status == 403 and payload["error"]["code"] == "theme_readonly"


@pytest.mark.asyncio
async def test_corrupt_runtime_selection_is_reported_without_replacing_packaged_presets(api):
    path = api.server.theme_store.library_path
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    status, payload = await request(api, "GET")

    assert status == 200
    assert "原文件已保留" in payload["data"]["error"]
    assert len(payload["data"]["themes"]) == 3
