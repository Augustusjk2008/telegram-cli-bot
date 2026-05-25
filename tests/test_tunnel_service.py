"""TunnelService 重启续用行为测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.web.tunnel_service import TunnelService


def test_tunnel_service_build_local_url_brackets_ipv6_loopback():
    assert TunnelService._build_local_url("::1", 8765) == "http://[::1]:8765"


def test_tunnel_service_extract_public_url_normalizes_trycloudflare_http_to_https():
    assert (
        TunnelService._extract_public_url("INF quick tunnel: http://fresh.trycloudflare.com")
        == "https://fresh.trycloudflare.com"
    )


def test_tunnel_service_extract_public_url_ignores_non_https_non_cloudflare_url():
    assert TunnelService._extract_public_url("public url http://example.com") is None


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
         patch.object(service, "_can_resolve_public_url", return_value=True, create=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "running"
    assert snapshot["source"] == "quick_tunnel"
    assert snapshot["public_url"] == "https://stable.trycloudflare.com"
    assert snapshot["pid"] == 4321


@pytest.mark.asyncio
async def test_tunnel_service_reuses_persisted_starting_quick_tunnel(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "status": "starting",
                "source": "quick_tunnel",
                "public_url": "https://slow.trycloudflare.com",
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
         patch.object(service, "_can_resolve_public_url", return_value=True, create=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "starting"
    assert snapshot["source"] == "quick_tunnel"
    assert snapshot["public_url"] == "https://slow.trycloudflare.com"
    assert snapshot["pid"] == 4321
    assert "公网地址仍在传播" in snapshot["last_error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["::", "[::]"])
async def test_tunnel_service_reuses_persisted_ipv4_tunnel_for_ipv6_any_host(tmp_path: Path, host: str):
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
        host=host,
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
    )

    with patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch.object(service, "_can_connect_local_url", return_value=True, create=True), \
         patch.object(service, "_can_resolve_public_url", return_value=True, create=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "running"
    assert snapshot["source"] == "quick_tunnel"
    assert snapshot["public_url"] == "https://stable.trycloudflare.com"
    assert snapshot["pid"] == 4321


@pytest.mark.parametrize("host", ["::", "[::]"])
def test_tunnel_service_does_not_restore_unreachable_ipv4_tunnel_for_ipv6_any_host(tmp_path: Path, host: str):
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
        host=host,
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
    )

    with patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch.object(service, "_can_connect_local_url", return_value=False, create=True), \
         patch.object(service, "_clear_state_file") as clear_state_file:
        restored = service._try_restore_persisted_tunnel()

    assert restored is False
    clear_state_file.assert_called_once()


def test_tunnel_service_does_not_restore_persisted_tunnel_with_unresolvable_public_url(tmp_path: Path):
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
         patch.object(service, "_can_resolve_public_url", return_value=False, create=True), \
         patch.object(service, "_clear_state_file") as clear_state_file:
        restored = service._try_restore_persisted_tunnel()

    assert restored is False
    clear_state_file.assert_called_once()


@pytest.mark.asyncio
async def test_tunnel_service_start_waits_for_local_health_before_spawning_cloudflared(tmp_path: Path):
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(tmp_path / "web-tunnel-state.json"),
        startup_timeout=0.01,
        local_health_timeout=0.01,
    )

    with patch.object(service, "_wait_for_health", return_value=False), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "error"
    assert snapshot["public_url"] == ""
    assert "本地 Web 未就绪" in snapshot["last_error"]


@pytest.mark.asyncio
async def test_tunnel_service_start_keeps_slow_public_tunnel_starting(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
        startup_timeout=0.01,
        local_health_timeout=0.01,
        public_health_timeout=0.01,
    )

    class FakeStdout:
        def __init__(self):
            self._first = True

        def readline(self):
            if self._first:
                self._first = False
                return "https://fresh.trycloudflare.com\n"
            time.sleep(1.0)
            return ""

    class FakeProcess:
        def __init__(self):
            self.pid = 5555
            self.stdout = FakeStdout()
            self.terminated = False
            self.killed = False
            self.waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True
            return None

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def kill(self):
            self.killed = True
            return None

    health_calls: list[str] = []

    def fake_wait_for_health(base_url: str, *, timeout: float) -> bool:
        health_calls.append(base_url)
        return base_url == "http://127.0.0.1:8765"

    process = FakeProcess()

    with patch.object(service, "_wait_for_health", side_effect=fake_wait_for_health), \
         patch("bot.web.tunnel_service.subprocess.Popen", return_value=process):
        snapshot = await service.start()

    assert health_calls == ["http://127.0.0.1:8765", "https://fresh.trycloudflare.com"]
    assert snapshot["status"] == "starting"
    assert snapshot["public_url"] == "https://fresh.trycloudflare.com"
    assert snapshot["pid"] == 5555
    assert "公网地址仍在传播" in snapshot["last_error"]
    assert process.terminated is False
    assert process.waited is False
    assert process.killed is False
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["public_url"] == "https://fresh.trycloudflare.com"
    assert persisted["pid"] == 5555


@pytest.mark.parametrize("status", ["starting", "running"])
def test_tunnel_service_preserve_for_restart_keeps_active_state(tmp_path: Path, status: str):
    state_file = tmp_path / "web-tunnel-state.json"
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
    )
    service._set_snapshot(
        status=status,
        source="quick_tunnel",
        public_url="https://slow.trycloudflare.com",
        pid=5555,
        last_error="公网地址仍在传播: https://slow.trycloudflare.com",
    )

    with patch.object(service, "_is_cloudflared_process", return_value=True):
        snapshot = service.preserve_for_restart()

    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert snapshot["status"] == status
    assert persisted["status"] == status
    assert persisted["public_url"] == "https://slow.trycloudflare.com"
    assert persisted["pid"] == 5555


@pytest.mark.asyncio
async def test_tunnel_service_stop_terminates_restored_pid_and_clears_state(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "status": "running",
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
    service._set_snapshot(
        status="running",
        source="quick_tunnel",
        public_url="https://stable.trycloudflare.com",
        pid=4321,
        last_error="",
    )

    with patch.object(service, "_terminate_pid") as terminate_pid:
        snapshot = await service.stop()

    terminate_pid.assert_called_once_with(4321)
    assert snapshot["status"] == "stopped"
    assert snapshot["public_url"] == ""
    assert snapshot["pid"] is None
    assert not state_file.exists()


@pytest.mark.asyncio
async def test_tunnel_service_restart_stops_then_starts_new_tunnel(tmp_path: Path):
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(tmp_path / "web-tunnel-state.json"),
    )
    calls: list[str] = []

    async def fake_stop():
        calls.append("stop")
        return {"status": "stopped", "public_url": "", "pid": None}

    async def fake_start():
        calls.append("start")
        return {"status": "running", "public_url": "https://fresh.trycloudflare.com", "pid": 9876}

    with patch.object(service, "stop", side_effect=fake_stop), \
         patch.object(service, "start", side_effect=fake_start):
        snapshot = await service.restart()

    assert calls == ["stop", "start"]
    assert snapshot["public_url"] == "https://fresh.trycloudflare.com"
    assert snapshot["pid"] == 9876


@pytest.mark.asyncio
async def test_tunnel_service_start_cleans_stale_cloudflared_before_spawning(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://stale.trycloudflare.com",
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
        local_health_timeout=0.01,
    )
    events: list[str] = []

    def fake_terminate(pid: int) -> None:
        events.append(f"terminate:{pid}")

    def fake_popen(*args, **kwargs):
        events.append("popen")
        raise FileNotFoundError

    with patch.object(service, "_wait_for_health", return_value=True), \
         patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch.object(service, "_can_resolve_public_url", return_value=False, create=True), \
         patch.object(service, "_terminate_pid", side_effect=fake_terminate), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=fake_popen):
        snapshot = await service.start()

    assert events == ["terminate:4321", "popen"]
    assert snapshot["status"] == "error"
    assert snapshot["last_error"] == "未找到 cloudflared 可执行文件"


@pytest.mark.asyncio
async def test_tunnel_service_start_does_not_clean_non_cloudflared_stale_pid(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://stale.trycloudflare.com",
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
        local_health_timeout=0.01,
    )

    with patch.object(service, "_wait_for_health", return_value=True), \
         patch.object(service, "_is_cloudflared_process", return_value=False), \
         patch.object(service, "_terminate_pid", side_effect=AssertionError("should not terminate pid")), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=FileNotFoundError):
        snapshot = await service.start()

    assert snapshot["status"] == "error"
    assert snapshot["last_error"] == "未找到 cloudflared 可执行文件"


@pytest.mark.parametrize(
    "state_patch",
    [
        {"source": "manual_config"},
        {"local_url": "http://127.0.0.1:9999"},
    ],
)
def test_tunnel_service_cleanup_stale_persisted_tunnel_skips_mismatched_state(
    tmp_path: Path,
    state_patch: dict[str, str],
):
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(tmp_path / "web-tunnel-state.json"),
    )
    data = {
        "mode": "cloudflare_quick",
        "status": "running",
        "source": "quick_tunnel",
        "public_url": "https://stale.trycloudflare.com",
        "local_url": "http://127.0.0.1:8765",
        "pid": 4321,
    }
    data.update(state_patch)

    with patch.object(service, "_is_cloudflared_process", side_effect=AssertionError("should not inspect pid")), \
         patch.object(service, "_terminate_pid", side_effect=AssertionError("should not terminate pid")):
        service._cleanup_stale_persisted_tunnel(data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_mode"),
    [
        ({"mode": "disabled"}, "disabled"),
        ({"mode": "cloudflare_quick", "public_url": "https://manual.example.com"}, "manual"),
    ],
)
async def test_tunnel_service_start_skips_cleanup_outside_quick_mode(
    tmp_path: Path,
    kwargs: dict[str, str],
    expected_mode: str,
):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://stale.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "pid": 4321,
            }
        ),
        encoding="utf-8",
    )
    service = TunnelService(host="127.0.0.1", port=8765, state_file=str(state_file), **kwargs)

    with patch.object(service, "_cleanup_stale_persisted_tunnel", side_effect=AssertionError("should not cleanup")), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["mode"] == expected_mode


@pytest.mark.asyncio
async def test_tunnel_service_wait_until_public_ready_marks_running(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
        startup_timeout=0.01,
        local_health_timeout=0.01,
        public_health_timeout=0.01,
    )

    class FakeStdout:
        def __init__(self):
            self._first = True

        def readline(self):
            if self._first:
                self._first = False
                return "https://fresh.trycloudflare.com\n"
            time.sleep(1.0)
            return ""

    class FakeProcess:
        pid = 5555
        stdout = FakeStdout()

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    public_checks = [False, True]

    def fake_wait_for_health(base_url: str, *, timeout: float) -> bool:
        if base_url == "http://127.0.0.1:8765":
            return True
        return public_checks.pop(0)

    with patch.object(service, "_wait_for_health", side_effect=fake_wait_for_health), \
         patch("bot.web.tunnel_service.subprocess.Popen", return_value=FakeProcess()):
        starting = await service.start()
        ready = await service.wait_until_public_ready(timeout=0.01)

    assert starting["status"] == "starting"
    assert ready["status"] == "running"
    assert ready["public_url"] == "https://fresh.trycloudflare.com"
    assert ready["last_error"] == ""
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["status"] == "running"
    assert persisted["public_url"] == "https://fresh.trycloudflare.com"
    assert persisted["pid"] == 5555


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

    with patch.object(service, "_wait_for_health", return_value=True), \
         patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=fake_popen), \
         patch("bot.web.tunnel_service.build_subprocess_group_kwargs", return_value={"start_new_session": True}), \
         patch("bot.web.tunnel_service.threading.Thread", ImmediateThread), \
         patch("bot.web.tunnel_service.asyncio.to_thread", side_effect=fake_to_thread):
        snapshot = await service.start()

    assert snapshot["public_url"] == "https://fresh.trycloudflare.com"
    assert captured["kwargs"]["start_new_session"] is True
