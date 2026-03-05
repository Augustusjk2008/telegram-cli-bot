"""
上下文帮助函数测试

直接导入 bot.context_helpers 中的真实函数进行测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.context_helpers import (
    ensure_admin,
    get_bot_alias,
    get_bot_id,
    get_current_profile,
    get_current_session,
    get_manager,
    is_main_application,
)


class TestIsMainApplication:
    """测试 is_main_application"""

    def test_is_main(self, mock_context):
        mock_context.application.bot_data["is_main"] = True
        assert is_main_application(mock_context) is True

    def test_is_not_main(self, mock_context):
        mock_context.application.bot_data["is_main"] = False
        assert is_main_application(mock_context) is False

    def test_missing_key_defaults_false(self, mock_context):
        mock_context.application.bot_data = {}
        assert is_main_application(mock_context) is False


class TestGetBotAlias:
    """测试 get_bot_alias"""

    def test_get_alias(self, mock_context):
        mock_context.application.bot_data["bot_alias"] = "my_bot"
        assert get_bot_alias(mock_context) == "my_bot"


class TestGetBotId:
    """测试 get_bot_id"""

    def test_get_id(self, mock_update, mock_context):
        mock_context.application.bot_data["bot_id"] = 12345
        result = get_bot_id(mock_update, mock_context)
        assert result == 12345


class TestGetManager:
    """测试 get_manager"""

    def test_get_manager(self, mock_context):
        manager_mock = MagicMock()
        mock_context.application.bot_data["manager"] = manager_mock
        result = get_manager(mock_context)
        assert result is manager_mock


class TestGetCurrentProfile:
    """测试 get_current_profile"""

    def test_get_profile(self, mock_context):
        manager_mock = MagicMock()
        profile_mock = MagicMock()
        manager_mock.get_profile.return_value = profile_mock
        mock_context.application.bot_data["manager"] = manager_mock
        mock_context.application.bot_data["bot_alias"] = "main"
        result = get_current_profile(mock_context)
        assert result is profile_mock
        manager_mock.get_profile.assert_called_with("main")


class TestGetCurrentSession:
    """测试 get_current_session"""

    def test_get_session(self, mock_update, mock_context, temp_dir):
        manager_mock = MagicMock()
        profile_mock = MagicMock()
        profile_mock.working_dir = str(temp_dir)
        manager_mock.get_profile.return_value = profile_mock
        mock_context.application.bot_data["manager"] = manager_mock
        mock_context.application.bot_data["bot_alias"] = "main"
        mock_context.application.bot_data["bot_id"] = 111

        mock_update.effective_user.id = 12345

        session = get_current_session(mock_update, mock_context)
        assert session.user_id == 12345
        assert session.bot_id == 111


class TestEnsureAdmin:
    """测试 ensure_admin"""

    @pytest.mark.asyncio
    async def test_not_main_app(self, mock_update, mock_context):
        mock_context.application.bot_data["is_main"] = False
        result = await ensure_admin(mock_update, mock_context)
        assert result is False
        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_not_authorized(self, mock_update, mock_context):
        mock_context.application.bot_data["is_main"] = True
        with patch("bot.context_helpers.check_auth", return_value=False):
            result = await ensure_admin(mock_update, mock_context)
        assert result is False
