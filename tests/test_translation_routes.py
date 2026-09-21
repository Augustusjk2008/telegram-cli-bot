from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.web.api_common import AuthContext, WebApiError, _require_capability
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_VIEW_CHAT_HISTORY
from bot.web.routes.translation_routes import register
from bot.web.translation_config import TranslationConfigStore


def build_routes(tmp_path, capabilities, payload=None):
    auth = AuthContext(user_id=1, token_used=True, capabilities=set(capabilities))

    async def authorize(request, capability):
        _require_capability(auth, capability)
        return auth

    server = SimpleNamespace(
        _with_capability=AsyncMock(side_effect=authorize),
        _parse_json=AsyncMock(return_value=payload),
    )
    store = TranslationConfigStore(tmp_path / "config.json")
    app = web.Application()
    register(app, server, service=SimpleNamespace(config_store=store))
    return {route.method: route.handler for route in app.router.routes()
            if route.resource.canonical == "/api/admin/chat-translation/config"}, store, server


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_admin_routes_require_global_capability_before_access(tmp_path, method):
    handlers, store, server = build_routes(tmp_path, [])
    request = make_mocked_request(method, "/api/admin/chat-translation/config")
    with pytest.raises(WebApiError) as caught:
        await handlers[method](request)
    assert caught.value.status == 403
    server._with_capability.assert_awaited_once_with(request, CAP_ADMIN_OPS)
    server._parse_json.assert_not_awaited()
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_admin_config_routes_redact_keys_and_map_validation_error(tmp_path):
    handlers, store, server = build_routes(tmp_path, [CAP_ADMIN_OPS], {
        "base_url": "https://provider.test/v1", "api_key": "sk-secret",
        "model": "translator", "translate_assistant_enabled": True,
    })
    for method in ("PATCH", "GET"):
        response = await handlers[method](make_mocked_request(method, "/api/admin/chat-translation/config"))
        payload = json.loads(response.text)
        assert response.status == 200 and payload["ok"] is True
        assert payload["data"]["api_key_set"] is True
        assert "api_key" not in payload["data"]
        assert "sk-secret" not in response.text
    server._parse_json.return_value = {"base_url": "invalid"}
    with pytest.raises(WebApiError) as caught:
        await handlers["PATCH"](make_mocked_request("PATCH", "/api/admin/chat-translation/config"))
    assert caught.value.status == 400
    assert caught.value.code == "invalid_translation_config"
    assert store.get_config().base_url == "https://provider.test/v1"


def build_bot_routes(tmp_path, monkeypatch, auth, payload=None):
    from tests.test_guest_access import _build_manager, _build_server

    server = _build_server(_build_manager(tmp_path), monkeypatch, tmp_path)
    server._with_auth = AsyncMock(return_value=auth)
    server._parse_json = AsyncMock(return_value=payload)
    store = TranslationConfigStore(tmp_path / "translation.json")
    app = web.Application()
    register(app, server, service=SimpleNamespace(config_store=store))
    handlers = {route.method: route.handler for route in app.router.routes()
                if route.resource.canonical == "/api/bots/{alias}/chat-translation"}
    return handlers, store, server


def bot_request(method, alias="main"):
    return make_mocked_request(method, f"/api/bots/{alias}/chat-translation", match_info={"alias": alias})


@pytest.mark.asyncio
async def test_bot_config_reports_global_status_without_exposing_provider(tmp_path, monkeypatch):
    auth = AuthContext(user_id=1, token_used=True, is_local_admin=True)
    handlers, store, server = build_bot_routes(tmp_path, monkeypatch, auth, {"enabled": False})
    store.update({"base_url": "https://provider.test/v1", "api_key": "sk-secret", "model": "translator", "translate_user_enabled": True})
    for method, enabled in [("GET", True), ("PATCH", False), ("GET", False)]:
        response = await handlers[method](bot_request(method))
        assert json.loads(response.text)["data"] == {
            "enabled": enabled, "global_translate_user_enabled": True,
            "global_translate_assistant_enabled": False, "can_edit": True,
        }
    assert server.manager.get_profile("team2").chat_translation_enabled is True
    assert store.get_config().translate_user_enabled is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"enabled": "false"}, {"enabled": 0}, {"enabled": None}, {"enabled": False, "api_key": "secret"}])
async def test_bot_config_rejects_invalid_updates(tmp_path, monkeypatch, payload):
    auth = AuthContext(user_id=1, token_used=True, is_local_admin=True)
    handlers, _, server = build_bot_routes(tmp_path, monkeypatch, auth, payload)
    with pytest.raises(WebApiError) as caught:
        await handlers["PATCH"](bot_request("PATCH"))
    assert caught.value.status == 400
    assert server.manager.main_profile.chat_translation_enabled is True


@pytest.mark.asyncio
@pytest.mark.parametrize("role,alias,method", [("guest", "main", "PATCH"), ("member", "team2", "PATCH"), ("member", "team2", "GET")])
async def test_bot_translation_rejects_readonly_or_unassigned_access(tmp_path, monkeypatch, role, alias, method):
    auth = AuthContext(user_id=1, token_used=True, role=role, account_id="unassigned", capabilities={CAP_VIEW_CHAT_HISTORY})
    handlers, _, server = build_bot_routes(tmp_path, monkeypatch, auth, {"enabled": False})
    with pytest.raises(WebApiError) as caught:
        await handlers[method](bot_request(method, alias))
    assert caught.value.status == 403
    server._parse_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_can_read_bot_translation_but_cannot_edit(tmp_path, monkeypatch):
    auth = AuthContext(user_id=1, token_used=True, role="guest", capabilities={CAP_VIEW_CHAT_HISTORY})
    handlers, _, _ = build_bot_routes(tmp_path, monkeypatch, auth)
    response = await handlers["GET"](bot_request("GET"))
    assert json.loads(response.text)["data"]["can_edit"] is False
