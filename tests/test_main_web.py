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
async def test_run_all_bots_prints_lan_url_for_all_interface_web_host(monkeypatch):
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

    printed: list[str] = []

    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", False)
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    monkeypatch.setattr(main_module.config, "WEB_HOST", "0.0.0.0")
    monkeypatch.setattr(main_module.config, "WEB_PORT", 8765)
    monkeypatch.setattr(main_module, "_get_primary_lan_ipv4", lambda: "192.168.71.114")
    monkeypatch.setattr(main_module, "safe_print", lambda text="": printed.append(text))

    with patch.object(main_module, "MultiBotManager", return_value=fake_manager), \
         patch.object(main_module.asyncio, "Event", return_value=fake_event), \
         patch.object(main_module, "WebApiServer", return_value=fake_web_server):
        await main_module.run_all_bots()

    assert "   Web 本机地址: http://127.0.0.1:8765" in printed
    assert "   Web 局域网地址: http://192.168.71.114:8765" in printed


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


def test_main_allows_empty_telegram_token_in_web_only_mode(monkeypatch):
    import bot.main as main_module

    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", False)
    monkeypatch.setattr(main_module.config, "WEB_ENABLED", True)
    monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(main_module, "safe_print", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "disable_console_quick_edit", lambda: None)
    monkeypatch.setattr(main_module, "prevent_system_sleep", lambda: None)
    monkeypatch.setattr(main_module.time, "sleep", lambda *args, **kwargs: None)

    def fake_asyncio_run(coro):
        coro.close()
        return None

    monkeypatch.setattr(main_module.asyncio, "run", fake_asyncio_run)

    main_module.main()


def test_main_rejects_empty_telegram_token_when_telegram_enabled(monkeypatch):
    import bot.main as main_module

    printed = []
    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(main_module, "safe_print", lambda text="": printed.append(text))
    monkeypatch.setattr(main_module, "disable_console_quick_edit", lambda: None)
    monkeypatch.setattr(main_module, "prevent_system_sleep", lambda: None)
    monkeypatch.setattr(main_module.time, "sleep", lambda *args, **kwargs: None)

    def fake_asyncio_run(coro):
        coro.close()
        return None

    monkeypatch.setattr(main_module.asyncio, "run", fake_asyncio_run)

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert any("TELEGRAM_BOT_TOKEN" in line for line in printed)


def test_main_rejects_placeholder_telegram_token_when_telegram_enabled(monkeypatch):
    import bot.main as main_module

    printed = []
    monkeypatch.setattr(main_module, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "your_bot_token_here")
    monkeypatch.setattr(main_module, "safe_print", lambda text="": printed.append(text))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert any("TELEGRAM_BOT_TOKEN" in line for line in printed)


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
            "TELEGRAM_ENABLED": "false",
            "WEB_ENABLED": "true",
            "WEB_HOST": "127.0.0.1",
            "WEB_PORT": str(port),
            "WEB_API_TOKEN": token,
            "WEB_TUNNEL_MODE": "disabled",
            "WEB_TUNNEL_AUTOSTART": "false",
            "TELEGRAM_CLI_BRIDGE_SUPERVISOR": "1",
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

        async with ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
            ws = await session.ws_connect(f"ws://127.0.0.1:{port}/terminal/ws?token={token}")
            await ws.send_json({"shell": "powershell", "cwd": str(repo_root)})
            first_message = await ws.receive_json(timeout=5)
            assert first_message == {"pty_mode": True}
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
