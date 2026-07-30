from __future__ import annotations

import json
from datetime import date

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS
from bot.web.server import WebApiServer


class _DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def start(self):
        return self.snapshot()

    async def stop(self):
        return self.snapshot()

    async def restart(self):
        return self.snapshot()

    def preserve_for_restart(self):
        return self.snapshot()

    def snapshot(self):
        return {"mode": "disabled", "status": "stopped", "public_url": "", "local_url": ""}


class _FakeUsageService:
    def __init__(self) -> None:
        self.enabled = False
        self.stats_calls: list[tuple[date | None, date | None, list[str]]] = []

    async def config_snapshot(self):
        return {
            "enabled": self.enabled,
            "current_provider": {
                "key": "openai_official",
                "kind": "openai_official",
                "label": "OpenAI 官方",
                "base_url": None,
                "resolution": "config_missing",
            },
            "time_basis": {"mode": "server_local", "utc_offset": "+08:00", "today": "2026-07-26"},
            "available_range": {"first_date": None, "last_date": None},
        }

    async def update_enabled(self, enabled: bool):
        self.enabled = enabled
        return await self.config_snapshot()

    async def query_stats(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        provider_keys: list[str],
    ):
        self.stats_calls.append((start_date, end_date, provider_keys))
        return {
            "range": {
                "start_date": start_date.isoformat() if start_date else "2026-06-27",
                "end_date": end_date.isoformat() if end_date else "2026-07-26",
            },
            "enabled": self.enabled,
            "time_basis": {"mode": "server_local", "utc_offset": "+08:00", "today": "2026-07-26"},
            "available_range": {"first_date": None, "last_date": None},
            "available_providers": [],
            "selected_provider_keys": provider_keys,
            "totals": {"request_count": 0},
            "by_provider": [],
            "by_day": [],
            "daily_by_provider": [],
        }

    def diagnostics(self):
        return {"enabled": self.enabled}


def _build_server(monkeypatch: pytest.MonkeyPatch) -> tuple[WebApiServer, _FakeUsageService]:
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(object(), host="127.0.0.1", port=0, tunnel_service=_DummyTunnelService())
    service = _FakeUsageService()
    server.codex_usage_service = service

    async def authorize(_request, capability: str) -> AuthContext:
        assert capability == CAP_ADMIN_OPS
        return AuthContext(
            user_id=1,
            token_used=True,
            account_id="admin",
            username="admin",
            capabilities={CAP_ADMIN_OPS},
            is_local_admin=False,
        )

    monkeypatch.setattr(server, "_with_capability", authorize)
    return server, service


@pytest.mark.asyncio
async def test_codex_usage_config_get_and_patch_validate_real_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    server, service = _build_server(monkeypatch)
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            initial = await client.get("/api/admin/codex-usage/config")
            enabled = await client.patch("/api/admin/codex-usage/config", json={"enabled": True})
            invalid = await client.patch("/api/admin/codex-usage/config", json={"enabled": "true"})
            initial_text = await initial.text()
            enabled_text = await enabled.text()
            invalid_text = await invalid.text()

    assert initial.status == 200
    assert initial.content_type == "application/json"
    assert json.loads(initial_text)["data"]["enabled"] is False
    assert enabled.status == 200
    assert json.loads(enabled_text)["data"]["enabled"] is True
    assert service.enabled is True
    assert invalid.status == 400
    assert json.loads(invalid_text)["error"]["code"] == "invalid_enabled"


@pytest.mark.asyncio
async def test_codex_usage_stats_parses_dates_and_repeated_provider_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    server, service = _build_server(monkeypatch)
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get(
                "/api/admin/codex-usage/stats",
                params=[
                    ("start_date", "2026-07-01"),
                    ("end_date", "2026-07-26"),
                    ("provider", "openai_official"),
                    ("provider", "unknown"),
                ],
            )
            response_text = await response.text()

    assert response.status == 200
    assert service.stats_calls == [(date(2026, 7, 1), date(2026, 7, 26), ["openai_official", "unknown"])]
    assert json.loads(response_text)["data"]["selected_provider_keys"] == ["openai_official", "unknown"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "?start_date=2026-07-01",
        "?start_date=bad&end_date=2026-07-26",
        "?start_date=2026-07-27&end_date=2026-07-26",
    ],
)
async def test_codex_usage_stats_rejects_invalid_date_ranges(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    server, _service = _build_server(monkeypatch)
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get(f"/api/admin/codex-usage/stats{query}")
            response_text = await response.text()

    assert response.status == 400
    assert json.loads(response_text)["error"]["code"] == "invalid_date_range"


@pytest.mark.asyncio
async def test_codex_usage_routes_require_admin_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    server, _service = _build_server(monkeypatch)

    async def reject(_request, _capability: str):
        raise WebApiError(403, "forbidden", "权限不足")

    monkeypatch.setattr(server, "_with_capability", reject)
    app = server._build_app()

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get("/api/admin/codex-usage/config")
            response_text = await response.text()

    assert response.status == 403
    assert json.loads(response_text)["error"]["code"] == "forbidden"
