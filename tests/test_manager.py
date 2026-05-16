"""
Bot 管理器测试

测试 MultiBotManager 的配置加载/保存和验证逻辑
（不测试 Telegram API 调用，只测试纯逻辑部分）
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import app_settings
from bot.config import BOT_ALIAS_RE, RESERVED_ALIASES
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.sessions import get_or_create_session


def test_kimi_cli_type_is_no_longer_removed_legacy_type():
    from bot.manager import REMOVED_LEGACY_CLI_TYPES

    assert "kimi" not in REMOVED_LEGACY_CLI_TYPES


def test_profile_store_save_matches_manager_private_wrapper(temp_dir: Path):
    from bot.profile_store import save_managed_profiles

    storage = temp_dir / "bots.json"
    profile = BotProfile(alias="main", token="main_tok")
    manager = MultiBotManager(main_profile=profile, storage_file=str(storage))
    manager.managed_profiles["sub1"] = BotProfile(alias="sub1", cli_type="claude", cli_path="claude")

    manager._save_profiles()
    manager_payload = json.loads(storage.read_text(encoding="utf-8"))

    save_managed_profiles(storage, manager.managed_profiles)
    helper_payload = json.loads(storage.read_text(encoding="utf-8"))

    assert helper_payload == manager_payload


class TestManagerLoadSave:
    """测试配置加载和保存"""

    def test_bot_profile_to_dict_omits_token(self):
        profile = BotProfile(alias="team2", cli_type="claude", cli_path="claude")

        payload = profile.to_dict()

        assert "token" not in payload

    def test_bot_profile_round_trips_avatar_name(self):
        profile = BotProfile(
            alias="team2",
            token="tok2",
            cli_type="claude",
            cli_path="claude",
            avatar_name="claude-blue.png",
        )

        restored = BotProfile.from_dict(profile.to_dict())

        assert restored.avatar_name == "claude-blue.png"

    def test_bot_profile_round_trips_agents(self):
        payload = {
            "alias": "repo",
            "agents": [
                {
                    "id": "reviewer",
                    "name": "代码审查",
                    "system_prompt": "先审查",
                    "enabled": True,
                    "created_at": "2026-05-04T10:00:00",
                    "updated_at": "2026-05-04T10:00:00",
                }
            ],
        }

        profile = BotProfile.from_dict(payload)

        assert profile.get_agent("main").name == "主 agent"
        assert profile.get_agent("reviewer").system_prompt == "先审查"
        assert profile.to_dict()["agents"][0]["id"] == "reviewer"

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
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                }
            ]
        }))
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))
        assert "sub1" in m.managed_profiles
        assert m.managed_profiles["sub1"].token == "tok1"

    def test_load_profiles_accepts_kimi_cli_type(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "alias": "kimi1",
                            "token": "",
                            "cli_type": "kimi",
                            "cli_path": "kimi",
                            "working_dir": str(temp_dir),
                            "enabled": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        assert manager.managed_profiles["kimi1"].cli_type == "kimi"

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
                {"alias": "main", "token": "tok", "cli_type": "codex"},
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
    async def test_set_bot_workdir_persists_to_storage_and_resets_browser_dir(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))

        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        nested = old_dir / "nested"
        nested.mkdir()
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1",
            token="tok1",
            cli_type="claude",
            cli_path="claude",
            working_dir=str(old_dir),
        )
        session = get_or_create_session(123, "sub1", 456, default_working_dir=str(old_dir))
        session.browse_dir = str(nested)

        await m.set_bot_workdir("sub1", str(new_dir), update_sessions=True)

        assert m.managed_profiles["sub1"].working_dir == str(new_dir)
        assert session.working_dir == str(new_dir)
        assert session.browse_dir == str(new_dir)

        data = json.loads(storage.read_text(encoding="utf-8"))
        assert data["bots"][0]["alias"] == "sub1"
        assert data["bots"][0]["working_dir"] == str(new_dir)

    @pytest.mark.asyncio
    async def test_agent_crud_is_scoped_to_existing_cli_bot(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", working_dir=str(temp_dir)), str(storage))

        created = await manager.create_bot_agent(
            "main",
            {"id": "reviewer", "name": "代码审查", "system_prompt": "先审查"},
        )
        updated = await manager.update_bot_agent("main", "reviewer", {"enabled": False})

        assert created["id"] == "reviewer"
        assert updated["enabled"] is False
        assert manager.get_profile("main").get_agent("reviewer").system_prompt == "先审查"

        await manager.delete_bot_agent("main", "reviewer")

        with pytest.raises(KeyError):
            manager.get_profile("main").get_agent("reviewer")

    @pytest.mark.asyncio
    async def test_set_bot_workdir_does_not_update_live_sessions_by_default(self, temp_dir: Path):
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
        session.browse_dir = str(old_dir)

        await m.set_bot_workdir("sub1", str(new_dir))

        assert m.managed_profiles["sub1"].working_dir == str(new_dir)
        assert session.working_dir == str(old_dir)
        assert session.browse_dir == str(old_dir)

    @pytest.mark.asyncio
    async def test_set_bot_workdir_rejects_assistant_mode(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        profile = BotProfile(alias="main", token="main_tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(storage))

        old_dir = temp_dir / "assistant-old"
        new_dir = temp_dir / "assistant-new"
        old_dir.mkdir()
        new_dir.mkdir()
        m.managed_profiles["assistant1"] = BotProfile(
            alias="assistant1",
            token="tok1",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(old_dir),
            bot_mode="assistant",
        )
        session = get_or_create_session(123, "assistant1", 456, default_working_dir=str(old_dir))

        with pytest.raises(ValueError, match="assistant.*工作目录"):
            await m.set_bot_workdir("assistant1", str(new_dir))

        assert m.managed_profiles["assistant1"].working_dir == str(old_dir)
        assert session.working_dir == str(old_dir)

    @pytest.mark.asyncio
    async def test_add_bot_rejects_second_assistant(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))
        assistant_dir = temp_dir / "assistant-root"
        assistant_dir.mkdir()

        with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
             patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
            await manager.add_bot("assistant1", "", "codex", "codex", str(assistant_dir), "assistant")
            with pytest.raises(ValueError, match="只允许一个 assistant"):
                await manager.add_bot("assistant2", "", "codex", "codex", str(assistant_dir), "assistant")

    @pytest.mark.asyncio
    async def test_add_bot_syncs_assistant_prompt_files_from_dedicated_template(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        template_path = temp_dir / "managed_prompt_template.md"
        template_path.write_text("assistant template", encoding="utf-8")

        assistant_dir = temp_dir / "assistant-root"
        assistant_dir.mkdir()

        with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
             patch.object(manager, "_start_profile", AsyncMock(return_value=None)), \
             patch("bot.assistant.docs.resolve_assistant_managed_template_path", return_value=template_path):
            await manager.add_bot("assistant1", "", "codex", "codex", str(assistant_dir), "assistant")

        agents_text = (assistant_dir / "AGENTS.md").read_text(encoding="utf-8")
        claude_text = (assistant_dir / "CLAUDE.md").read_text(encoding="utf-8")
        assert "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->" in agents_text
        assert agents_text == claude_text
        assert agents_text.startswith("assistant template\n\n")

    @pytest.mark.asyncio
    async def test_add_bot_requires_explicit_workdir_for_assistant(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        with patch("bot.manager.resolve_cli_executable", return_value="codex"):
            with pytest.raises(ValueError, match="assistant.*必须显式提供工作目录"):
                await manager.add_bot("assistant1", "", "codex", "codex", None, "assistant")

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

    def test_load_assistant_profile_syncs_prompt_files_from_dedicated_template(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        assistant_dir = temp_dir / "assistant-root"
        assistant_dir.mkdir()
        storage.write_text(
            json.dumps(
                {
                    "bots": [
                        {
                            "alias": "assistant1",
                            "token": "",
                            "cli_type": "codex",
                            "cli_path": "codex",
                            "working_dir": str(assistant_dir),
                            "enabled": True,
                            "bot_mode": "assistant",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        template_path = temp_dir / "managed_prompt_template.md"
        template_path.write_text("assistant template", encoding="utf-8")

        with patch("bot.assistant.docs.resolve_assistant_managed_template_path", return_value=template_path):
            manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        assert "assistant1" in manager.managed_profiles
        assert (assistant_dir / "AGENTS.md").read_text(encoding="utf-8") == (
            assistant_dir / "CLAUDE.md"
        ).read_text(encoding="utf-8")

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
    async def test_add_bot_persists_avatar_name_to_storage(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        with patch("bot.manager.resolve_cli_executable", return_value="claude"), \
             patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
            created = await manager.add_bot(
                alias="team2",
                token="",
                cli_type="claude",
                cli_path="claude",
                working_dir=str(temp_dir),
                bot_mode="cli",
                avatar_name="claude-blue.png",
            )

        assert created.avatar_name == "claude-blue.png"
        assert json.loads(storage.read_text(encoding="utf-8"))["bots"][0]["avatar_name"] == "claude-blue.png"

    @pytest.mark.asyncio
    async def test_add_bot_defaults_cli_path_from_env_then_existing_same_cli(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex"), str(storage))
        manager.managed_profiles["review"] = BotProfile(
            alias="review",
            token="",
            cli_type="claude",
            cli_path="C:/tools/claude.cmd",
            working_dir=str(temp_dir),
            bot_mode="cli",
        )
        monkeypatch.setenv("CLI_TYPE", "codex")
        monkeypatch.setenv("CLI_PATH", "C:/tools/codex.exe")

        with patch("bot.manager.resolve_cli_executable", return_value="cli"), \
             patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
            codex_bot = await manager.add_bot("team2", cli_type="codex", cli_path="", working_dir=str(temp_dir), bot_mode="cli")
            claude_bot = await manager.add_bot("team3", cli_type="claude", cli_path="", working_dir=str(temp_dir), bot_mode="cli")
            kimi_bot = await manager.add_bot("team4", cli_type="kimi", cli_path="", working_dir=str(temp_dir), bot_mode="cli")

        assert codex_bot.cli_path == "C:/tools/codex.exe"
        assert claude_bot.cli_path == "C:/tools/claude.cmd"
        assert kimi_bot.cli_path == "kimi"

    @pytest.mark.asyncio
    async def test_add_bot_prefers_existing_non_default_cli_path_when_env_missing(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex"), str(storage))
        manager.managed_profiles["worker"] = BotProfile(
            alias="worker",
            token="",
            cli_type="codex",
            cli_path="C:/tools/codex.exe",
            working_dir=str(temp_dir),
            bot_mode="cli",
        )
        monkeypatch.delenv("CLI_PATH", raising=False)
        monkeypatch.setattr("bot.manager._DOTENV_VALUES", {})

        with patch("bot.manager.resolve_cli_executable", return_value="cli"), \
             patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
            created = await manager.add_bot("team2", cli_type="codex", cli_path="", working_dir=str(temp_dir), bot_mode="cli")

        assert created.cli_path == "C:/tools/codex.exe"

    @pytest.mark.asyncio
    async def test_set_bot_avatar_updates_profile_and_storage(self, temp_dir: Path):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))
        manager.managed_profiles["team2"] = BotProfile(
            alias="team2",
            token="",
            cli_type="claude",
            cli_path="claude",
            working_dir=str(temp_dir),
            avatar_name="avatar_01.png",
        )

        await manager.set_bot_avatar("team2", "mint-teal.png")

        assert manager.managed_profiles["team2"].avatar_name == "mint-teal.png"
        assert json.loads(storage.read_text(encoding="utf-8"))["bots"][0]["avatar_name"] == "mint-teal.png"

    @pytest.mark.asyncio
    async def test_main_bot_avatar_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))
        await manager.set_bot_avatar("main", "codex-slate.png")

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        assert restored.main_profile.avatar_name == "codex-slate.png"

    @pytest.mark.asyncio
    async def test_main_bot_cli_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex"), str(storage))
        with patch("bot.manager.resolve_cli_executable", return_value="claude"):
            await manager.set_bot_cli("main", "claude", "claude")

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex"), str(storage))

        assert restored.main_profile.cli_type == "claude"
        assert restored.main_profile.cli_path == "claude"

    def test_manager_uses_storage_local_settings_for_main_bot_profile(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        global_settings = temp_dir / "global" / ".web_admin_settings.json"
        global_settings.parent.mkdir()
        global_settings.write_text(
            json.dumps({"main_bot_profile": {"cli_type": "claude", "cli_path": "claude"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", global_settings)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex"), str(storage))

        assert manager.main_profile.cli_type == "codex"
        assert manager.main_profile.cli_path == "codex"

    @pytest.mark.asyncio
    async def test_main_bot_workdir_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
        old_dir = temp_dir / "old"
        new_dir = temp_dir / "new"
        old_dir.mkdir()
        new_dir.mkdir()

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(old_dir)), str(storage))
        await manager.set_bot_workdir("main", str(new_dir))

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", working_dir=str(old_dir)), str(storage))

        assert restored.main_profile.working_dir == str(new_dir)

    @pytest.mark.asyncio
    async def test_main_bot_cli_params_persist_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex"), str(storage))
        await manager.set_bot_cli_param("main", "codex", "model", "none")

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex"), str(storage))

        assert restored.main_profile.cli_params.get_param("codex", "model") is None

    @pytest.mark.asyncio
    async def test_main_bot_cluster_config_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex"), str(storage))
        await manager.update_bot_cluster(
            "main",
            {
                "enabled": True,
                "model_tiers": {
                    "low": "gpt-5.3-codex",
                    "medium": "gpt-5.4",
                    "high": "gpt-5.5",
                },
            },
        )

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex"), str(storage))

        assert restored.main_profile.cluster.enabled is True
        assert restored.main_profile.cluster.model_tiers["low"] == "gpt-5.3-codex"

    @pytest.mark.asyncio
    async def test_main_bot_agent_cluster_config_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex"), str(storage))
        await manager.create_bot_agent(
            "main",
            {
                "id": "tester",
                "name": "测试专家",
                "cluster": {
                    "allow_cluster": True,
                    "allow_write": True,
                    "session_policy": "ephemeral",
                    "timeout_seconds": 900,
                },
            },
        )

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok", cli_type="codex"), str(storage))
        agent = restored.main_profile.get_agent("tester")

        assert agent.cluster.allow_write is True
        assert agent.cluster.session_policy == "ephemeral"
        assert agent.cluster.timeout_seconds == 900

    @pytest.mark.asyncio
    async def test_managed_bot_avatar_persists_across_manager_reload(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "team2",
                    "token": "",
                    "cli_type": "claude",
                    "cli_path": "claude",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                    "bot_mode": "cli",
                    "avatar_name": "avatar_01.png",
                }
            ]
        }), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))
        await manager.set_bot_avatar("team2", "mint-teal.png")

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        assert restored.managed_profiles["team2"].avatar_name == "mint-teal.png"

    @pytest.mark.asyncio
    async def test_removed_bot_does_not_reuse_stale_persisted_avatar(self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
        storage = temp_dir / "bots.json"
        storage.write_text(json.dumps({
            "bots": [
                {
                    "alias": "team2",
                    "token": "",
                    "cli_type": "claude",
                    "cli_path": "claude",
                    "working_dir": str(temp_dir),
                    "enabled": True,
                    "bot_mode": "cli",
                    "avatar_name": "avatar_01.png",
                }
            ]
        }), encoding="utf-8")
        settings_file = temp_dir / ".web_admin_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

        manager = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))
        await manager.set_bot_avatar("team2", "mint-teal.png")

        with patch.object(manager, "_stop_application", AsyncMock(return_value=None)), \
             patch("bot.manager.resolve_cli_executable", return_value="claude"), \
             patch.object(manager, "_start_profile", AsyncMock(return_value=None)):
            await manager.remove_bot("team2")
            await manager.add_bot(
                alias="team2",
                token="",
                cli_type="claude",
                cli_path="claude",
                working_dir=str(temp_dir),
                bot_mode="cli",
            )

        restored = MultiBotManager(BotProfile(alias="main", token="main_tok"), str(storage))

        assert restored.managed_profiles["team2"].avatar_name == ""
        assert "avatar_name" not in json.loads(storage.read_text(encoding="utf-8"))["bots"][0]

    @pytest.mark.asyncio
    async def test_start_profile_is_web_only_noop(self, temp_dir: Path):
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

        app = await m._start_profile(web_only, is_main=False)

        assert app is None
        assert "web_only" not in m.applications

    @pytest.mark.asyncio
    async def test_start_watchdog_is_web_only_noop(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))

        await m.start_watchdog()
        await m.stop_watchdog()

        assert getattr(m, "_watchdog_task", None) is None

    @pytest.mark.asyncio
    async def test_shutdown_all_clears_stub_applications(self, temp_dir: Path):
        profile = BotProfile(alias="main", token="tok")
        m = MultiBotManager(main_profile=profile, storage_file=str(temp_dir / "b.json"))
        workdir = temp_dir / "repo"
        workdir.mkdir()
        session = get_or_create_session(123, "team1", 456, default_working_dir=str(workdir))
        m.applications["team1"] = MagicMock(bot_data={"bot_id": 123})
        m.bot_id_to_alias[123] = "team1"

        await m.shutdown_all()

        assert session.bot_alias == "team1"
        assert not m.applications
        assert 123 not in m.bot_id_to_alias

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
        main_profile = BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        # 没有启动任何 application，main 状态为 stopped
        lines = m.get_status_lines()
        # 新的格式返回包含 HTML 的字符串列表
        result = "\n".join(lines)
        assert "main" in result
        assert "🔴" in result  # stopped 状态的表情符号
        assert "主 Bot" in result

    def test_with_sub_bots(self, temp_dir: Path):
        main_profile = BotProfile(alias="main", token="main_tok", cli_type="codex", cli_path="codex")
        m = MultiBotManager(main_profile=main_profile, storage_file=str(temp_dir / "b.json"))
        m.managed_profiles["sub1"] = BotProfile(
            alias="sub1", token="tok1", cli_type="claude", cli_path="claude"
        )
        lines = m.get_status_lines()
        result = "\n".join(lines)
        assert "sub1" in result
        assert "claude" in result
        assert "托管 Bot" in result
