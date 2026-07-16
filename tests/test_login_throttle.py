from __future__ import annotations

from types import SimpleNamespace

from bot.web import server
from bot.web.login_throttle import LoginThrottle


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
