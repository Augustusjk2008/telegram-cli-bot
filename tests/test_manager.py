"""
Bot 管理器测试

测试 MultiBotManager 的配置加载/保存和验证逻辑
（不测试 Telegram API 调用，只测试纯逻辑部分）
"""

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import BOT_ALIAS_RE, RESERVED_ALIASES
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.sessions import get_or_create_session


class TestManagerLoadSave:
    """测试配置加载和保存"""

    def test_load_empty(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert len(m.managed_profiles) == 0

    def test_load_bots_format(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "sub1",
                    "token": "tok1",
                    "cli_type": "kimi",
                    "cli_path": "kimi",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                }
            ]
        }))
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert "sub1" in m.managed_profiles
        assert m.managed_profiles["sub1"].token == "tok1"

    def test_save_bots_format(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1", token="tok1", cli_type="claude",
            cli_path="claude", working_dir=str(temp_dir),
        )
        m._save_profiles()
        data = json.loads(storage.read_text(encoding="utf-8"))
        assert "bots" in data
        assert isinstance(data["bots"], list)
        assert len(data["bots"]) == 1
        assert data["bots"][0]["alias"] == "sub1"

    def test_invalid_cli_type_fallback(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "bad",
                    "token": "tok",
                    "cli_type": "nonexistent_type",
                    "cli_path": "foo",
                    "working_dir": str(temp_dir),
                }
            ]
        }))
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        # 应该回退到默认 CLI_TYPE
        assert "bad" in m.managed_profiles

    def test_reserved_alias_skipped(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {"alias": "main", "token": "tok", "cli_type": "kimi"},
            ]
        }))
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert len(m.managed_profiles) == 0

    def test_load_web_only_bot_without_token(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "web_only",
                    "token": "",
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                    "bot_mode": "cli",
                }
            ]
        }))
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert "web_only" in m.managed_profiles
        assert m.managed_profiles["web_only"].token == ""

    @pytest.mark.asyncio
    async def test_set_bot_workdir_persists_to_storage_and_sessions(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))

        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1",
            token="tok1",
            cli_type="claude",
            cli_path="claude",
            working_dir=str(old_dir),
        )
        session = get_or_create_session(123, "sub1", 456, default_working_dir=str(old_dir))

        await m.set_bot_workdir("sub1", str(new_dir))

        assert m.managed_profiles["sub1"].working_dir == str(new_dir)
        assert session.working_dir == str(new_dir)

        data = json.loads(storage.read_text(encoding="utf-8"))
        assert data["bots"][0]["alias"] == "sub1"
        assert data["bots"][0]["working_dir"] == str(new_dir)

    @pytest.mark.asyncio
    async def test_rename_bot_persists_to_storage_and_sessions(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))

        workdir = temp_dir / "repo"
        workdir.mkdir()
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1",
            token="tok1",
            cli_type="claude",
            cli_path="claude",
            working_dir=str(workdir),
        )
        app = MagicMock()
        app.bot_data = {"bot_id": 123, "bot_alias": "sub1"}
        m.applications["sub1"] = app
        m.bot_id_to_alias[123] = "sub1"
        session = get_or_create_session(123, "sub1", 456, default_working_dir=str(workdir))

        await m.rename_bot("sub1", "team1")

        assert "sub1" not in m.managed_profiles
        assert "team1" in m.managed_profiles
        assert m.managed_profiles["team1"].alias == "team1"
        assert session.bot_alias == "team1"
        assert "sub1" not in m.applications
        assert m.applications["team1"] is app
        assert m.bot_id_to_alias[123] == "team1"

        data = json.loads(storage.read_text(encoding="utf-8"))
        assert data["bots"][0]["alias"] == "team1"


class TestManagerValidation:
    """测试验证逻辑"""

    def test_validate_alias_valid(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        # 应该不抛异常
        m._validate_alias("ab")
        m._validate_alias("test-bot")
        m._validate_alias("1a")

    def test_validate_alias_too_short(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        with pytest.raises(ValueError):
            m._validate_alias("a")

    def test_validate_alias_reserved(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        with pytest.raises(ValueError, match="保留"):
            m._validate_alias("main")

    def test_validate_alias_invalid_chars(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        with pytest.raises(ValueError):
            m._validate_alias("-invalid")

    @pytest.mark.asyncio
    async def test_add_bot_allows_empty_token_for_web_only_mode(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))

        with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
             patch.object(m, "_start_profile", AsyncMock(return_value=None)) as start_profile:
            created = await m.add_bot(
                alias="web_only",
                token="",
                cli_type="codex",
                cli_path="codex",
                working_dir=str(temp_dir),
                bot_mode="cli",
            )

        assert created.token == ""
        assert m.managed_profiles["web_only"].token == ""
        assert json.loads(storage.read_text(encoding="utf-8"))["bots"][0]["token"] == ""
        start_profile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_profile_skips_telegram_when_token_missing(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        web_only = BotProfile(
            alias="web_only",
            token="",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(temp_dir),
            enabled=True,
            bot_mode="cli",
        )

        with patch("bot.manager.Application.builder", side_effect=AssertionError("should not connect telegram")):
            app = await m._start_profile(web_only, is_main=False)

        assert app is None
        assert "web_only" not in m.applications

    def test_handle_network_error_exhausted_checks_main_bot_id(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        m._main_bot_network_error_count = 9
        m.applications["main"] = MagicMock(bot_data={"bot_id": 123})

        with patch("bot.manager.is_bot_processing", autospec=True, return_value=False) as mock_processing, \
             patch("bot.config.RESTART_EVENT", None):
            m._handle_network_error_exhausted("main")

        mock_processing.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_manager_warning_sent_to_main_bot_when_idle(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        with patch("bot.manager.ALLOWED_USER_IDS", [987654321]), \
             patch("bot.manager.is_bot_processing", autospec=True, return_value=False):
            m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
            app = MagicMock()
            app.bot = MagicMock()
            app.bot.send_message = AsyncMock()
            app.bot_data = {"bot_id": 123}
            m.applications["main"] = app

            logging.getLogger("bot.manager").warning("测试告警 alias=%s", "team1")

            for _ in range(20):
                if app.bot.send_message.await_count:
                    break
                await asyncio.sleep(0.01)

            assert app.bot.send_message.await_count == 1
            kwargs = app.bot.send_message.await_args.kwargs
            assert kwargs["chat_id"] == 987654321
            assert "测试告警 alias=team1" in kwargs["text"]
            assert "WARNING" in kwargs["text"]

    @pytest.mark.asyncio
    async def test_manager_warning_waits_until_main_bot_idle(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        with patch("bot.manager.ALLOWED_USER_IDS", [987654321]), \
             patch("bot.manager.is_bot_processing", autospec=True, side_effect=[True, True, False]):
            m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
            m._main_bot_alert_retry_delay = 0.01
            app = MagicMock()
            app.bot = MagicMock()
            app.bot.send_message = AsyncMock()
            app.bot_data = {"bot_id": 123}
            m.applications["main"] = app

            logging.getLogger("bot.manager").error("测试错误 alias=%s", "team2")

            await asyncio.sleep(0.005)
            assert app.bot.send_message.await_count == 0

            for _ in range(30):
                if app.bot.send_message.await_count:
                    break
                await asyncio.sleep(0.01)

            assert app.bot.send_message.await_count == 1
            kwargs = app.bot.send_message.await_args.kwargs
            assert "测试错误 alias=team2" in kwargs["text"]
            assert "ERROR" in kwargs["text"]


class TestManagerGetProfile:
    """测试 get_profile"""

    def test_get_main_profile(self, temp_dir: Path):
        main_profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        assert m.get_profile("main") is main_profile

    def test_get_sub_profile(self, temp_dir: Path):
        main_profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        sub = BotProfile(alias="sub1", token="tok1")
        m.managed_profiles["sub1"] = sub
        assert m.get_profile("sub1") is sub

    def test_get_nonexistent_raises(self, temp_dir: Path):
        main_profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        with pytest.raises(KeyError):
            m.get_profile("nonexistent")


class TestManagerGetStatusLines:
    """测试 get_status_lines"""

    def test_main_only(self, temp_dir: Path):
        main_profile = BotProfile(alias="main", token="main_tok", cli_type="kimi", cli_path="kimi")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        # 没有启动任何 application，main 状态为 stopped
        lines = m.get_status_lines()
        # 新的格式返回包含 HTML 的字符串列表
        result = "\n".join(lines)
        assert "main" in result
        assert "🔴" in result  # stopped 状态的表情符号
        assert "主 Bot" in result

    def test_with_sub_bots(self, temp_dir: Path):
        main_profile = BotProfile(alias="main", token="main_tok", cli_type="kimi", cli_path="kimi")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1", token="tok1", cli_type="claude", cli_path="claude"
        )
        lines = m.get_status_lines()
        result = "\n".join(lines)
        assert "sub1" in result
        assert "claude" in result
        assert "托管 Bot" in result
