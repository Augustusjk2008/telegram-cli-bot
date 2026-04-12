"""消息文本管理模块

所有用户-facing 的文本消息都从此模块加载，支持从 JSON 配置文件自定义。
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 默认消息配置
DEFAULT_MESSAGES: Dict[str, Any] = {
    "greeting": {
        "header": "👋 CLI Bridge Bot ({alias})",
        "current_config": "📌 当前配置:",
        "cli_label": "   CLI: {cli_type}",
        "cli_path_label": "   CLI路径: {cli_path}",
        "workdir_label": "   工作目录: {working_dir}",
        "msg_count_label": "   消息数: {message_count}",
        "session_id_labels": {
            "codex": "   Codex会话ID: {session_id}",
            "kimi": "   Kimi会话ID: {session_id}",
            "claude": "   Claude会话ID: {session_id} ({status})"
        },
        "session_id_not_created": "(未创建，收到首条消息后自动生成)",
        "claude_initialized": "已初始化",
        "claude_pending": "待初始化",
        "usage": "📝 基本用法:",
        "usage_direct": "   直接发送消息 - 与 AI 对话",
        "usage_slash": "   //xxx - 转发为 /xxx 给 CLI",
        "usage_file": "   发送文件 - 供 AI 分析",
        "commands": "🔧 命令列表:",
        "cmd_start": "   /start - 显示此帮助",
        "cmd_reset": "   /reset - 重置当前会话",
        "cmd_kill": "   /kill - 终止当前任务",
        "cmd_cd": "   /cd <路径> - 切换工作目录",
        "cmd_pwd": "   /pwd - 显示当前目录",
        "cmd_files": "   /files - 交互式浏览当前目录",
        "cmd_ls": "   /ls - 列出目录内容",
        "cmd_exec": "   /exec <cmd> - 执行 Shell 命令",
        "cmd_history": "   /history - 查看会话历史",
        "cmd_codex_status": "   /codex_status - 查询 Codex CLI 状态",
        "cmd_upload": "   /upload - 上传文件",
        "cmd_download": "   /download <文件> - 下载文件",
        "cmd_cat": "   /cat <文件> - 查看文件内容",
        "cmd_head": "   /head <文件> [行数] - 查看文件前N行",
        "cmd_kill_note": "   (主Bot 也可使用 /bot_kill <alias> [user_id] 终止指定 Bot 的任务)",
        "admin_commands_header": "🛠 主Bot管理命令:",
        "admin_cmd_help": "   /bot_help - 显示多Bot管理帮助",
        "admin_cmd_list": "   /bot_list - 列出所有Bot状态",
        "admin_cmd_restart": "   /restart - 重启整个程序（重载代码）",
        "admin_cmd_system": "   /system [脚本名] - 系统脚本管理",
        "admin_cmd_add": "   /bot_add <alias> <token> [bot_mode] [cli_type] [cli_path] [workdir]",
        "admin_cmd_remove": "   /bot_remove <alias>",
        "admin_cmd_start_stop": "   /bot_start <alias> / /bot_stop <alias>",
        "admin_cmd_set_cli": "   /bot_set_cli <alias> <cli_type> <cli_path>",
        "admin_cmd_set_workdir": "   /bot_set_workdir <alias> <workdir>",
        "admin_cmd_kill": "   /bot_kill <alias> [user_id] - 强制终止任务",
        "admin_cmd_params": "   /bot_params <alias> [cli_type] - 查看 CLI 参数配置",
        "admin_cmd_params_set": "   /bot_params_set <alias> <cli_type> <key> <value> - 设置 CLI 参数",
        "admin_cmd_params_reset": "   /bot_params_reset <alias> [cli_type] - 重置 CLI 参数",
        "admin_cmd_params_help": "   /bot_params_help [cli_type] - 显示 CLI 参数帮助",
        "admin_cmd_assistant_proposals": "   /assistant_proposals <alias> [status] - 查看 assistant proposal",
        "admin_cmd_assistant_approve": "   /assistant_approve <alias> <proposal_id> - 批准 proposal",
        "admin_cmd_assistant_reject": "   /assistant_reject <alias> <proposal_id> - 拒绝 proposal"
    },
    "auth": {
        "unauthorized": "⛔ 未授权的用户"
    },
    "reset": {
        "success": "🔄 会话已完全重置",
        "no_session": "ℹ️ 当前没有可重置的会话"
    },
    "kill": {
        "no_task": "ℹ️ 当前没有正在运行的任务",
        "killed": "✅ 已强制终止当前任务",
        "already_done": "ℹ️ 任务已经完成",
        "error": "❌ 终止进程时出错: {error}"
    },
    "cd": {
        "usage": "用法: /cd <路径>",
        "success": "📁 目录已切换:\n<code>{path}</code>",
        "persist_failed": "❌ 子Bot工作目录保存失败:\n<code>{error}</code>",
        "not_exist": "❌ 目录不存在:\n<code>{path}</code>"
    },
    "pwd": {
        "current_dir": "📂 当前目录:\n<code>{path}</code>"
    },
    "ls": {
        "dir_header": "📂 <code>{path}</code>",
        "empty": "(空目录)",
        "error": "❌ 错误: {error}"
    },
    "history": {
        "empty": "📭 暂无历史记录",
        "header": "📜 最近历史:\n\n"
    },
    "codex_status": {
        "unsupported_cli": "ℹ️ 当前 CLI 不是 Codex，无法查询 /codex_status",
        "success": "📊 <b>Codex 状态</b>\n\n<code>{status_line}</code>\n\n<i>{note}</i>",
        "note": "这是 Codex CLI 的状态显示，不一定等于账单额度。",
        "failed": "❌ 查询 Codex 状态失败: <code>{error}</code>"
    },
    "upload": {
        "help": "📤 <b>文件上传帮助</b>\n\n直接发送文件即可上传。\n<b>注意:</b> 文件将保存在当前工作目录。",
        "no_file": "⚠️ 请附加文件",
        "unsafe_filename": "⛔ 文件名包含非法字符",
        "file_too_large": "❌ 文件太大，请发送小于 20MB 的文件",
        "success": "✅ 文件已保存: <code>{filename}</code>",
        "failed": "❌ 保存文件失败: {error}"
    },
    "download": {
        "usage": "用法: /download <文件路径>",
        "not_found": "❌ 文件不存在",
        "unsafe_path": "⛔ 无效的文件路径",
        "unsafe_filename": "⛔ 文件名包含非法字符",
        "file_too_large": "❌ 文件太大 (>50MB)，无法通过 Telegram 发送",
        "error": "❌ 发送文件失败: {error}"
    },
    "shell": {
        "usage": "用法: /exec <命令>",
        "dangerous": "⛔ 该命令被禁止执行（安全风险）",
        "no_output": "(无输出)",
        "result": "🖥 <code>{command}</code>\n\n<pre>{output}</pre>",
        "error": "❌ 命令执行失败: {error}"
    },
    "chat": {
        "busy": "⏳ 当前会话正在处理上一条消息，请稍后再试。",
        "processing": "⏳ 处理中...",
        "processing_with_time": "⏳ 处理中，已等待 {elapsed} 秒...",
        "no_cli": "❌ 未找到CLI可执行文件: {cli_path}\n请用 /bot_set_cli 配置正确的命令名或完整路径",
        "cli_failed": "❌ CLI 进程启动失败",
        "error": "❌ 错误: {error}",
        "timeout": "⏱️ <b>任务已超时终止</b>\n执行时间超过 {timeout} 秒，进程已被强制结束。",
        "timeout_collecting": "⏱️ 已超时（{elapsed}秒），正在收集剩余输出...",
        "timeout_warning": "⚠️ 任务已超时，但已收集到部分输出。如需继续对话，可继续发送消息。",
        "no_output": "(无输出)",
        "timeout_no_output": "(进程已超时终止，无输出)"
    },
    "admin": {
        "unauthorized": "⛔ 需要管理员权限",
        "help_text": "🛠 多Bot管理命令:\n\n0) 重启整个程序（重载代码）:\n   /restart\n\n1) 添加并启动子Bot:\n   /bot_add <alias> <token> [bot_mode] [cli_type] [cli_path] [workdir]\n   bot_mode 支持: cli(默认) / assistant\n   cli_type 支持: kimi / claude / codex\n   例: /bot_add team1 123:abc cli codex codex C:/work/project\n   例: /bot_add helper 456:def assistant claude claude C:/work\n\n2) 查看状态:\n   /bot_list\n\n3) 停止/启动:\n   /bot_stop <alias>\n   /bot_start <alias>\n\n4) 修改CLI配置:\n   /bot_set_cli <alias> <cli_type> <cli_path>\n   /bot_set_workdir <alias> <workdir>\n\n5) 删除子Bot:\n   /bot_remove <alias>\n\n6) 强制终止任务:\n   /bot_kill <alias> [user_id]\n   例: /bot_kill main        (终止主Bot所有任务)\n   例: /bot_kill team1       (终止team1所有任务)\n   例: /bot_kill main 12345  (终止主Bot指定用户的任务)\n\n7) 系统脚本管理:\n   /system          (列出所有可用脚本)\n   /system <脚本名>  (执行指定脚本)\n\n8) CLI 参数配置:\n   /bot_params <alias> [cli_type]     - 查看当前参数\n   /bot_params_set <alias> <type> <key> <value>  - 设置参数\n   /bot_params_reset <alias> [cli_type] - 重置参数\n   /bot_params_help [cli_type]        - 显示参数帮助\n\n9) Assistant proposal 审批:\n   /assistant_proposals <alias> [status]\n   /assistant_approve <alias> <proposal_id>\n   /assistant_reject <alias> <proposal_id>",
        "restart": "🔄 正在重启整个程序并重载代码...",
        "bot_add_usage": "用法: /bot_add <alias> <token> [bot_mode] [cli_type] [cli_path] [workdir]\nbot_mode: cli(默认) | assistant\nassistant: 最多一个，且必须显式提供 workdir",
        "bot_add_success": "✅ 子Bot已启动\nalias: <code>{alias}</code>\nusername: @{username}\nmode: <code>{bot_mode}</code>\ncli: <code>{cli_type}</code> / <code>{cli_path}</code>\nworkdir: <code>{workdir}</code>",
        "bot_add_failed": "❌ 添加失败: {error}",
        "bot_remove_usage": "用法: /bot_remove <alias>",
        "bot_remove_success": "✅ 已删除子Bot: <code>{alias}</code>",
        "bot_remove_failed": "❌ 删除失败: {error}",
        "bot_start_usage": "用法: /bot_start <alias>",
        "bot_start_success": "✅ 已启动子Bot: <code>{alias}</code>",
        "bot_start_failed": "❌ 启动失败: {error}",
        "bot_stop_usage": "用法: /bot_stop <alias>",
        "bot_stop_success": "✅ 已停止子Bot: <code>{alias}</code>",
        "bot_stop_failed": "❌ 停止失败: {error}",
        "bot_set_cli_usage": "用法: /bot_set_cli <alias> <cli_type> <cli_path>",
        "bot_set_cli_success": "✅ 已更新CLI配置: <code>{alias}</code> -> <code>{cli_type}</code> / <code>{cli_path}</code>",
        "bot_set_cli_failed": "❌ 更新失败: {error}",
        "bot_set_workdir_usage": "用法: /bot_set_workdir <alias> <workdir>",
        "bot_set_workdir_success": "✅ 已更新工作目录: <code>{alias}</code> -> <code>{workdir}</code>",
        "bot_set_workdir_failed": "❌ 更新失败: {error}",
        "bot_kill_usage": "用法: /bot_kill <alias> [user_id]\n  alias: Bot 别名（main 表示主Bot）\n  user_id: 可选，指定终止哪个用户的任务，不填则终止所有用户",
        "bot_kill_invalid_user_id": "❌ user_id 必须是数字",
        "bot_kill_not_running": "❌ Bot <code>{alias}</code> 未运行或不存在",
        "bot_kill_success": "✅ 已强制终止 <code>{alias}</code> 的任务:",
        "bot_kill_user_line": "  • 用户 <code>{user_id}</code>",
        "bot_kill_no_task_user": "ℹ️ <code>{alias}</code> 的用户 <code>{user_id}</code> 没有正在运行的任务",
        "bot_kill_no_task": "ℹ️ <code>{alias}</code> 当前没有正在运行的任务",
        "system_no_scripts_dir": "❌ scripts 目录不存在: {path}",
        "system_no_scripts": "📂 scripts 目录暂无可用脚本\n\n支持的格式: {extensions}\n路径: <code>{path}</code>",
        "system_menu_title": "📂 <b>系统脚本菜单</b>\n\n点击按钮直接执行脚本，或使用命令:\n<code>/system &lt;脚本名&gt;</code>",
        "system_script_not_found": "❌ 未找到脚本: <code>{script_name}</code>\n\n可用脚本: <code>{available}</code>",
        "system_executing": "🖥️ 正在执行脚本: <code>{script_name}</code>...",
        "system_exec_success": "✅ <code>{script_name}</code> 执行成功:\n\n<pre>{output}</pre>",
        "system_exec_failed": "❌ <code>{script_name}</code> 执行失败:\n\n<pre>{output}</pre>",
        # CLI 参数配置相关消息
        "bot_params_usage": "用法: /bot_params <alias> [cli_type]\n\n示例:\n  /bot_params main         # 查看 main bot 的所有参数\n  /bot_params team1 claude # 只查看 team1 的 claude 参数",
        "bot_params_not_found": "❌ 未找到 alias 为 <code>{alias}</code> 的 Bot",
        "bot_params_failed": "❌ 获取参数失败: {error}",
        "bot_params_set_usage": "用法: /bot_params_set <alias> <cli_type> <key> <value>\n\n示例:\n  /bot_params_set team1 claude effort high\n  /bot_params_set team1 kimi thinking false\n  /bot_params_set team1 codex model o4-mini\n\n使用 /bot_params_help [cli_type] 查看可用参数",
        "bot_params_set_success": "✅ 已设置参数\nBot: <code>{alias}</code>\nCLI: <code>{cli_type}</code>\n参数: <code>{param_key}</code> = <code>{value}</code>",
        "bot_params_set_failed": "❌ 设置参数失败: {error}",
        "bot_params_reset_usage": "用法: /bot_params_reset <alias> [cli_type]\n\n示例:\n  /bot_params_reset team1         # 重置 team1 的所有参数\n  /bot_params_reset team1 claude  # 只重置 team1 的 claude 参数",
        "bot_params_reset_success": "✅ 已重置 <code>{alias}</code> 的所有 CLI 参数为默认值",
        "bot_params_reset_partial_success": "✅ 已重置 <code>{alias}</code> 的 <code>{cli_type}</code> 参数为默认值",
        "bot_params_reset_failed": "❌ 重置参数失败: {error}",
        "assistant_proposals_usage": "用法: /assistant_proposals <alias> [status]",
        "assistant_review_usage": "用法: /assistant_approve <alias> <proposal_id>\n或: /assistant_reject <alias> <proposal_id>",
        "assistant_proposals_header": "🧾 <code>{alias}</code> 的 assistant proposals:",
        "assistant_proposals_empty": "📭 <code>{alias}</code> 暂无 assistant proposal",
        "assistant_review_success": "✅ Proposal <code>{proposal_id}</code> 已更新为 <code>{status}</code>",
        "assistant_proposals_failed": "❌ assistant proposal 操作失败: {error}"
    },
    "voice": {
        "disabled": "❌ 语音识别功能未启用\n\n请在 .env 中设置:\nWHISPER_ENABLED=true\n\n并安装依赖:\npip install openai-whisper pydub",
        "too_long": "❌ 语音时长超过限制（最大 {max_duration} 秒）",
        "downloading": "🎤 正在接收语音消息（{duration}秒）...",
        "converting": "🔄 正在转换音频格式...",
        "convert_failed": "❌ 音频格式转换失败\n\n请确保已安装 FFmpeg:\nWindows: choco install ffmpeg\nLinux: sudo apt install ffmpeg",
        "recognizing": "🧠 正在识别语音内容...",
        "recognized": "✅ <b>识别结果:</b>\n<pre>{text}</pre>\n\n正在发送给 AI 处理...",
        "recognize_failed": "❌ 语音识别失败: {error}",
        "error": "❌ 处理语音消息时出错: {error}"
    },
    "startup": {
        "banner": "═══════════════════════════════════════════════════",
        "title": "  🤖 Telegram CLI Bridge Bot",
        "version": "  版本: 1.0.0",
        "loading_config": "📋 正在加载配置...",
        "loaded": "✅ 配置加载完成",
        "starting": "🚀 正在启动 Bot...",
        "started": "✅ Bot 启动完成",
        "main_bot_started": "✅ 主Bot (@{username}) 启动成功",
        "managed_bots_loaded": "📦 已加载 {count} 个托管Bot配置",
        "starting_managed": "🚀 正在启动托管Bot...",
        "all_started": "✅ 所有 Bot 启动完成，共 {count} 个",
        "polling_started": "▶️ 开始消息轮询...",
        "restart": "🔄 正在重启整个程序并重载代码...",
        "shutdown": "🛑 正在关闭...",
        "shutdown_complete": "✅ 已安全关闭"
    }
}


class MessageManager:
    """消息管理器，支持从 JSON 文件加载自定义消息"""
    
    _instance: Optional["MessageManager"] = None
    _messages: Dict[str, Any]
    
    def __new__(cls, config_path: Optional[str] = None) -> "MessageManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._messages = {}
            cls._instance._load(config_path)
        return cls._instance
    
    def _load(self, config_path: Optional[str] = None) -> None:
        """加载消息配置"""
        # 先加载默认值
        self._messages = json.loads(json.dumps(DEFAULT_MESSAGES))
        
        # 尝试从文件加载
        paths_to_try = []
        if config_path:
            paths_to_try.append(Path(config_path))
        
        # 环境变量指定的路径
        env_path = os.environ.get("MESSAGES_CONFIG")
        if env_path:
            paths_to_try.append(Path(env_path))
        
        # 默认路径
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
                    # 递归合并用户配置
                    self._merge_messages(self._messages, user_messages)
                    logger.info(f"已加载自定义消息配置: {path}")
                    return
                except Exception as e:
                    logger.warning(f"加载消息配置失败 {path}: {e}")
        
        logger.debug("使用默认消息配置")
    
    def _merge_messages(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """递归合并消息配置"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_messages(base[key], value)
            else:
                base[key] = value
    
    def get(self, category: str, key: str, default: Optional[str] = None) -> Any:
        """获取指定类别的消息"""
        try:
            result = self._messages[category][key]
            return result
        except KeyError:
            return default
    
    def format(self, category: str, key: str, **kwargs) -> str:
        """获取并格式化消息"""
        template = self.get(category, key)
        if template is None:
            return f"[{category}.{key}]"
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"消息格式化缺少参数: {category}.{key}, missing {e}")
            return template
    
    def get_category(self, category: str) -> Dict[str, Any]:
        """获取整个类别的消息"""
        return self._messages.get(category, {})
    
    def reload(self, config_path: Optional[str] = None) -> None:
        """重新加载配置"""
        self._instance = None
        self.__class__._instance = None
        MessageManager(config_path)


# 全局消息管理器实例
_messages: Optional[MessageManager] = None


def get_messages() -> MessageManager:
    """获取全局消息管理器实例"""
    global _messages
    if _messages is None:
        _messages = MessageManager()
    return _messages


def msg(category: str, key: str, **kwargs) -> str:
    """快捷函数：获取并格式化消息"""
    return get_messages().format(category, key, **kwargs)


def reload_messages(config_path: Optional[str] = None) -> None:
    """重新加载消息配置"""
    global _messages
    _messages = None
    MessageManager._instance = None
    _messages = MessageManager(config_path)
