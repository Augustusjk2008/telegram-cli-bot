"""长期记忆管理模块

记忆数据结构设计原则：
1. 精炼：每条记忆只保留核心信息，避免冗余
2. 准确：通过 AI 提炼，确保信息准确性
3. 易于人工修改：使用 JSON 格式，结构清晰，支持手动编辑
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

# 记忆文件存储路径
MEMORY_DIR = Path(__file__).parent.parent / "data"
MEMORY_FILE = MEMORY_DIR / "memories.json"


@dataclass
class Memory:
    """单条记忆数据结构

    设计为易于人工阅读和编辑的格式
    """
    id: str  # 唯一标识，格式: user_{user_id}_{timestamp}
    user_id: int  # 用户 ID
    content: str  # 记忆内容（精炼后的文本）
    category: str  # 分类: personal/preference/work/fact/other
    created_at: str  # 创建时间 ISO 格式
    updated_at: str  # 最后更新时间
    tags: List[str]  # 关键词标签，用于检索

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        return cls(**data)


class MemoryStore:
    """记忆存储管理器

    使用 JSON 文件存储，格式设计为易于人工编辑：
    {
        "version": "1.0",
        "memories": [
            {
                "id": "user_123_1234567890",
                "user_id": 123,
                "content": "用户名叫张三，是一名软件工程师",
                "category": "personal",
                "created_at": "2026-03-06T10:00:00",
                "updated_at": "2026-03-06T10:00:00",
                "tags": ["姓名", "职业"]
            }
        ]
    }
    """

    def __init__(self, file_path: Path = MEMORY_FILE):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """确保存储文件和目录存在"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save_data({"version": "1.0", "memories": []})

    def _load_data(self) -> dict:
        """加载记忆数据"""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载记忆文件失败: {e}")
            return {"version": "1.0", "memories": []}

    def _save_data(self, data: dict):
        """保存记忆数据（格式化输出，便于人工编辑）"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存记忆文件失败: {e}")

    def add_memory(
        self,
        user_id: int,
        content: str,
        category: str = "other",
        tags: Optional[List[str]] = None
    ) -> Memory:
        """添加新记忆

        Args:
            user_id: 用户 ID
            content: 记忆内容（应该是精炼后的文本）
            category: 分类 (personal/preference/work/fact/other)
            tags: 关键词标签列表

        Returns:
            创建的 Memory 对象
        """
        now = datetime.now().isoformat()
        memory_id = f"user_{user_id}_{int(datetime.now().timestamp())}"

        memory = Memory(
            id=memory_id,
            user_id=user_id,
            content=content.strip(),
            category=category,
            created_at=now,
            updated_at=now,
            tags=tags or []
        )

        data = self._load_data()
        data["memories"].append(memory.to_dict())
        self._save_data(data)

        logger.info(f"添加记忆: user_id={user_id}, category={category}")
        return memory

    def get_user_memories(self, user_id: int) -> List[Memory]:
        """获取指定用户的所有记忆"""
        data = self._load_data()
        memories = [
            Memory.from_dict(m)
            for m in data["memories"]
            if m["user_id"] == user_id
        ]
        return memories

    def search_memories(
        self,
        user_id: int,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10
    ) -> List[Memory]:
        """搜索记忆

        Args:
            user_id: 用户 ID
            keyword: 关键词（在 content 和 tags 中搜索）
            category: 分类筛选
            limit: 返回数量限制

        Returns:
            匹配的记忆列表（按时间倒序）
        """
        memories = self.get_user_memories(user_id)

        # 分类筛选
        if category:
            memories = [m for m in memories if m.category == category]

        # 关键词搜索
        if keyword:
            keyword_lower = keyword.lower()
            memories = [
                m for m in memories
                if keyword_lower in m.content.lower()
                or any(keyword_lower in tag.lower() for tag in m.tags)
            ]

        # 按时间倒序排序
        memories.sort(key=lambda m: m.updated_at, reverse=True)

        return memories[:limit]

    def delete_memory(self, memory_id: str) -> bool:
        """删除指定记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        data = self._load_data()
        original_count = len(data["memories"])
        data["memories"] = [m for m in data["memories"] if m["id"] != memory_id]

        if len(data["memories"]) < original_count:
            self._save_data(data)
            logger.info(f"删除记忆: {memory_id}")
            return True
        return False

    def clear_user_memories(self, user_id: int) -> int:
        """清空指定用户的所有记忆

        Args:
            user_id: 用户 ID

        Returns:
            删除的记忆数量
        """
        data = self._load_data()
        original_count = len(data["memories"])
        data["memories"] = [m for m in data["memories"] if m["user_id"] != user_id]
        deleted_count = original_count - len(data["memories"])

        if deleted_count > 0:
            self._save_data(data)
            logger.info(f"清空用户记忆: user_id={user_id}, count={deleted_count}")

        return deleted_count

    def get_recent_memories(self, user_id: int, limit: int = 5) -> List[Memory]:
        """获取最近的记忆（用于注入对话上下文）

        Args:
            user_id: 用户 ID
            limit: 返回数量

        Returns:
            最近的记忆列表
        """
        memories = self.get_user_memories(user_id)
        memories.sort(key=lambda m: m.updated_at, reverse=True)
        return memories[:limit]

    def read_user_memories_json(self, user_id: int) -> str:
        """读取用户记忆（JSON 格式，供 AI tool use）

        Args:
            user_id: 用户 ID

        Returns:
            JSON 字符串，包含用户的所有记忆
        """
        memories = self.get_user_memories(user_id)
        memories_data = [m.to_dict() for m in memories]
        return json.dumps(memories_data, ensure_ascii=False, indent=2)

    def write_user_memories_json(self, user_id: int, memories_json: str) -> bool:
        """写入用户记忆（JSON 格式，供 AI tool use）

        AI 负责去重、合并、更新记忆，然后一次性写回

        Args:
            user_id: 用户 ID
            memories_json: JSON 字符串，包含更新后的记忆列表

        Returns:
            是否写入成功
        """
        try:
            # 解析 AI 提供的记忆数据
            new_memories_data = json.loads(memories_json)

            # 验证数据格式
            if not isinstance(new_memories_data, list):
                logger.error("记忆数据格式错误：必须是列表")
                return False

            # 加载完整数据
            data = self._load_data()

            # 移除该用户的旧记忆
            data["memories"] = [m for m in data["memories"] if m["user_id"] != user_id]

            # 添加新记忆（确保 user_id 正确）
            for mem_data in new_memories_data:
                mem_data["user_id"] = user_id  # 强制设置正确的 user_id
                data["memories"].append(mem_data)

            # 保存
            self._save_data(data)
            logger.info(f"AI 更新记忆成功: user_id={user_id}, count={len(new_memories_data)}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"解析记忆 JSON 失败: {e}")
            return False
        except Exception as e:
            logger.error(f"写入记忆失败: {e}")
            return False


# 全局单例
_memory_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """获取全局记忆存储实例"""
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store
