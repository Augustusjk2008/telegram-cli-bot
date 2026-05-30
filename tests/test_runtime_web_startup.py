import json
import socket
from contextlib import closing

import pytest

from bot.main import _get_web_access_lines
from bot.web.runtime_binding import RuntimeWebBind, resolve_runtime_web_bind
from bot.web.server import WebApiServer


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


def test_resolve_runtime_web_bind_uses_next_port_when_requested_port_is_busy() -> None:
    held_socket, requested_port = _hold_tcp_port("127.0.0.1")
    try:
        bind = resolve_runtime_web_bind("127.0.0.1", requested_port)
    finally:
        held_socket.close()

    assert bind.configured_port == requested_port
    assert bind.actual_port > requested_port
    assert bind.port_changed is True


@pytest.mark.asyncio
async def test_health_reports_runtime_port() -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8768, tunnel_service=DummyTunnelService())

    response = await server.health(None)
    payload = json.loads(response.text)

    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 8768


