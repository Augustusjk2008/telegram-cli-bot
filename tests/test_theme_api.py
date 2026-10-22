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
    server.theme_store = ThemeStore(tmp_path / "themes" / "accounts")
    sessions = {
        key: WebAuthSession(token=key, account=WebAccount(account_id=key, username=key,
            role="guest" if key == "guest" else "member", session_user_id=index),
            created_at="2026-10-22T00:00:00Z", capabilities=(CAP_ADMIN_OPS,) if key == "admin" else ())
        for index, key in enumerate(("alice", "bob", "admin", "guest"), start=100)
    }
    monkeypatch.setattr(server_module, "_WEB_AUTH_STORE", SimpleNamespace(
        get_session=lambda token: sessions.get(token), can_bootstrap_without_auth=lambda: False))
    monkeypatch.setattr(server_module, "_BOT_PERMISSION_STORE", SimpleNamespace(
        allowed_bots_for_account=lambda account: set(), owned_bot_aliases=lambda account: set()))
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


def create_input(**changes):
    return {"schemaVersion": 1, "expectedRevision": 0, "sourceId": "paper-daylight", "name": "个人主题", **changes}


@pytest.mark.asyncio
async def test_authenticated_member_crud_works_without_bot_or_admin_permissions(api):
    status, payload = await request(api, "GET", "/node/theme-test/api/ui/themes")
    assert status == 200 and payload["data"]["revision"] == 0
    status, payload = await request(api, "POST", body=create_input(activate=True))
    assert status == 200
    library = payload["data"]
    theme_id = library["themes"][1]["id"]
    assert library["selectedThemeId"] == theme_id
    status, payload = await request(api, "PATCH", f"/api/ui/themes/{theme_id}", body={
        "schemaVersion": 1, "expectedRevision": 1, "name": "修改后的名字",
        "appearance": {"colors": {"scheme": "dark", "overrides": {"surface.base": "#123456"}}},
    })
    assert status == 200 and payload["data"]["themes"][1]["appearance"]["colors"]["overrides"] == {"surface.base": "#123456FF"}
    status, payload = await request(api, "PATCH", "/api/ui/theme-selection", body={"themeId": "paper-daylight", "expectedRevision": 2})
    assert status == 200 and payload["data"]["selectedThemeId"] == "paper-daylight"
    status, payload = await request(api, "PATCH", "/api/ui/theme-selection", body={"themeId": theme_id, "expectedRevision": 3})
    assert status == 200 and payload["data"]["selectedThemeId"] == theme_id
    status, payload = await request(api, "DELETE", f"/api/ui/themes/{theme_id}", body={"expectedRevision": 4})
    assert status == 200 and payload["data"]["selectedThemeId"] == "paper-daylight"
    assert payload["data"]["revision"] == 5 and len(payload["data"]["themes"]) == 1


@pytest.mark.asyncio
async def test_accounts_including_admin_cannot_address_another_library(api):
    _, created = await request(api, "POST", body=create_input())
    theme_id = created["data"]["themes"][1]["id"]
    for account in ("bob", "admin"):
        status, payload = await request(api, "GET", "/api/ui/themes?accountId=alice&user_id=100", token=account,
                                        headers={"X-User-Id": "100", "X-Account-Id": "alice"})
        assert status == 200 and len(payload["data"]["themes"]) == 1
        for method, path, body in (
            ("POST", "/api/ui/themes", create_input(sourceId=theme_id)),
            ("PATCH", f"/api/ui/themes/{theme_id}", {"schemaVersion": 1, "expectedRevision": 0, "name": "接管"}),
            ("DELETE", f"/api/ui/themes/{theme_id}", {"expectedRevision": 0}),
            ("PATCH", "/api/ui/theme-selection", {"themeId": theme_id, "expectedRevision": 0}),
        ):
            status, payload = await request(api, method, path, token=account, body=body)
            assert status == 404 and payload["error"]["code"] == "theme_not_found"
        status, payload = await request(api, "POST", token=account, body=create_input(accountId="alice"))
        assert status == 400
    _, payload = await request(api, "GET")
    assert len(payload["data"]["themes"]) == 2 and payload["data"]["revision"] == 1


@pytest.mark.asyncio
async def test_guests_read_only_builtin_and_unauthenticated_requests_use_host_auth(api):
    status, payload = await request(api, "GET", token="guest")
    assert status == 200 and len(payload["data"]["themes"]) == 1
    for method, path, body in (
        ("POST", "/api/ui/themes", create_input()),
        ("PATCH", "/api/ui/themes/paper-daylight", {"schemaVersion": 1, "expectedRevision": 0}),
        ("DELETE", "/api/ui/themes/paper-daylight", {"expectedRevision": 0}),
        ("PATCH", "/api/ui/theme-selection", {"themeId": "paper-daylight", "expectedRevision": 0}),
    ):
        status, payload = await request(api, method, path, token="guest", body=body)
        assert status == 403 and payload["error"]["code"] == "theme_readonly"
    for token in ("", "invalid-token"):
        status, payload = await request(api, "GET", token=token)
        assert status == 401 and payload["error"]["code"] == "unauthorized"
    status, payload = await request(api, "GET", "/api/ui/themes?token=alice", token="")
    assert status == 401 and payload["error"]["code"] == "query_token_disabled"
    assert not api.server.theme_store.accounts_dir.exists()


@pytest.mark.asyncio
async def test_revision_conflicts_are_409_and_do_not_apply_stale_mutations(api):
    _, payload = await request(api, "POST", body=create_input())
    theme_id = payload["data"]["themes"][1]["id"]
    for method, path, body in (
        ("POST", "/api/ui/themes", create_input(activate=True)),
        ("PATCH", f"/api/ui/themes/{theme_id}", {"schemaVersion": 1, "expectedRevision": 0, "name": "旧草稿", "activate": True}),
        ("DELETE", f"/api/ui/themes/{theme_id}", {"expectedRevision": 0}),
        ("PATCH", "/api/ui/theme-selection", {"themeId": theme_id, "expectedRevision": 0}),
    ):
        status, result = await request(api, method, path, body=body)
        assert status == 409 and result["error"]["code"] == "theme_revision_conflict"
        assert result["error"]["data"]["revision"] == 1
    _, result = await request(api, "GET")
    assert result == payload


@pytest.mark.asyncio
async def test_bad_payloads_and_builtin_mutations_are_rejected(api):
    for body in ([], None, create_input(schemaVersion=2), create_input(expectedRevision=True),
                 create_input(appearance={"colors": {"scheme": "light", "overrides": {"unknown": "#FFFFFF"}}})):
        status, payload = await request(api, "POST", body=body)
        assert status == 400 and payload["ok"] is False
    for method, body in (
        ("PATCH", {"schemaVersion": 1, "expectedRevision": 0, "name": "覆盖"}),
        ("DELETE", {"expectedRevision": 0}),
    ):
        status, payload = await request(api, method, "/api/ui/themes/paper-daylight", body=body)
        assert status == 403 and payload["error"]["code"] == "theme_readonly"
    status, _ = await request(api, "PATCH", "/api/ui/theme-selection", body={
        "themeId": "paper-daylight", "expectedRevision": 0, "accountId": "bob"})
    assert status == 400
    status, _ = await request(api, "DELETE", "/api/ui/themes/paper-daylight", body={"expectedRevision": 0, "force": True})
    assert status == 400


@pytest.mark.asyncio
async def test_cookie_writes_keep_existing_origin_protection(api):
    cookie = {"Cookie": f"{server_module.AUTH_SESSION_COOKIE_NAME}=alice"}
    status, payload = await request(api, "POST", token="", headers=cookie, body=create_input())
    assert status == 403 and payload["error"]["code"] == "csrf_origin_rejected"
    status, _ = await request(api, "POST", token="", headers={**cookie, "Origin": "http://example.test"}, body=create_input())
    assert status == 200


@pytest.mark.asyncio
async def test_theme_account_binding_rejects_cookie_switch_before_any_read_or_write(api):
    headers = {"Cookie": f"{server_module.AUTH_SESSION_COOKIE_NAME}=bob",
               "Origin": "http://example.test", "X-UI-Account-ID": "alice"}
    for method, body in (("GET", None), ("POST", create_input())):
        status, payload = await request(api, method, token="", headers=headers, body=body)
        assert status == 409 and payload["error"]["code"] == "theme_account_changed"
    assert not api.server.theme_store.accounts_dir.exists()
    status, payload = await request(api, "GET", token="bob", headers={"X-UI-Account-ID": "bob"})
    assert status == 200 and payload["data"]["accountId"] == "bob"


@pytest.mark.asyncio
async def test_corrupt_library_falls_back_with_error_and_cannot_be_overwritten(api):
    await request(api, "POST", body=create_input())
    path = next(api.server.theme_store.accounts_dir.glob("*.json"))
    path.write_bytes(b'{"schemaVersion":2,"themes":')
    original = path.read_bytes()
    status, payload = await request(api, "GET")
    assert status == 200 and "原文件已保留" in payload["data"]["error"]
    assert len(payload["data"]["themes"]) == 1
    status, payload = await request(api, "POST", body=create_input())
    assert status == 500 and payload["error"]["code"] == "theme_store_unreadable"
    assert path.read_bytes() == original
