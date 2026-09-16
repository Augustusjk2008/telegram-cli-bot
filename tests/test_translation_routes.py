from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.web.api_common import AuthContext, WebApiError, _require_capability
from bot.web.auth_store import CAP_ADMIN_OPS
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
    return {route.method: route.handler for route in app.router.routes()}, store, server


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
