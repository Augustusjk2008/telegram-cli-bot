"""消息文本管理模块

所有用户-facing 的文本消息都从此模块加载，支持从 JSON 配置文件自定义。
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MESSAGES: Dict[str, Any] = {
    "kill": {
        "no_task": "ℹ️ 当前没有正在运行的任务",
        "killed": "✅ 已强制终止当前任务",
        "already_done": "ℹ️ 任务已经完成",
        "error": "❌ 终止进程时出错: {error}",
    },
    "upload": {
        "file_too_large": "❌ 文件太大，请发送小于 20MB 的文件",
    },
    "shell": {
        "usage": "用法: /exec <命令>",
        "dangerous": "⛔ 该命令被禁止执行（安全风险）",
        "no_output": "(无输出)",
    },
    "chat": {
        "busy": "⏳ 当前会话正在处理上一条消息，请稍后再试。",
        "no_cli": "❌ 未找到 CLI 可执行文件: {cli_path}\n请在设置页修改 CLI 路径。",
        "cli_failed": "❌ CLI 进程启动失败",
        "codex_resume_reset_hint": "当前 Codex 会话可能异常，请点“新会话”后重试。",
        "no_output": "(无输出)",
    },
    "startup": {
        "banner": "═══════════════════════════════════════════════════",
        "title": "  🤖 CLI Bridge Bot",
        "loading_config": "📋 正在加载配置...",
        "loaded": "✅ 配置加载完成",
        "restart": "🔄 正在重启整个程序并重载代码...",
        "shutdown": "🛑 正在关闭...",
    },
}


class MessageManager:
    _instance: Optional["MessageManager"] = None
    _messages: Dict[str, Any]

    def __new__(cls, config_path: Optional[str] = None) -> "MessageManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._messages = {}
            cls._instance._load(config_path)
        return cls._instance

    def _load(self, config_path: Optional[str] = None) -> None:
        self._messages = json.loads(json.dumps(DEFAULT_MESSAGES))
        paths_to_try = []
        if config_path:
            paths_to_try.append(Path(config_path))
        env_path = os.environ.get("MESSAGES_CONFIG")
        if env_path:
            paths_to_try.append(Path(env_path))
        current_dir = Path(__file__).parent
        paths_to_try.extend([
            current_dir / "messages.json",
            Path.cwd() / "messages.json",
            Path.cwd() / "bot" / "messages.json",
        ])
        for path in paths_to_try:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        user_messages = json.load(f)
                    self._merge_messages(self._messages, user_messages)
                    logger.info(f"已加载自定义消息配置: {path}")
                    return
                except Exception as e:
                    logger.warning(f"加载消息配置失败 {path}: {e}")
        logger.debug("使用默认消息配置")

    def _merge_messages(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_messages(base[key], value)
            else:
                base[key] = value

    def get(self, category: str, key: str, default: Optional[str] = None) -> Any:
        try:
            return self._messages[category][key]
        except KeyError:
            return default

    def format(self, category: str, key: str, **kwargs) -> str:
        template = self.get(category, key)
        if template is None:
            return f"[{category}.{key}]"
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"消息格式化缺少参数: {category}.{key}, missing {e}")
            return template


_messages: Optional[MessageManager] = None


def get_messages() -> MessageManager:
    global _messages
    if _messages is None:
        _messages = MessageManager()
    return _messages


def msg(category: str, key: str, **kwargs) -> str:
    return get_messages().format(category, key, **kwargs)
