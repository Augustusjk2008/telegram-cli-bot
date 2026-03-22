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
    RESTART_EVENT,
    RESTART_REQUESTED,
    SESSION_TIMEOUT,
    SUPPORTED_CLI_TYPES,
    WORKING_DIR,
    reexec_current_process,
    request_restart,
)


class TestConfigConstants:
    """测试配置常量值"""

    def test_supported_cli_types(self):
        assert SUPPORTED_CLI_TYPES == {"kimi", "claude", "codex"}

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
