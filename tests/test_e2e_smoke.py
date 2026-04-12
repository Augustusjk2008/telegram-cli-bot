"""
端到端冒烟测试

验证真实模块可以导入并且基本数据结构正确
"""

import json
import os
from pathlib import Path

import pytest


@pytest.mark.smoke
class TestImports:
    """测试所有模块可以正确导入"""

    def test_import_config(self):
        from bot.config import (
            ALLOWED_USER_IDS,
            CLI_TYPE,
            DANGEROUS_COMMANDS,
            POLLING_TIMEOUT,
            RESERVED_ALIASES,
            SESSION_TIMEOUT,
            SUPPORTED_CLI_TYPES,
            TELEGRAM_BOT_TOKEN,
            WORKING_DIR,
        )

    def test_import_models(self):
        from bot.models import BotProfile, UserSession

    def test_import_sessions(self):
        from bot.sessions import (
            clear_bot_sessions,
            get_session,
            is_bot_processing,
            reset_session,
        )

    def test_import_utils(self):
        from bot.utils import (
            check_auth,
            is_dangerous_command,
            is_safe_filename,
            split_text_into_chunks,
            truncate_for_markdown,
        )

    def test_import_cli(self):
        from bot.cli import (
            build_cli_command,
            normalize_cli_type,
            parse_codex_json_output,
            resolve_cli_executable,
            should_mark_claude_session_initialized,
            should_reset_claude_session,
            should_reset_codex_session,
            validate_cli_type,
        )

    def test_import_context_helpers(self):
        from bot.context_helpers import (
            ensure_admin,
            get_bot_alias,
            get_bot_id,
            get_current_profile,
            get_current_session,
            get_manager,
            is_main_application,
        )

    def test_import_handlers(self):
        from bot.handlers import register_handlers
        from bot.handlers.admin import bot_help, bot_list, bot_add
        from bot.handlers.basic import start, reset
        from bot.handlers.chat import handle_text_message
        from bot.handlers.file import upload_help, handle_document, download_file
        from bot.handlers.shell import execute_shell

    def test_import_manager(self):
        from bot.manager import MultiBotManager

    def test_import_main(self):
        from bot.main import main, run_all_bots


@pytest.mark.smoke
class TestBotProfileIntegration:
    """测试 BotProfile 的端到端行为"""

    def test_profile_round_trip(self, temp_dir: Path):
        from bot.models import BotProfile
        p = BotProfile(alias="test", token="tok", cli_type="claude",
                        cli_path="/usr/bin/claude", working_dir=str(temp_dir))
        d = p.to_dict()
        json_str = json.dumps(d)
        restored = json.loads(json_str)
        assert restored["alias"] == "test"
        assert restored["token"] == "tok"
        assert restored["cli_type"] == "claude"


@pytest.mark.smoke
class TestSessionIntegration:
    """测试会话管理的端到端行为"""

    def test_session_lifecycle(self, temp_dir: Path):
        from bot.sessions import get_session, reset_session

        session = get_session(1, "main", 100, str(temp_dir))
        assert session.bot_id == 1
        assert session.user_id == 100

        session.add_to_history("user", "hello")
        assert len(session.history) == 1

        result = reset_session(1, 100)
        assert result is True


@pytest.mark.smoke
class TestCliIntegration:
    """测试 CLI 模块的端到端行为"""

    def test_validate_and_build(self):
        from bot.cli import validate_cli_type, build_cli_command
        from bot.cli_params import CliParamsConfig

        cli_type = validate_cli_type("kimi")
        assert cli_type == "kimi"

        cmd, use_stdin = build_cli_command(
            cli_type="kimi",
            resolved_cli="kimi",
            user_text="hello",
            env={},
            params_config=CliParamsConfig(),
        )
        assert isinstance(cmd, list)
        assert len(cmd) > 0


@pytest.mark.smoke
class TestManagerLoadSave:
    """测试 Manager 配置持久化"""

    def test_save_and_load(self, temp_dir: Path):
        from bot.models import BotProfile
        from bot.manager import MultiBotManager

        storage = temp_dir / "bots.json"
        main_profile = BotProfile(alias="main", token="main_tok")
        m1 = MultiBotManager(main_profile=main_profile, storage_file=str(storage))
        m1.managed_profiles["sub1"] = BotProfile(
            alias="sub1", token="tok1", cli_type="kimi",
            cli_path="kimi", working_dir=str(temp_dir),
        )
        m1._save_profiles()

        # 从文件重新加载
        m2 = MultiBotManager(main_profile=main_profile, storage_file=str(storage))
        assert "sub1" in m2.managed_profiles
        assert m2.managed_profiles["sub1"].token == "tok1"
