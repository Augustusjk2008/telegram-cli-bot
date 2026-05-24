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
async def test_run_all_bots_opens_localhost_with_actual_port(monkeypatch):
    import bot.main as main_module

    fake_manager = MagicMock()
    fake_manager.start_background_services = AsyncMock()
    fake_manager.shutdown_all = AsyncMock()

    fake_web_server = MagicMock()
    fake_web_server.start = AsyncMock()
    fake_web_server.stop = AsyncMock()

    fake_event = MagicMock()
    fake_event.wait = AsyncMock()

    opened_urls: list[tuple[str, int]] = []
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    monkeypatch.setattr(main_module.config, "WEB_HOST", "0.0.0.0")
    monkeypatch.setattr(main_module.config, "WEB_PORT", 8765)
    monkeypatch.setenv("BROWSER", "test-browser")
    monkeypatch.setattr(
        main_module,
        "resolve_runtime_web_bind",
        lambda host, port: main_module.RuntimeWebBind(host=host, configured_port=port, actual_port=8767),
    )
    monkeypatch.setattr(
        main_module.webbrowser,
        "open",
        lambda url, new=0: opened_urls.append((url, new)) or True,
    )

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=fake_event), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    assert opened_urls == [("http://127.0.0.1:8767", 2)]


@pytest.mark.asyncio
async def test_open_local_browser_skips_headless_linux(monkeypatch):
    import bot.main as main_module

    open_browser = MagicMock(side_effect=AssertionError("不应尝试打开浏览器"))
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET", "BROWSER", "WEB_AUTO_OPEN_BROWSER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main_module, "_open_local_browser_sync", open_browser)

    await main_module._open_local_browser(
        main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8765)
    )

    open_browser.assert_not_called()


@pytest.mark.asyncio
async def test_open_local_browser_skips_posix_root(monkeypatch):
    import bot.main as main_module

    open_browser = MagicMock(side_effect=AssertionError("不应尝试打开浏览器"))
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    monkeypatch.setattr(main_module.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("BROWSER", "test-browser")
    monkeypatch.setattr(main_module, "_open_local_browser_sync", open_browser)

    await main_module._open_local_browser(
        main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8765)
    )

    open_browser.assert_not_called()


@pytest.mark.asyncio
async def test_open_local_browser_skips_linux_without_browser_command(monkeypatch):
    import bot.main as main_module

    open_browser = MagicMock(side_effect=AssertionError("不应尝试打开浏览器"))
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    monkeypatch.setattr(main_module.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setattr(main_module, "_has_posix_browser_command", lambda: False)
    monkeypatch.setattr(main_module, "_open_local_browser_sync", open_browser)

    await main_module._open_local_browser(
        main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8765)
    )

    open_browser.assert_not_called()


@pytest.mark.asyncio
async def test_open_local_browser_skips_linux_display_without_desktop_session(monkeypatch):
    import bot.main as main_module

    open_browser = MagicMock(side_effect=AssertionError("不应尝试打开浏览器"))
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    monkeypatch.setattr(main_module.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    for name in ("WAYLAND_DISPLAY", "MIR_SOCKET", "BROWSER", "WEB_AUTO_OPEN_BROWSER", "XAUTHORITY", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main_module, "_has_posix_browser_command", lambda: True)
    monkeypatch.setattr(main_module, "_open_local_browser_sync", open_browser)

    await main_module._open_local_browser(
        main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8765)
    )

    open_browser.assert_not_called()


@pytest.mark.asyncio
async def test_open_local_browser_skips_posix_browser_wrapper_env(monkeypatch):
    import bot.main as main_module

    open_browser = MagicMock(side_effect=AssertionError("不应尝试打开浏览器"))
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    monkeypatch.setattr(main_module.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setenv("BROWSER", f"xdg-open{os.pathsep}x-www-browser")
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET", "WEB_AUTO_OPEN_BROWSER", "XAUTHORITY", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main_module, "_open_local_browser_sync", open_browser)

    await main_module._open_local_browser(
        main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8765)
    )

    open_browser.assert_not_called()


def test_try_open_posix_graphical_browser_hides_failed_browser_output(monkeypatch):
    import bot.main as main_module

    class FailedProcess:
        def wait(self, timeout):
            return 1

    popen_calls = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FailedProcess()

    monkeypatch.setattr(main_module, "_POSIX_GRAPHICAL_BROWSER_COMMANDS", ("firefox",))
    monkeypatch.setattr(main_module.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(main_module.subprocess, "Popen", fake_popen)

    assert not main_module._try_open_posix_graphical_browser("http://127.0.0.1:8765")
    assert popen_calls[0][1]["stdout"] is main_module.subprocess.DEVNULL
    assert popen_calls[0][1]["stderr"] is main_module.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_open_local_browser_can_be_disabled_with_env(monkeypatch):
    import bot.main as main_module

    open_browser = MagicMock(side_effect=AssertionError("不应尝试打开浏览器"))
    monkeypatch.setattr(main_module.sys, "platform", "win32")
    monkeypatch.setenv("WEB_AUTO_OPEN_BROWSER", "false")
    monkeypatch.setattr(main_module, "_open_local_browser_sync", open_browser)

    await main_module._open_local_browser(
        main_module.RuntimeWebBind(host="127.0.0.1", configured_port=8765, actual_port=8765)
    )

    open_browser.assert_not_called()

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

def test_main_prints_web_only_runtime_status(monkeypatch):
    import bot.main as main_module

    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    printed: list[str] = []
    monkeypatch.setattr(main_module, "safe_print", lambda text="": printed.append(text))
    monkeypatch.setattr(main_module, "disable_console_quick_edit", lambda: None)
    monkeypatch.setattr(main_module, "prevent_system_sleep", lambda: None)
    monkeypatch.setattr(main_module.time, "sleep", lambda *args, **kwargs: None)

    def fake_asyncio_run(coro):
        coro.close()
        return None

    monkeypatch.setattr(main_module.asyncio, "run", fake_asyncio_run)

    main_module.main()

    assert any(line == "   Web API: 开启" for line in printed)
    assert all(line != "   Telegram: 开启" and line != "   Telegram: 关闭" for line in printed)

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

def test_windows_proactor_connection_reset_context_is_benign(monkeypatch):
    import bot.main as main_module

    monkeypatch.setattr(main_module.sys, "platform", "win32")

    assert main_module._is_benign_windows_proactor_reset({
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
        "exception": ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"),
    })
    assert not main_module._is_benign_windows_proactor_reset({
        "message": "Exception in callback other_callback()",
        "exception": ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"),
    })
    assert not main_module._is_benign_windows_proactor_reset({
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
        "exception": RuntimeError("boom"),
    })


def test_windows_proactor_exception_filter_suppresses_only_transport_reset(monkeypatch):
    import bot.main as main_module

    class FakeLoop:
        def __init__(self):
            self.installed_handler = None
            self.previous_contexts = []
            self.default_contexts = []

        def get_exception_handler(self):
            return lambda loop, context: self.previous_contexts.append(context)

        def set_exception_handler(self, handler):
            self.installed_handler = handler

        def default_exception_handler(self, context):
            self.default_contexts.append(context)

    loop = FakeLoop()
    monkeypatch.setattr(main_module.sys, "platform", "win32")

    main_module._install_asyncio_exception_filter(loop)

    benign_context = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
        "exception": ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"),
    }
    other_context = {
        "message": "Exception in callback other_callback()",
        "exception": ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"),
    }

    assert loop.installed_handler is not None
    loop.installed_handler(loop, benign_context)
    loop.installed_handler(loop, other_context)

    assert loop.previous_contexts == [other_context]
    assert loop.default_contexts == []

@pytest.mark.skipif(sys.platform != "win32", reason="该回归仅在 Windows 的 Web 终端重启路径上复现")
@pytest.mark.asyncio
async def test_supervised_web_restart_exits_with_terminal_connection():
    repo_root = Path(__file__).resolve().parents[1]
    token = "restart-secret"

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    env = os.environ.copy()
    env.update(
        {
            "WEB_ENABLED": "true",
            "WEB_HOST": "127.0.0.1",
            "WEB_PORT": str(port),
            "WEB_API_TOKEN": token,
            "WEB_TUNNEL_MODE": "disabled",
            "WEB_TUNNEL_AUTOSTART": "false",
            "CLI_BRIDGE_SUPERVISOR": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "bot",
        cwd=str(repo_root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    output_lines: list[str] = []

    async def drain_output() -> None:
        if process.stdout is None:
            return
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            output_lines.append(line.decode("utf-8", errors="replace"))

    drain_task = asyncio.create_task(drain_output())

    async def wait_for_server() -> None:
        base_url = f"http://127.0.0.1:{port}"
        async with ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
            for _ in range(60):
                if process.returncode is not None:
                    break
                try:
                    async with session.get(f"{base_url}/api/auth/me") as resp:
                        if resp.status == 200:
                            return
                except Exception:
                    pass
                await asyncio.sleep(0.25)
        pytest.fail(
            "Web 服务器未按时启动。\n"
            + "".join(output_lines[-40:])
        )

    try:
        await wait_for_server()
        base_url = f"http://127.0.0.1:{port}"
        owner_id = "restart-test-owner"

        async with ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
            async with session.post(
                f"{base_url}/api/terminal/session/rebuild",
                json={"owner_id": owner_id, "cwd": str(repo_root), "shell": "powershell"},
            ) as resp:
                assert resp.status == 200
            ws = await session.ws_connect(f"ws://127.0.0.1:{port}/terminal/ws?token={token}")
            await ws.send_json({"owner_id": owner_id})
            first_message = await ws.receive_json(timeout=5)
            assert first_message["pty_mode"] is True
            assert first_message["connection_text"] == "运行中"
            await asyncio.sleep(1.0)

            async with session.post(f"{base_url}/api/admin/restart") as resp:
                assert resp.status == 200

            await asyncio.sleep(2.0)
            await ws.close()

        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except TimeoutError:
            pytest.fail(
                "带活动终端连接时，网页重启未能让受监督子进程及时退出。\n"
                + "".join(output_lines[-80:])
            )

        assert process.returncode == 75
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await asyncio.wait_for(drain_task, timeout=5)
