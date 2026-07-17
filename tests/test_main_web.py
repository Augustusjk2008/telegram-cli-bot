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
from bot.web.runtime_binding import WebPortInUseError

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

    fake_native_service = MagicMock()
    fake_native_service.shutdown = AsyncMock()

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch("bot.main.get_native_agent_service", return_value=fake_native_service), \
         patch.object(main_module.asyncio, "Event", return_value=fake_event), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    fake_manager.start_all.assert_not_called()
    fake_manager.start_watchdog.assert_not_called()
    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=False)
    fake_native_service.shutdown.assert_awaited_once()
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

    fake_native_service = MagicMock()
    fake_native_service.shutdown = AsyncMock()

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch("bot.main.get_native_agent_service", return_value=fake_native_service), \
         patch.object(main_module.asyncio, "Event", return_value=FakeEvent()), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    fake_web_server.start.assert_awaited_once()
    fake_web_server.stop.assert_awaited_once_with(preserve_tunnel=True)
    fake_native_service.shutdown.assert_awaited_once()
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

    assert state_path.read_text(encoding="utf-8")
    payload = __import__("json").loads(state_path.read_text(encoding="utf-8"))
    assert payload["configured_port"] == 8765
    assert payload["actual_port"] == 8767

    main_module._clear_web_runtime_state()

    assert not state_path.exists()


def test_format_cli_error_display_prefixes_exit_code_once():
    from bot.web.api_service import _format_cli_error_display

    assert _format_cli_error_display(
        "错误信息",
        returncode=1,
        completion_state="error",
    ) == "命令退出码 1\n错误信息"

    assert _format_cli_error_display(
        "命令退出码 1\n错误信息",
        returncode=1,
        completion_state="error",
    ) == "命令退出码 1\n错误信息"


def test_format_cli_error_display_leaves_non_error_response_unchanged():
    from bot.web.api_service import _format_cli_error_display

    assert _format_cli_error_display(
        " 正常输出\n",
        returncode=0,
        completion_state="completed",
    ) == " 正常输出\n"


def test_directory_listing_includes_direct_child_counts_and_file_sizes(tmp_path):
    from bot.web.files_service import list_directory_entries

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "nested").mkdir()
    (source_dir / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    payload = b"x" * 1536
    (tmp_path / "bundle.bin").write_bytes(payload)

    listing_without_counts = list_directory_entries(str(tmp_path))
    listing = list_directory_entries(str(tmp_path), include_child_counts=True)
    entries = {entry["name"]: entry for entry in listing["entries"]}

    assert all("child_count" not in entry for entry in listing_without_counts["entries"])
    assert entries["src"]["child_count"] == 2
    assert entries["empty"]["child_count"] == 0
    assert entries["bundle.bin"]["size"] == len(payload)


def test_terminal_trace_and_cli_error_display_keep_single_exit_code_prefix():
    from bot.web.api_service import _build_terminal_trace, _format_cli_error_display

    trace = _build_terminal_trace(
        live_trace=[],
        stop_requested=False,
        returncode=1,
        error_detail="错误信息",
    )
    display = _format_cli_error_display(
        trace[0]["summary"],
        returncode=1,
        completion_state="error",
    )

    assert trace == [{"kind": "error", "source": "runtime", "summary": "命令退出码 1\n错误信息"}]
    assert display == "命令退出码 1\n错误信息"

