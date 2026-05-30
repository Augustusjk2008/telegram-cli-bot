"""主进程 Web 启动相关测试。"""

import asyncio
import io
import os
import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientSession
import pytest

@pytest.fixture(autouse=True)
def _prevent_real_browser_open(monkeypatch):
    import bot.main as main_module

    monkeypatch.setattr(main_module.webbrowser, "open", lambda *args, **kwargs: True)

@pytest.mark.asyncio
async def test_run_all_bots_starts_web_server_when_enabled(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.start_all = AsyncMock()
    fake_manager.start_watchdog = AsyncMock()
    fake_manager.start_background_services = AsyncMock()
    fake_manager.shutdown_all = AsyncMock()

    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    fake_web_server.stop = AsyncMock()

    fake_event = MagicMock()
    fake_event.wait = AsyncMock()

    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    monkeypatch.setattr(main_module, "_allow_runtime_port_fallback", lambda: True)

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
    fake_manager.start_background_services = AsyncMock()
    fake_manager.shutdown_all = AsyncMock()

    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    fake_web_server.stop = AsyncMock()

    class FakeEvent:
        async def wait(self):
            main_module.config.RESTART_REQUESTED = True

    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    monkeypatch.setattr(main_module, "_allow_runtime_port_fallback", lambda: True)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=FakeEvent()), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=True)
    fake_manager.shutdown_all.assert_awaited_once()

@pytest.mark.asyncio
async def test_run_all_bots_requires_web_runtime(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.shutdown_all = AsyncMock()

    monkeypatch.setattr(main_module.config, "WEB_ENABLED", False)

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=MagicMock()):
        with pytest.raises(RuntimeError, match="WEB_ENABLED 不能为 false"):
            await main_module.run_all_bots()

