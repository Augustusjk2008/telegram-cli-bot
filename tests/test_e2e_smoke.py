"""
端到端冒烟测试

验证真实模块可以导入并且基本数据结构正确
"""

import json
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
            SUPPORTED_CLI_TYPES,
            WEB_ENABLED,
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
        assert "token" not in restored
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

        cli_type = validate_cli_type("codex")
        assert cli_type == "codex"

        cmd, use_stdin = build_cli_command(
            cli_type="codex",
            resolved_cli="codex",
            user_text="hello",
            env={},
            params_config=CliParamsConfig(),
            json_output=True,
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
            alias="sub1", token="tok1", cli_type="claude",
            cli_path="claude", working_dir=str(temp_dir),
        )
        m1._save_profiles()

        # 从文件重新加载
        m2 = MultiBotManager(main_profile=main_profile, storage_file=str(storage))
        assert "sub1" in m2.managed_profiles
        assert m2.managed_profiles["sub1"].cli_type == "claude"
