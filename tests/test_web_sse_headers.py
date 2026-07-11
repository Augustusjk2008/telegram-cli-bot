from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.auth_store import CAP_CHAT_SEND
from bot.web.permission_store import BotPermissionStore
from bot.web.server import WebApiServer, _sse_headers


class DummyTunnelService:
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


def test_sse_headers_disable_proxy_buffering_and_transforms():
    headers = _sse_headers()

    assert headers["Content-Type"] == "text/event-stream"
    assert "no-transform" in headers["Cache-Control"]
    assert "no-store" in headers["Cache-Control"]
    assert headers["Pragma"] == "no-cache"
    assert headers["Expires"] == "0"
    assert headers["Connection"] == "keep-alive"
    assert headers["X-Accel-Buffering"] == "no"


def _build_manager(tmp_path: Path) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            token="main_tok",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )


@pytest.mark.asyncio
async def test_chat_stream_sends_sse_headers_and_ready_comment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

    async def chat_send_only(_request, capability: str) -> AuthContext:
        assert capability == CAP_CHAT_SEND
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_CHAT_SEND})

    async def event_source():
        yield {"type": "done", "output": "ok", "elapsed_seconds": 0}

    def fake_stream_chat(*_args, **_kwargs):
        return event_source()

    monkeypatch.setattr(server, "_with_capability", chat_send_only)
    monkeypatch.setattr(server, "_schedule_chat_terminal_event", lambda **_kwargs: None)
    monkeypatch.setattr("bot.web.server.stream_chat", fake_stream_chat)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post("/api/bots/main/chat/stream", json={"message": "hello"})
            body = await response.text()

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    assert "no-store" in response.headers["Cache-Control"]
    assert "no-transform" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert body.startswith(": ready\n\n")
    assert 'event: done\ndata: {"type": "done", "output": "ok", "elapsed_seconds": 0}' in body


@pytest.mark.asyncio
async def test_chat_stream_rejects_invalid_resume_before_sse_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

    async def chat_send_only(_request, _capability: str) -> AuthContext:
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_CHAT_SEND})

    monkeypatch.setattr(server, "_with_capability", chat_send_only)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/bots/main/chat/stream",
                json={
                    "message": "",
                    "execution_mode": "native_agent",
                    "stream_id": "pit_missing",
                    "turn_id": "turn_missing",
                    "after_sequence": "not-an-integer",
                },
            )
            payload = await response.json()

    assert response.status == 400
    assert response.headers["Content-Type"].startswith("application/json")
    assert payload["error"]["code"] == "invalid_resume_sequence"


@pytest.mark.asyncio
async def test_chat_stream_rejects_expired_resume_before_sse_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

    async def chat_send_only(_request, _capability: str) -> AuthContext:
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_CHAT_SEND})

    monkeypatch.setattr(server, "_with_capability", chat_send_only)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/bots/main/chat/stream",
                json={
                    "message": "",
                    "execution_mode": "native_agent",
                    "stream_id": "pit_expired",
                    "turn_id": "turn_expired",
                    "after_sequence": 0,
                },
            )
            payload = await response.json()

    assert response.status == 410
    assert response.headers["Content-Type"].startswith("application/json")
    assert payload["error"]["code"] == "native_turn_stream_expired"


@pytest.mark.asyncio
async def test_terminal_sse_emits_structured_error_before_closing_on_queue_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _build_manager(tmp_path)
    server = WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())

    async def terminal_only(_request, _capability: str) -> AuthContext:
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_CHAT_SEND})

    class BrokenQueue:
        async def get(self):
            raise RuntimeError("terminal queue failed")

    async def attach(*_args, **_kwargs):
        return BrokenQueue(), {
            "pty_mode": True,
            "connection_text": "运行中",
            "last_seq": 0,
            "stream_id": "term-test",
        }

    async def detach(*_args, **_kwargs):
        return None

    monkeypatch.setattr(server, "_with_capability", terminal_only)
    monkeypatch.setattr(server._terminal_manager, "attach", attach)
    monkeypatch.setattr(server._terminal_manager, "detach", detach)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get("/api/terminal/session/stream?owner_id=default&protocol=2")
            body = await response.text()

    assert response.status == 200
    assert "event: error" in body
    assert "terminal_stream_error" in body
    assert "event: closed" in body
