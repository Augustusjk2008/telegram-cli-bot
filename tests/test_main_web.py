"""主进程 Web 启动相关测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot.web.runtime_binding import WebPortInUseError

@pytest.fixture(autouse=True)
def _prevent_real_browser_open(monkeypatch):
    import bot.main as main_module

    monkeypatch.setattr(main_module.webbrowser, "open", lambda *args, **kwargs: True)

@pytest.mark.asyncio
@pytest.mark.parametrize("restart_requested", [False, True])
async def test_run_all_bots_stops_web_server_with_restart_policy(monkeypatch, restart_requested):
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
