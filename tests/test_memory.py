"""测试长期记忆系统"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from bot.assistant.memory import Memory, MemoryStore, get_memory_store
from bot.handlers.assistant import (
    cmd_memory,
    cmd_memory_search,
    cmd_memory_delete,
    cmd_memory_clear
)


@pytest.fixture
def temp_memory_file(tmp_path):
    """创建临时记忆文件"""
    memory_file = tmp_path / "test_memories.json"
    return memory_file


@pytest.fixture
def memory_store(temp_memory_file):
    """创建测试用的记忆存储实例"""
    return MemoryStore(temp_memory_file)


class TestMemory:
    """测试 Memory 数据类"""

    def test_memory_creation(self):
        """测试创建记忆对象"""
        memory = Memory(
            id="user_123_1234567890",
            user_id=123,
            content="用户名叫张三",
            category="personal",
            created_at="2026-03-06T10:00:00",
            updated_at="2026-03-06T10:00:00",
            tags=["姓名"]
        )

        assert memory.user_id == 123
        assert memory.content == "用户名叫张三"
        assert memory.category == "personal"
        assert "姓名" in memory.tags

    def test_memory_to_dict(self):
        """测试记忆对象转字典"""
        memory = Memory(
            id="user_123_1234567890",
            user_id=123,
            content="用户名叫张三",
            category="personal",
            created_at="2026-03-06T10:00:00",
            updated_at="2026-03-06T10:00:00",
            tags=["姓名"]
        )

        data = memory.to_dict()
        assert data["user_id"] == 123
        assert data["content"] == "用户名叫张三"
        assert data["category"] == "personal"

    def test_memory_from_dict(self):
        """测试从字典创建记忆对象"""
        data = {
            "id": "user_123_1234567890",
            "user_id": 123,
            "content": "用户名叫张三",
            "category": "personal",
            "created_at": "2026-03-06T10:00:00",
            "updated_at": "2026-03-06T10:00:00",
            "tags": ["姓名"]
        }

        memory = Memory.from_dict(data)
        assert memory.user_id == 123
        assert memory.content == "用户名叫张三"


class TestMemoryStore:
    """测试 MemoryStore 记忆存储"""

    def test_ensure_file_exists(self, memory_store, temp_memory_file):
        """测试文件初始化"""
        assert temp_memory_file.exists()

        with open(temp_memory_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["version"] == "1.0"
        assert data["memories"] == []

    def test_add_memory(self, memory_store):
        """测试添加记忆"""
        memory = memory_store.add_memory(
            user_id=123,
            content="用户名叫张三，是一名软件工程师",
            category="personal",
            tags=["姓名", "职业"]
        )

        assert memory.user_id == 123
        assert memory.content == "用户名叫张三，是一名软件工程师"
        assert memory.category == "personal"
        assert "姓名" in memory.tags
        assert "职业" in memory.tags

    def test_get_user_memories(self, memory_store):
        """测试获取用户记忆"""
        # 添加多条记忆
        memory_store.add_memory(123, "用户名叫张三", "personal", ["姓名"])
        memory_store.add_memory(123, "喜欢喝咖啡", "preference", ["饮品"])
        memory_store.add_memory(456, "另一个用户", "personal", ["姓名"])

        # 获取用户 123 的记忆
        memories = memory_store.get_user_memories(123)
        assert len(memories) == 2
        assert all(m.user_id == 123 for m in memories)

        # 获取用户 456 的记忆
        memories = memory_store.get_user_memories(456)
        assert len(memories) == 1
        assert memories[0].content == "另一个用户"

    def test_search_memories_by_keyword(self, memory_store):
        """测试按关键词搜索记忆"""
        memory_store.add_memory(123, "用户名叫张三，是软件工程师", "personal", ["姓名", "职业"])
        memory_store.add_memory(123, "喜欢喝咖啡", "preference", ["饮品"])
        memory_store.add_memory(123, "在北京工作", "work", ["地点"])

        # 搜索"工程师"
        results = memory_store.search_memories(123, keyword="工程师")
        assert len(results) == 1
        assert "工程师" in results[0].content

        # 搜索"工作"
        results = memory_store.search_memories(123, keyword="工作")
        assert len(results) == 1
        assert "工作" in results[0].content

    def test_search_memories_by_category(self, memory_store):
        """测试按分类搜索记忆"""
        memory_store.add_memory(123, "用户名叫张三", "personal", ["姓名"])
        memory_store.add_memory(123, "喜欢喝咖啡", "preference", ["饮品"])
        memory_store.add_memory(123, "在北京工作", "work", ["地点"])

        # 搜索 personal 分类
        results = memory_store.search_memories(123, category="personal")
        assert len(results) == 1
        assert results[0].category == "personal"

        # 搜索 preference 分类
        results = memory_store.search_memories(123, category="preference")
        assert len(results) == 1
        assert results[0].category == "preference"

    def test_search_memories_by_tag(self, memory_store):
        """测试按标签搜索记忆"""
        memory_store.add_memory(123, "用户名叫张三", "personal", ["姓名", "个人"])
        memory_store.add_memory(123, "喜欢喝咖啡", "preference", ["饮品"])

        # 搜索标签"姓名"
        results = memory_store.search_memories(123, keyword="姓名")
        assert len(results) == 1
        assert "姓名" in results[0].tags

    def test_delete_memory(self, memory_store):
        """测试删除记忆"""
        memory = memory_store.add_memory(123, "用户名叫张三", "personal", ["姓名"])
        memory_id = memory.id

        # 删除记忆
        success = memory_store.delete_memory(memory_id)
        assert success

        # 验证已删除
        memories = memory_store.get_user_memories(123)
        assert len(memories) == 0

        # 删除不存在的记忆
        success = memory_store.delete_memory("nonexistent_id")
        assert not success

    def test_clear_user_memories(self, memory_store):
        """测试清空用户记忆"""
        memory_store.add_memory(123, "记忆1", "personal", [])
        memory_store.add_memory(123, "记忆2", "preference", [])
        memory_store.add_memory(456, "其他用户记忆", "personal", [])

        # 清空用户 123 的记忆
        count = memory_store.clear_user_memories(123)
        assert count == 2

        # 验证用户 123 的记忆已清空
        memories = memory_store.get_user_memories(123)
        assert len(memories) == 0

        # 验证用户 456 的记忆未受影响
        memories = memory_store.get_user_memories(456)
        assert len(memories) == 1

    def test_get_recent_memories(self, memory_store):
        """测试获取最近记忆"""
        # 添加多条记忆
        for i in range(10):
            memory_store.add_memory(123, f"记忆{i}", "other", [])

        # 获取最近 5 条
        recent = memory_store.get_recent_memories(123, limit=5)
        assert len(recent) == 5

        # 验证是按时间倒序排列
        for i in range(len(recent) - 1):
            assert recent[i].updated_at >= recent[i + 1].updated_at


class TestMemoryCommands:
    """测试记忆管理命令"""

    @pytest.fixture
    def mock_update(self):
        """模拟 Telegram Update"""
        update = MagicMock()
        update.effective_user.id = 123
        update.message.reply_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """模拟 Telegram Context"""
        context = MagicMock()
        context.args = []
        return context

    @pytest.mark.asyncio
    async def test_cmd_memory_empty(self, mock_update, mock_context, memory_store):
        """测试查看空记忆列表"""
        with patch("bot.handlers.assistant.get_memory_store", return_value=memory_store):
            await cmd_memory(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "暂无记忆" in call_args

    @pytest.mark.asyncio
    async def test_cmd_memory_with_data(self, mock_update, mock_context, memory_store):
        """测试查看记忆列表"""
        memory_store.add_memory(123, "用户名叫张三", "personal", ["姓名"])
        memory_store.add_memory(123, "喜欢喝咖啡", "preference", ["饮品"])

        with patch("bot.handlers.assistant.get_memory_store", return_value=memory_store):
            await cmd_memory(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "张三" in call_args
            assert "咖啡" in call_args

    @pytest.mark.asyncio
    async def test_cmd_memory_search(self, mock_update, mock_context, memory_store):
        """测试搜索记忆"""
        memory_store.add_memory(123, "用户名叫张三，是软件工程师", "personal", ["姓名", "职业"])
        memory_store.add_memory(123, "喜欢喝咖啡", "preference", ["饮品"])

        mock_context.args = ["工程师"]

        with patch("bot.handlers.assistant.get_memory_store", return_value=memory_store):
            await cmd_memory_search(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "工程师" in call_args

    @pytest.mark.asyncio
    async def test_cmd_memory_delete(self, mock_update, mock_context, memory_store):
        """测试删除记忆"""
        memory = memory_store.add_memory(123, "用户名叫张三", "personal", ["姓名"])
        mock_context.args = [memory.id]

        with patch("bot.handlers.assistant.get_memory_store", return_value=memory_store):
            await cmd_memory_delete(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "已删除" in call_args

    @pytest.mark.asyncio
    async def test_cmd_memory_clear(self, mock_update, mock_context, memory_store):
        """测试清空记忆"""
        memory_store.add_memory(123, "记忆1", "personal", [])
        memory_store.add_memory(123, "记忆2", "preference", [])

        with patch("bot.handlers.assistant.get_memory_store", return_value=memory_store):
            await cmd_memory_clear(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "已清空" in call_args
            assert "2" in call_args
