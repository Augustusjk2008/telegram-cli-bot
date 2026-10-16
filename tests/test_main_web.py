"""主进程 Web 启动相关测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from bot.web.runtime_binding import WebPortInUseError

@pytest.fixture(autouse=True)
def _prevent_real_browser_open(monkeypatch):
    import bot.main as main_module

    monkeypatch.setattr(main_module.webbrowser, "open", lambda *args, **kwargs: True)

@pytest.mark.asyncio
@pytest.mark.parametrize("restart_requested", [False, True])
@pytest.mark.parametrize("migration_state", ["completed", "failed", "awaiting_restart"])
async def test_run_all_bots_stops_web_server_with_restart_policy(monkeypatch, restart_requested, migration_state):
    import bot.main as main_module
    fake_manager = MagicMock()
    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    monkeypatch.setattr(main_module.config, "RESTART_REQUESTED", False)
    fake_web_server.stop = AsyncMock()
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    monkeypatch.setattr(main_module, "_allow_runtime_port_fallback", lambda: True)
    fake_native_service = MagicMock()
    fake_native_service.shutdown = AsyncMock()
    migration_service = MagicMock()
    migration_service.status.return_value = {"state": migration_state}
    save_sessions = MagicMock()
    monkeypatch.setattr(main_module, "StorageMigrationService", lambda _repo: migration_service)
    monkeypatch.setattr("bot.sessions.save_all_sessions", save_sessions)

    class FakeEvent:
        async def wait(self):
            main_module.config.RESTART_REQUESTED = restart_requested

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch("bot.main.get_native_agent_service", return_value=fake_native_service), \
         patch.object(main_module.asyncio, "Event", return_value=FakeEvent()), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()
    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=restart_requested)
    fake_native_service.shutdown.assert_awaited_once()
    assert save_sessions.call_count == (0 if migration_state == "awaiting_restart" else 1)

@pytest.mark.asyncio
async def test_run_all_bots_requires_web_runtime(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()

    monkeypatch.setattr(main_module.config, "WEB_ENABLED", False)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=MagicMock()):
        with pytest.raises(RuntimeError, match="WEB_ENABLED 不能为 false"):
            await main_module.run_all_bots()


def test_main_exits_without_retry_when_configured_web_port_is_busy(monkeypatch):
    import bot.main as main_module

    calls = {"sleep": 0}

    def raise_port_in_use():
        raise WebPortInUseError(8765, "0.0.0.0")

    monkeypatch.setattr(main_module, "validate_cli_type", lambda _cli_type: None)
    monkeypatch.setattr(main_module, "disable_console_quick_edit", lambda: None)
    monkeypatch.setattr(main_module, "suppress_windows_error_dialogs", lambda: None)
    monkeypatch.setattr(main_module, "prevent_system_sleep", lambda: None)
    monkeypatch.setattr(main_module, "run_all_bots", raise_port_in_use)
    monkeypatch.setattr(main_module.time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert calls["sleep"] == 0


def test_web_runtime_state_records_actual_port(monkeypatch, tmp_path):
    import bot.main as main_module

    state_path = tmp_path / "runtime_state.json"
    bind = main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8767)
    monkeypatch.setattr(main_module, "get_web_runtime_state_path", lambda: state_path)

    main_module._write_web_runtime_state(bind)

    payload = __import__("json").loads(state_path.read_text(encoding="utf-8"))
    assert payload["configured_port"] == 8765
    assert payload["actual_port"] == 8767

    main_module._clear_web_runtime_state()

    assert not state_path.exists()


def test_chat_voice_route_is_registered():
    from bot.web.routes import chat_routes

    app = web.Application()
    chat_routes.register(app, MagicMock())

    assert any(
        route.resource is not None
        and route.resource.canonical == "/api/bots/{alias}/chat/voice"
        for route in app.router.routes()
    )


@pytest.mark.asyncio
async def test_chat_voice_is_rejected_when_feature_is_disabled(monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    from bot.web.api_common import AuthContext, WebApiError
    from bot.web.auth_store import CAP_CHAT_SEND
    from bot.web.server import WebApiServer

    server = object.__new__(WebApiServer)
    server.manager = MagicMock()
    server._with_websocket_capability = AsyncMock(
        return_value=AuthContext(user_id=1, token_used=True, account_id="account", capabilities={CAP_CHAT_SEND})
    )
    server._manager_alias = lambda _request: "main"
    server._request_agent_id = lambda _request: "main"
    server._request_execution_mode = lambda _request, **_kwargs: "cli"
    monkeypatch.setattr("bot.web.server.config.TCB_CODEX_SERVER_VOICE_ENABLED", False)

    with pytest.raises(WebApiError) as exc_info:
        await server.chat_voice_ws(make_mocked_request(
            "GET", "/api/bots/main/chat/voice", match_info={"alias": "main"},
        ))
    assert exc_info.value.code == "voice_disabled"


@pytest.mark.asyncio
async def test_chat_voice_occupied_connection_gets_structured_error_after_handshake(monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    from bot.codex_server.voice import VoiceLeaseRegistry
    from bot.web.api_common import AuthContext
    from bot.web.auth_store import CAP_CHAT_SEND
    from bot.web.server import WebApiServer

    class FakeWebSocket:
        def __init__(self):
            self.closed = False
            self.messages = []
            self.close_code = None

        async def prepare(self, _request):
            return self

        async def send_json(self, value):
            self.messages.append(value)

        async def close(self, *, code=None, message=b""):
            self.close_code = code
            self.close_message = message
            self.closed = True
            return True

    server = object.__new__(WebApiServer)
    server.manager = MagicMock()
    auth = AuthContext(user_id=1, token_used=True, account_id="account", capabilities={CAP_CHAT_SEND})
    server._with_websocket_capability = AsyncMock(return_value=auth)
    server._manager_alias = lambda _request: "main"
    server._request_agent_id = lambda _request: "main"
    server._request_execution_mode = lambda _request, **_kwargs: "cli"
    server._chat_user_id = lambda value: value.user_id
    monkeypatch.setattr("bot.web.server.config.TCB_CODEX_SERVER_VOICE_ENABLED", True)

    session = SimpleNamespace(bot_id=1, user_id=1, agent_id="main")
    monkeypatch.setattr(
        "bot.web.server.get_codex_server_voice_session",
        lambda *args, **kwargs: (MagicMock(), session, "conversation"),
    )
    registry = VoiceLeaseRegistry()
    registry.acquire((1, 1, "main", "conversation"), ("other", 2))
    monkeypatch.setattr("bot.web.server.voice_leases", registry)
    websocket = FakeWebSocket()
    monkeypatch.setattr("bot.web.server.web.WebSocketResponse", lambda **_kwargs: websocket)

    result = await server.chat_voice_ws(make_mocked_request(
        "GET",
        "/api/bots/main/chat/voice?protocol_version=1&conversation_id=conversation&session_epoch=0&agent_id=main",
        match_info={"alias": "main"},
    ))

    assert result is websocket
    assert websocket.messages == [{
        "type": "voice.error",
        "code": "voice_connection_occupied",
        "message": "当前会话已有语音连接",
        "state": "idle",
    }]
    assert websocket.closed


@pytest.mark.asyncio
async def test_chat_voice_reconnect_rebinds_same_runtime_with_recovery_credentials(monkeypatch):
    from aiohttp import WSMsgType
    from aiohttp.test_utils import make_mocked_request
    from bot.codex_server.voice import VoiceEvents, VoiceLeaseRegistry
    from bot.web.api_common import AuthContext
    from bot.web.auth_store import CAP_CHAT_SEND
    from bot.web.server import WebApiServer

    class ClosingWebSocket:
        def __init__(self):
            self.closed = False
            self.messages = []

        async def prepare(self, _request):
            return self

        async def send_json(self, value):
            self.messages.append(value)

        def __aiter__(self):
            async def iterator():
                yield SimpleNamespace(type=WSMsgType.CLOSE, data="")
            return iterator()

        async def close(self, **_kwargs):
            self.closed = True
            return True

    runtime = SimpleNamespace(
        request=SimpleNamespace(owner_key=(1, 1, "main"), conversation_id="conversation", experimental_api=True),
        thread_id="thread-1",
        active=False,
        alive=True,
        voice_task_active=False,
        voice_events=VoiceEvents(),
        voice_lease=None,
        start_realtime=AsyncMock(),
        stop_realtime=AsyncMock(),
    )
    runtime.subscribe_voice = lambda: runtime.voice_events.subscribe()
    runtime.unsubscribe_voice = lambda queue: runtime.voice_events.unsubscribe(queue)
    registry = VoiceLeaseRegistry(recovery_window=10)
    server = object.__new__(WebApiServer)
    server.manager = MagicMock()
    auth = AuthContext(user_id=1, token_used=True, account_id="account", capabilities={CAP_CHAT_SEND})
    server._with_websocket_capability = AsyncMock(return_value=auth)
    server._manager_alias = lambda _request: "main"
    server._request_agent_id = lambda _request: "main"
    server._request_execution_mode = lambda _request, **_kwargs: "cli"
    server._chat_user_id = lambda value: value.user_id
    monkeypatch.setattr("bot.web.server.config.TCB_CODEX_SERVER_VOICE_ENABLED", True)
    monkeypatch.setattr("bot.web.server.voice_leases", registry)
    monkeypatch.setattr(
        "bot.web.server.get_codex_server_voice_session",
        lambda *args, **kwargs: (SimpleNamespace(), SimpleNamespace(bot_id=1, user_id=1, agent_id="main"), "conversation"),
    )
    open_runtime = AsyncMock(return_value=runtime)
    monkeypatch.setattr("bot.web.server.open_codex_server_voice_runtime", open_runtime)

    first_ws = ClosingWebSocket()
    monkeypatch.setattr("bot.web.server.web.WebSocketResponse", lambda **_kwargs: first_ws)
    first = await server.chat_voice_ws(make_mocked_request(
        "GET",
        "/api/bots/main/chat/voice?protocol_version=1&conversation_id=conversation&session_epoch=0&agent_id=main",
        match_info={"alias": "main"},
    ))
    assert first is first_ws
    key = (1, 1, "main", "conversation")
    lease = registry._leases[key]
    assert lease.recoverable
    old_connection_id = lease.connection_id
    runtime.voice_task_active = True

    second_ws = ClosingWebSocket()
    monkeypatch.setattr("bot.web.server.web.WebSocketResponse", lambda **_kwargs: second_ws)
    second = await server.chat_voice_ws(make_mocked_request(
        "GET",
        f"/api/bots/main/chat/voice?protocol_version=1&conversation_id=conversation&session_epoch=0&agent_id=main"
        f"&clientGeneration={lease.client_generation}&recoveryToken={lease.recovery_token}",
        match_info={"alias": "main"},
    ))

    assert second is second_ws
    assert lease.connection_id != old_connection_id
    assert runtime.voice_lease is lease
    assert runtime.start_realtime.await_count == 0
    assert open_runtime.await_count == 2
    assert open_runtime.await_args_list[1].kwargs["voice_lease"] is lease
    lease.invalidate()


@pytest.mark.asyncio
async def test_voice_runtime_recovery_preserves_runtime_persistence(monkeypatch, tmp_path):
    import threading
    from bot.web import api_service

    marker = object()
    runtime = SimpleNamespace(thread_id="thread-1", voice_persistence=marker)
    opened = {}

    class FakeRegistry:
        async def open_or_create(self, request, **kwargs):
            opened["request"] = request
            opened["kwargs"] = kwargs
            return runtime

    session = SimpleNamespace(
        bot_id=1,
        user_id=1,
        agent_id="main",
        codex_session_id="thread-1",
        session_epoch=3,
        working_dir=str(tmp_path),
        active_conversation_id="conversation",
        is_processing=True,
        _lock=threading.RLock(),
    )
    profile = SimpleNamespace(cli_path="codex", cli_params={}, remote_workspace=None)
    lease = SimpleNamespace(recovery_claimed=True)
    registry = FakeRegistry()
    monkeypatch.setattr("bot.codex_server.runtime.get_codex_server_registry", lambda: registry)
    monkeypatch.setattr(api_service, "_build_cli_env", lambda _cli_type: {})
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex.exe")
    monkeypatch.setattr(api_service, "_effective_cli_params", lambda *_args, **_kwargs: object())

    recovered = await api_service.open_codex_server_voice_runtime(
        profile,
        session,
        "conversation",
        voice_lease=lease,
    )

    assert recovered is runtime
    assert runtime.voice_persistence is marker
    assert opened["kwargs"] == {"allow_voice_rebind": True}
