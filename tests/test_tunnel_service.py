"""TunnelService 重启续用行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.web.tunnel_service import TunnelService


def test_tunnel_service_build_local_url_brackets_ipv6_loopback():
    assert TunnelService._build_local_url("::1", 8765) == "http://[::1]:8765"


@pytest.mark.parametrize("host", ["::", "[::]"])
def test_tunnel_service_build_local_url_uses_ipv6_loopback_for_any(host: str):
    assert TunnelService._build_local_url(host, 8765) == "http://[::1]:8765"


@pytest.mark.asyncio
async def test_tunnel_service_reuses_persisted_quick_tunnel_without_starting_new_process(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "source": "quick_tunnel",
                "public_url": "https://stable.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "pid": 4321,
            }
        ),
        encoding="utf-8",
    )

    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
    )

    with patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "running"
    assert snapshot["source"] == "quick_tunnel"
    assert snapshot["public_url"] == "https://stable.trycloudflare.com"
    assert snapshot["pid"] == 4321


@pytest.mark.asyncio
async def test_tunnel_service_reuses_persisted_ipv4_tunnel_for_ipv6_any_host(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "source": "quick_tunnel",
                "public_url": "https://stable.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "pid": 4321,
            }
        ),
        encoding="utf-8",
    )

    service = TunnelService(
        host="::",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
    )

    with patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "running"
    assert snapshot["source"] == "quick_tunnel"
    assert snapshot["public_url"] == "https://stable.trycloudflare.com"
    assert snapshot["pid"] == 4321


@pytest.mark.asyncio
async def test_tunnel_service_start_passes_platform_process_kwargs(tmp_path: Path):
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(tmp_path / "web-tunnel-state.json"),
    )

    class FakeStdout:
        def __init__(self):
            self._lines = ["https://fresh.trycloudflare.com\n", ""]

        def __iter__(self):
            return iter(["https://fresh.trycloudflare.com\n"])

        def readline(self):
            return self._lines.pop(0)

    class FakeProcess:
        def __init__(self):
            self.pid = 5555
            self.stdout = FakeStdout()
            self._poll_count = 0

        def poll(self):
            self._poll_count += 1
            return None if self._poll_count == 1 else 0

    captured: dict[str, object] = {}

    def fake_popen(*args, **kwargs):
        captured["kwargs"] = kwargs
        return FakeProcess()

    class ImmediateThread:
        def __init__(self, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    with patch("bot.web.tunnel_service.subprocess.Popen", side_effect=fake_popen), \
         patch("bot.web.tunnel_service.build_subprocess_group_kwargs", return_value={"start_new_session": True}), \
         patch("bot.web.tunnel_service.threading.Thread", ImmediateThread), \
         patch("bot.web.tunnel_service.asyncio.to_thread", side_effect=fake_to_thread):
        snapshot = await service.start()

    assert snapshot["public_url"] == "https://fresh.trycloudflare.com"
    assert captured["kwargs"]["start_new_session"] is True
