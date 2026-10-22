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
    assert library["scope"] == "global" and "accountId" not in library
    theme_id = library["themes"][1]["id"]
    assert library["selectedThemeId"] == theme_id
    for token in ("alice", "bob", "admin", "guest"):
        status, shared = await request(api, "GET", token=token)
        assert status == 200 and shared["data"] == library
    status, payload = await request(api, "PATCH", f"/api/ui/themes/{theme_id}", token="bob", body={
        "schemaVersion": 1, "expectedRevision": 1, "name": "修改后的名字",
        "appearance": {"colors": {"scheme": "dark", "overrides": {"surface.base": "#123456"}}},
    })
    assert status == 200 and payload["data"]["themes"][1]["appearance"]["colors"]["overrides"] == {"surface.base": "#123456FF"}
    _, shared = await request(api, "GET", token="alice")
    assert shared == payload
    status, payload = await request(api, "PATCH", "/api/ui/theme-selection", body={"themeId": "paper-daylight", "expectedRevision": 2})
    assert status == 200 and payload["data"]["selectedThemeId"] == "paper-daylight"
    status, payload = await request(api, "PATCH", "/api/ui/theme-selection", token="bob", body={"themeId": theme_id, "expectedRevision": 3})
    assert status == 200 and payload["data"]["selectedThemeId"] == theme_id
    _, shared = await request(api, "GET", token="alice")
    assert shared == payload
    status, payload = await request(api, "DELETE", f"/api/ui/themes/{theme_id}", token="bob", body={"expectedRevision": 4})
    assert status == 200 and payload["data"]["selectedThemeId"] == "paper-daylight"
    assert payload["data"]["revision"] == 5 and len(payload["data"]["themes"]) == 1


@pytest.mark.asyncio
async def test_account_headers_and_queries_do_not_select_a_library(api):
    _, created = await request(api, "POST", body=create_input())
    for account in ("bob", "admin"):
        status, payload = await request(api, "GET", "/api/ui/themes?accountId=alice&user_id=100", token=account,
                                        headers={"X-User-Id": "100", "X-Account-Id": "alice", "X-UI-Account-ID": "alice"})
        assert status == 200 and payload == created
        status, payload = await request(api, "POST", token=account, body=create_input(accountId="alice"))
        assert status == 400
    status, copied = await request(api, "POST", token="bob", body=create_input(
        expectedRevision=1, sourceId=created["data"]["themes"][1]["id"], name="共享副本"))
    assert status == 200 and len(copied["data"]["themes"]) == 3
    _, payload = await request(api, "GET", token="alice")
    assert payload == copied


@pytest.mark.asyncio
async def test_guests_read_global_library_and_unauthenticated_requests_use_host_auth(api):
    _, created = await request(api, "POST", body=create_input(activate=True))
    status, payload = await request(api, "GET", token="guest")
    assert status == 200 and payload == created
    before = api.server.theme_store.library_path.read_bytes()
    for method, path, body in (
        ("POST", "/api/ui/themes", create_input()),
        ("PATCH", "/api/ui/themes/paper-daylight", {"schemaVersion": 1, "expectedRevision": 0}),
        ("DELETE", "/api/ui/themes/paper-daylight", {"expectedRevision": 0}),
        ("PATCH", "/api/ui/theme-selection", {"themeId": "paper-daylight", "expectedRevision": 0}),
    ):
        status, payload = await request(api, method, path, token="guest", body=body,
                                        headers={"X-UI-Account-ID": "alice"})
        assert status == 403 and payload["error"]["code"] == "theme_readonly"
    for token in ("", "invalid-token"):
        status, payload = await request(api, "GET", token=token)
        assert status == 401 and payload["error"]["code"] == "unauthorized"
    status, payload = await request(api, "GET", "/api/ui/themes?token=alice", token="")
    assert status == 401 and payload["error"]["code"] == "query_token_disabled"
    assert api.server.theme_store.library_path.read_bytes() == before


@pytest.mark.asyncio
async def test_login_page_can_read_themes_without_auth_but_cannot_mutate_them(api):
    _, created = await request(api, "POST", body=create_input(activate=True))
    theme_id = created["data"]["selectedThemeId"]
    before = api.server.theme_store.library_path.read_bytes()
    for path in ("/api/public/ui/themes", "/node/theme-test/api/public/ui/themes"):
        status, payload = await request(api, "GET", path, token="")
        assert status == 200 and payload == created
    for method, path, body in (
        ("POST", "/api/ui/themes", create_input(expectedRevision=1)),
        ("PATCH", f"/api/ui/themes/{theme_id}", {"schemaVersion": 1, "expectedRevision": 1, "name": "修改"}),
        ("DELETE", f"/api/ui/themes/{theme_id}", {"expectedRevision": 1}),
        ("PATCH", "/api/ui/theme-selection", {"themeId": "paper-daylight", "expectedRevision": 1}),
    ):
        status, payload = await request(api, method, path, token="", body=body)
        assert status == 401 and payload["error"]["code"] == "unauthorized"
    assert api.server.theme_store.library_path.read_bytes() == before


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
        status, result = await request(api, method, path, token="bob", body=body)
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
async def test_stale_account_header_is_ignored_for_authenticated_reads_and_writes(api):
    headers = {"Cookie": f"{server_module.AUTH_SESSION_COOKIE_NAME}=bob",
               "Origin": "http://example.test", "X-UI-Account-ID": "alice"}
    status, payload = await request(api, "POST", token="", headers=headers, body=create_input())
    assert status == 200 and payload["data"]["scope"] == "global"
    status, read = await request(api, "GET", token="", headers=headers)
    assert status == 200 and read == payload and "accountId" not in read["data"]


@pytest.mark.asyncio
async def test_corrupt_library_falls_back_with_error_and_cannot_be_overwritten(api):
    await request(api, "POST", body=create_input())
    path = api.server.theme_store.library_path
    path.write_bytes(b'{"schemaVersion":2,"themes":')
    original = path.read_bytes()
    status, payload = await request(api, "GET")
    assert status == 200 and "原文件已保留" in payload["data"]["error"]
    assert len(payload["data"]["themes"]) == 1
    status, payload = await request(api, "POST", body=create_input())
    assert status == 500 and payload["error"]["code"] == "theme_store_unreadable"
    assert path.read_bytes() == original
