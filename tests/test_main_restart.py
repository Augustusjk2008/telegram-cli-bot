"""主进程重启行为测试。"""

from unittest.mock import patch

import pytest


def test_main_uses_supervisor_exit_code_when_restart_requested(monkeypatch):
    import bot.main as main_module

    monkeypatch.setenv("TELEGRAM_CLI_BRIDGE_SUPERVISOR", "1")
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
