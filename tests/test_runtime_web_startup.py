import json
import socket
from contextlib import closing
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.main import _get_web_access_lines
from bot.web.runtime_binding import RuntimeWebBind, WebPortInUseError, resolve_runtime_web_bind
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


def test_resolve_runtime_web_bind_raises_typed_error_without_fallback() -> None:
    held_socket, requested_port = _hold_tcp_port("127.0.0.1")
    try:
        with pytest.raises(WebPortInUseError) as exc_info:
            resolve_runtime_web_bind("127.0.0.1", requested_port, allow_port_fallback=False)
    finally:
        held_socket.close()

    assert exc_info.value.port == requested_port
    assert exc_info.value.host == "127.0.0.1"


@pytest.mark.asyncio
async def test_health_reports_runtime_port() -> None:
    server = WebApiServer(object(), host="127.0.0.1", port=8768, tunnel_service=DummyTunnelService())

    response = await server.health(None)
    payload = json.loads(response.text)

    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 8768


@pytest.mark.asyncio
async def test_web_base_path_serves_api_and_spa(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "/node/nanjing-laptop")
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    server = WebApiServer(object(), host="127.0.0.1", port=8768, tunnel_service=DummyTunnelService())
    monkeypatch.setattr(server, "_get_static_dir", lambda subdir=None: str(dist / subdir) if subdir else str(dist))

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            root_health = await client.get("/api/health")
            sub_health = await client.get("/node/nanjing-laptop/api/health")
            root_asset = await client.get("/assets/app.js")
            sub_asset = await client.get("/node/nanjing-laptop/assets/app.js")
            sub_spa = await client.get("/node/nanjing-laptop/xxx")

            assert root_health.status == 200
            assert sub_health.status == 200
            assert root_asset.status == 200
            assert sub_asset.status == 200
            assert sub_spa.status == 200
            sub_spa_text = await sub_spa.text()
            assert "app" in sub_spa_text
            assert "window.__TCB_PUBLIC_ENV__" in sub_spa_text
            assert '"VITE_API_BASE_URL": "/node/nanjing-laptop"' in sub_spa_text

