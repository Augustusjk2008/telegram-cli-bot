from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.web import server
from bot.web.auth_store import WebAuthStore
from bot.web.login_throttle import LoginThrottle
from bot.web.permission_store import BotPermissionStore


class _DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    async def restart(self) -> dict[str, object]:
        return self.snapshot()

    def preserve_for_restart(self) -> dict[str, object]:
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }


def test_login_throttle_applies_exponential_cooldown_and_resets_on_success() -> None:
    now = [100.0]
    throttle = LoginThrottle(
        max_attempts=3,
        window_seconds=60,
        base_lock_seconds=2,
        max_lock_seconds=8,
        clock=lambda: now[0],
    )

    assert throttle.record_failure("127.0.0.1", "Alice") == 0
    assert throttle.record_failure("127.0.0.1", "alice") == 0
    assert throttle.record_failure("127.0.0.1", "ALICE") == 2
    assert throttle.check("127.0.0.1", "alice") == 2

    now[0] += 2.1
    assert throttle.record_failure("127.0.0.1", "alice") == 4
    assert throttle.diagnostics()["failure_count"] == 4

    throttle.record_success("127.0.0.1", "alice")
    assert throttle.check("127.0.0.1", "alice") == 0
    assert throttle.diagnostics()["active_keys"] == 0


def test_login_throttle_drops_failures_outside_observation_window() -> None:
    now = [10.0]
    throttle = LoginThrottle(max_attempts=2, window_seconds=10, clock=lambda: now[0])

    assert throttle.record_failure("client", "alice") == 0
    now[0] += 11
    assert throttle.record_failure("client", "alice") == 0


def test_login_client_only_trusts_forwarded_ip_from_loopback_proxy(monkeypatch) -> None:
    monkeypatch.setattr(server, "WEB_TRUST_PROXY_HEADERS", True)

    proxied = SimpleNamespace(remote="127.0.0.1", headers={"X-Forwarded-For": "203.0.113.7, 127.0.0.1"})
    direct = SimpleNamespace(remote="198.51.100.9", headers={"X-Forwarded-For": "203.0.113.8"})
    malformed = SimpleNamespace(remote="127.0.0.1", headers={"X-Forwarded-For": "not-an-ip"})

    assert server._login_throttle_client(proxied) == "203.0.113.7"
    assert server._login_throttle_client(direct) == "198.51.100.9"
    assert server._login_throttle_client(malformed) == "127.0.0.1"


@pytest.mark.asyncio
async def test_login_endpoint_normalizes_failures_and_enforces_retry_after(monkeypatch, tmp_path) -> None:
    auth_store = WebAuthStore(
        users_path=tmp_path / "users.json",
        register_codes_path=tmp_path / "register_codes.json",
    )
    invite_code = auth_store.create_register_code(created_by="test")["code"]
    auth_store.register_member("alice", "pw-123456", invite_code)
    monkeypatch.setattr(server, "_WEB_AUTH_STORE", auth_store)
    monkeypatch.setattr(server, "_BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    monkeypatch.setattr(server, "WEB_API_TOKEN", "")
    monkeypatch.setattr(server, "WEB_BASE_PATH", "")

    now = [100.0]
    web_server = server.WebApiServer(
        object(),
        host="127.0.0.1",
        port=8765,
        tunnel_service=_DummyTunnelService(),
    )
    web_server._login_throttle = LoginThrottle(
        max_attempts=2,
        window_seconds=60,
        base_lock_seconds=2,
        max_lock_seconds=8,
        clock=lambda: now[0],
    )
    headers = {"Host": "example.test", "Origin": "http://example.test"}

    async with TestServer(web_server._build_app()) as test_server:
        async with TestClient(test_server) as client:
            malformed = await client.post(
                "/api/auth/login",
                json={"username": "?", "password": "bad-password"},
                headers=headers,
            )
            first = await client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "bad-password"},
                headers=headers,
            )
            blocked = await client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "still-wrong"},
                headers=headers,
            )
            blocked_correct = await client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "pw-123456"},
                headers=headers,
            )
            now[0] += 2.1
            success = await client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "pw-123456"},
                headers=headers,
            )

            malformed_payload = await malformed.json()
            first_payload = await first.json()
            blocked_payload = await blocked.json()
            blocked_correct_payload = await blocked_correct.json()
            success_payload = await success.json()

    assert malformed.status == 401
    assert malformed_payload["error"]["code"] == "invalid_credentials"
    assert first.status == 401
    assert first_payload["error"]["code"] == "invalid_credentials"
    assert blocked.status == 429
    assert blocked_payload["error"] == {
        "code": "login_throttled",
        "message": "登录尝试过于频繁，请稍后再试",
        "data": {"retry_after": 2},
    }
    assert blocked_correct.status == 429
    assert blocked_correct_payload["error"]["data"]["retry_after"] == 2
    assert success.status == 200, success_payload
    assert success_payload["data"]["username"] == "alice"
