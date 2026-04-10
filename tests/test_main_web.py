"""主进程 Web 启动相关测试。"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_all_bots_starts_web_server_when_enabled(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.start_all = AsyncMock()
    fake_manager.start_watchdog = AsyncMock()
    fake_manager.shutdown_all = AsyncMock()

    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    fake_web_server.stop = AsyncMock()

    fake_event = MagicMock()
    fake_event.wait = AsyncMock()

    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=fake_event), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    fake_manager.start_all.assert_awaited_once()
    fake_manager.start_watchdog.assert_awaited_once()
    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=False)
    fake_manager.shutdown_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_all_bots_supports_web_only_mode(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.start_all = AsyncMock()
    fake_manager.start_watchdog = AsyncMock()
    fake_manager.shutdown_all = AsyncMock()

    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    fake_web_server.stop = AsyncMock()

    fake_event = MagicMock()
    fake_event.wait = AsyncMock()

    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", False)
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=fake_event), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    fake_manager.start_all.assert_not_called()
    fake_manager.start_watchdog.assert_not_called()
    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=False)
    fake_manager.shutdown_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_all_bots_preserves_tunnel_when_restart_requested(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.start_all = AsyncMock()
    fake_manager.start_watchdog = AsyncMock()
    fake_manager.shutdown_all = AsyncMock()

    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    fake_web_server.stop = AsyncMock()

    class FakeEvent:
        async def wait(self):
            main_module.config.RESTART_REQUESTED = True

    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", False)
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=FakeEvent()), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=True)
    fake_manager.shutdown_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_all_bots_requires_at_least_one_runtime(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.shutdown_all = AsyncMock()

    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", False)
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", False)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=MagicMock()):
        with pytest.raises(RuntimeError, match="不能同时为 false"):
            await main_module.run_all_bots()


def test_safe_print_falls_back_on_gbk_console(monkeypatch):
    import bot.main as main_module

    class GbkConsole(io.StringIO):
        encoding = "gbk"

        def write(self, text):
            text.encode(self.encoding)
            return super().write(text)

    fake_stdout = GbkConsole()
    monkeypatch.setattr(main_module.sys, "stdout", fake_stdout)

    main_module.safe_print("🤖 Web Bot 已启动")

    assert "? Web Bot 已启动" in fake_stdout.getvalue()
