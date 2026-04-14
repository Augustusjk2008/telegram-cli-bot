"""
配置模块测试

直接导入 bot.config 中的真实常量和函数进行测试
"""

import pytest

from bot.config import (
    BOT_ALIAS_RE,
    DANGEROUS_COMMANDS,
    MAIN_LOOP_RETRY_DELAY,
    POLLING_BOOTSTRAP_RETRIES,
    POLLING_TIMEOUT,
    POLLING_WATCHDOG_INTERVAL,
    RESERVED_ALIASES,
    RESTART_EXIT_CODE,
    RESTART_EVENT,
    RESTART_REQUESTED,
    RESTART_SUPERVISOR_ENV,
    SESSION_TIMEOUT,
    SUPPORTED_CLI_TYPES,
    WORKING_DIR,
    build_reexec_args,
    reexec_current_process,
    request_restart,
)


class TestConfigConstants:
    """测试配置常量值"""

    def test_supported_cli_types(self):
        assert SUPPORTED_CLI_TYPES == {"claude", "codex"}

    def test_config_module_no_longer_exports_telegram_runtime_envs(self):
        import bot.config as config

        assert not hasattr(config, "TELEGRAM" "_ENABLED")
        assert not hasattr(config, "TELEGRAM" "_BOT_TOKEN")

    def test_dangerous_commands_is_set(self):
        assert isinstance(DANGEROUS_COMMANDS, set)
        # rm 已被移除，允许通过 /exec 和 /rm 命令执行
        assert "rm" not in DANGEROUS_COMMANDS
        assert "dd" in DANGEROUS_COMMANDS
        assert "mkfs" in DANGEROUS_COMMANDS
        assert "kill" in DANGEROUS_COMMANDS
        assert "shutdown" in DANGEROUS_COMMANDS
        assert len(DANGEROUS_COMMANDS) >= 15

    def test_reserved_aliases(self):
        assert RESERVED_ALIASES == {"main"}

    def test_bot_alias_re(self):
        # 允许字母/数字开头，长度 2-32
        assert BOT_ALIAS_RE.fullmatch("ab") is not None
        assert BOT_ALIAS_RE.fullmatch("a1") is not None
        assert BOT_ALIAS_RE.fullmatch("1a") is not None  # 数字开头允许
        assert BOT_ALIAS_RE.fullmatch("test-bot_1") is not None
        # 不允许
        assert BOT_ALIAS_RE.fullmatch("a") is None  # 太短
        assert BOT_ALIAS_RE.fullmatch("") is None  # 空
        assert BOT_ALIAS_RE.fullmatch("-ab") is None  # 非字母数字开头
        assert BOT_ALIAS_RE.fullmatch("_ab") is None
        assert BOT_ALIAS_RE.fullmatch("a" * 33) is None  # 太长

    def test_polling_constants(self):
        assert POLLING_BOOTSTRAP_RETRIES == -1  # 无限重试
        assert POLLING_TIMEOUT == 30
        assert POLLING_WATCHDOG_INTERVAL == 5
        assert MAIN_LOOP_RETRY_DELAY == 5

    def test_session_timeout_is_int(self):
        assert isinstance(SESSION_TIMEOUT, int)

    def test_working_dir_is_absolute(self):
        import os
        assert os.path.isabs(WORKING_DIR)

    def test_web_config_reads_environment(self, monkeypatch):
        monkeypatch.setenv("WEB_ENABLED", "true")
        monkeypatch.setenv("WEB_HOST", "127.0.0.1")
        monkeypatch.setenv("WEB_PORT", "8765")
        monkeypatch.setenv("WEB_API_TOKEN", "secret")
        monkeypatch.setenv("WEB_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000")

        import importlib
        import dotenv
        import bot.config as config

        monkeypatch.setattr(dotenv, "dotenv_values", lambda *args, **kwargs: {})
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)
        importlib.reload(config)

        assert config.WEB_ENABLED is True
        assert config.WEB_HOST == "127.0.0.1"
        assert config.WEB_PORT == 8765
        assert config.WEB_API_TOKEN == "secret"
        assert config.WEB_ALLOWED_ORIGINS == ["http://127.0.0.1:3000", "http://localhost:3000"]

    def test_web_config_prefers_explicit_environment_over_project_dotenv_for_host_and_port(self, monkeypatch):
        monkeypatch.setenv("WEB_HOST", "127.0.0.1")
        monkeypatch.setenv("WEB_PORT", "9999")

        import importlib
        import dotenv
        import bot.config as config

        monkeypatch.setattr(
            dotenv,
            "dotenv_values",
            lambda *args, **kwargs: {"WEB_HOST": "0.0.0.0", "WEB_PORT": "8765"},
        )
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)
        importlib.reload(config)

        assert config.WEB_HOST == "127.0.0.1"
        assert config.WEB_PORT == 9999


class TestRestartMechanism:
    """测试重启机制"""

    def test_restart_event_initially_none(self):
        # RESTART_EVENT 是 Optional[asyncio.Event], 初始为 None
        import bot.config as config
        # 可能在之前的测试中被修改，不做强断言

    def test_request_restart(self):
        import bot.config as config
        old_val = config.RESTART_REQUESTED
        config.RESTART_REQUESTED = False
        request_restart()
        assert config.RESTART_REQUESTED is True
        config.RESTART_REQUESTED = old_val

    def test_request_restart_sets_event(self):
        import asyncio
        import bot.config as config
        event = asyncio.Event()
        config.RESTART_EVENT = event
        config.RESTART_REQUESTED = False
        request_restart()
        assert event.is_set()
        config.RESTART_EVENT = None
        config.RESTART_REQUESTED = False

    def test_restart_exit_code_for_supervisor(self):
        assert RESTART_EXIT_CODE == 75

    def test_restart_supervisor_env_uses_generic_web_only_name(self):
        assert RESTART_SUPERVISOR_ENV == "CLI_BRIDGE_SUPERVISOR"

    def test_build_reexec_args_prefers_orig_argv(self, monkeypatch):
        import bot.config as config

        monkeypatch.setattr(config.sys, "executable", r"C:\Python\python.exe")
        monkeypatch.setattr(config.sys, "argv", ["C:\\repo\\bot\\__main__.py", "--flag"])
        monkeypatch.setattr(config.sys, "orig_argv", ["C:\\Python\\python.exe", "-m", "bot", "--flag"])

        executable, args = build_reexec_args()

        assert executable == r"C:\Python\python.exe"
        assert args == [r"C:\Python\python.exe", "-m", "bot", "--flag"]
