"""主进程重启行为测试。"""

import types
from unittest.mock import patch

import pytest


def test_main_uses_supervisor_exit_code_when_restart_requested(monkeypatch):
    import bot.main as main_module

    monkeypatch.setenv("CLI_BRIDGE_SUPERVISOR", "1")
    monkeypatch.setattr(main_module, "safe_print", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "disable_console_quick_edit", lambda: None)
    monkeypatch.setattr(main_module, "prevent_system_sleep", lambda: None)
    monkeypatch.setattr(main_module.time, "sleep", lambda *args, **kwargs: None)

    def fake_asyncio_run(coro):
        coro.close()
        main_module.config.RESTART_REQUESTED = True
        return None

    with patch.object(main_module.asyncio, "run", side_effect=fake_asyncio_run), \
         patch.object(main_module, "reexec_current_process", side_effect=AssertionError("should not execv under supervisor")):
        with pytest.raises(SystemExit) as exc_info:
            main_module.main()

    assert exc_info.value.code == main_module.config.RESTART_EXIT_CODE


def test_main_calls_windows_error_dialog_suppression(monkeypatch):
    import bot.main as main_module
    import bot.sessions as sessions_module

    calls: list[str] = []

    monkeypatch.setattr(main_module, "safe_print", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "disable_console_quick_edit", lambda: None)
    monkeypatch.setattr(main_module, "suppress_windows_error_dialogs", lambda: calls.append("suppressed"))
    monkeypatch.setattr(main_module, "prevent_system_sleep", lambda: None)
    monkeypatch.setattr(sessions_module, "save_all_sessions", lambda: None)

    def fake_asyncio_run(coro):
        coro.close()
        return None

    with patch.object(main_module.asyncio, "run", side_effect=fake_asyncio_run):
        main_module.main()

    assert calls == ["suppressed"]


def test_suppress_windows_error_dialogs_sets_error_mode(monkeypatch):
    import bot.main as main_module

    set_modes: list[int] = []

    class FakeKernel32:
        def GetErrorMode(self):
            return 0x0010

        def SetErrorMode(self, mode):
            set_modes.append(mode)
            return mode

    monkeypatch.setattr(main_module.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(
        main_module.ctypes,
        "windll",
        types.SimpleNamespace(kernel32=FakeKernel32()),
        raising=False,
    )

    main_module.suppress_windows_error_dialogs()

    assert set_modes == [
        0x0010 | main_module.SEM_FAILCRITICALERRORS | main_module.SEM_NOGPFAULTERRORBOX | main_module.SEM_NOOPENFILEERRORBOX
    ]
