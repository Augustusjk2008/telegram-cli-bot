import json
import socket
from contextlib import closing

import pytest

from bot.main import _get_web_access_lines
from bot.web.runtime_binding import RuntimeWebBind, resolve_runtime_web_bind
from bot.web.server import WebApiServer
from bot.web.tunnel_service import TunnelService


class DummyTunnelService:
    def __init__(self) -> None:
        self._snapshot = {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }

    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return dict(self._snapshot)

    async def stop(self) -> dict[str, object]:
        return dict(self._snapshot)

    async def restart(self) -> dict[str, object]:
        return dict(self._snapshot)

    def preserve_for_restart(self) -> dict[str, object]:
        return dict(self._snapshot)

    def snapshot(self) -> dict[str, object]:
        return dict(self._snapshot)


def _hold_tcp_port(host: str) -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def test_resolve_runtime_web_bind_keeps_requested_port_when_available() -> None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        requested_port = probe.getsockname()[1]

    bind = resolve_runtime_web_bind("127.0.0.1", requested_port)

    assert bind == RuntimeWebBind(host="127.0.0.1", configured_port=requested_port, actual_port=requested_port)
    assert bind.port_changed is False


def test_resolve_runtime_web_bind_uses_next_port_when_requested_port_is_busy() -> None:
    held_socket, requested_port = _hold_tcp_port("127.0.0.1")
    try:
        bind = resolve_runtime_web_bind("127.0.0.1", requested_port)
    finally:
        held_socket.close()

    assert bind.configured_port == requested_port
    assert bind.actual_port > requested_port
    assert bind.port_changed is True


def test_resolve_runtime_web_bind_uses_next_port_for_wildcard_when_loopback_port_is_busy() -> None:
    held_socket, requested_port = _hold_tcp_port("127.0.0.1")
    try:
        bind = resolve_runtime_web_bind("0.0.0.0", requested_port)
    finally:
        held_socket.close()

    assert bind.configured_port == requested_port
    assert bind.actual_port > requested_port
    assert bind.port_changed is True


def test_resolve_runtime_web_bind_uses_next_port_for_loopback_when_wildcard_port_is_busy() -> None:
    held_socket, requested_port = _hold_tcp_port("0.0.0.0")
    try:
        bind = resolve_runtime_web_bind("127.0.0.1", requested_port)
    finally:
        held_socket.close()

    assert bind.configured_port == requested_port
    assert bind.actual_port > requested_port
    assert bind.port_changed is True


def test_get_web_access_lines_use_runtime_port() -> None:
    bind = RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8767)

    assert _get_web_access_lines(bind) == ["   http://127.0.0.1:8767"]


@pytest.mark.asyncio
async def test_health_reports_runtime_port() -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8768, tunnel_service=DummyTunnelService())

    response = await server.health(None)
    payload = json.loads(response.text)

    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 8768


def test_tunnel_service_uses_runtime_port_for_local_url() -> None:
    tunnel = TunnelService(host="127.0.0.1", port=8769, mode="cloudflare_quick")

    assert tunnel.snapshot()["local_url"] == "http://127.0.0.1:8769"


@pytest.mark.asyncio
async def test_notify_tunnel_public_url_prints_qr_for_quick_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    printed_urls: list[str] = []

    monkeypatch.setattr(server, "_copy_text_to_clipboard", lambda text: False)
    monkeypatch.setattr(server, "_print_public_url_qr", lambda public_url: printed_urls.append(public_url) or True)

    await server._notify_tunnel_public_url(
        {
            "status": "running",
            "source": "quick_tunnel",
            "public_url": "https://demo.trycloudflare.com",
        },
        reason="test",
    )

    assert printed_urls == ["https://demo.trycloudflare.com"]


def test_print_public_url_qr_returns_false_when_renderer_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

    def raise_error(public_url: str) -> str:
        raise RuntimeError(f"boom: {public_url}")

    monkeypatch.setattr(server, "_build_public_url_qr_text", raise_error)

    assert server._print_public_url_qr("https://demo.trycloudflare.com") is False


def test_build_public_url_qr_text_uses_solid_blocks() -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

    qr_text = server._build_public_url_qr_text("https://demo.trycloudflare.com")

    assert "██" in qr_text
    assert "##" not in qr_text
