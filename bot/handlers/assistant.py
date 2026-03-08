"""助手模式的消息处理器"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot.assistant.llm import (
    ANTHROPIC_AVAILABLE,
    call_claude_with_memory_tools,
    call_claude_with_memory_tools_stream,
    get_tool_usage_summary,
)
from bot.assistant.memory import get_memory_store
from bot.context_helpers import get_current_session
from bot.config import ANTHROPIC_MODEL

logger = logging.getLogger(__name__)
call_claude_api = call_claude_with_memory_tools
_DEFAULT_CALL_CLAUDE_API = call_claude_api


async def handle_assistant_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理助手模式的文本消息"""
    if not update.message or not update.message.text:
        return

    if not ANTHROPIC_AVAILABLE:
        await update.message.reply_text(
            "❌ 助手模式不可用：anthropic SDK 未安装\n\n"
            "请运行: pip install anthropic"
        )
        return

    user_text = update.message.text.strip()
    if not user_text:
        return

    session = get_current_session(update, context)
    session.touch()

    user_id = update.effective_user.id

    # 构建对话历史
    messages = []
    for item in session.history[-10:]:  # 只取最近10条
        if item["role"] in ("user", "assistant"):
            messages.append({
                "role": item["role"],
                "content": item["content"]
            })

    # 添加当前用户消息
    messages.append({
        "role": "user",
        "content": user_text
    })

    # 发送"正在思考"提示
    status_msg = await update.message.reply_text("🤔 正在思考...")

    try:
        # 判断是否为首次对话（历史记录为空或只有当前消息）
        is_first_message = len(session.history) == 0

        # 构建系统提示，注入长期记忆
        system_prompt = _build_system_prompt_with_memory(user_id, is_first_message)

        response_text = ""
        usage_info = {}

        # 兼容旧测试和旧扩展点：如果调用方显式 patch 了 call_claude_api，就走非流式入口。
        if call_claude_api is not _DEFAULT_CALL_CLAUDE_API:
            response = await call_claude_api(
                messages=messages,
                system_prompt=system_prompt,
                user_id=user_id
            )
            response_text = response if isinstance(response, str) else str(response)
        else:
            # 默认仍走流式 + 记忆工具链
            async for event in call_claude_with_memory_tools_stream(
                messages=messages,
                system_prompt=system_prompt,
                user_id=user_id
            ):
                if event["type"] == "text":
                    response_text += event["text"]

                    # 每收到一定长度的文本就更新消息（避免过于频繁）
                    if len(response_text) % 100 < len(event["text"]):
                        try:
                            await status_msg.edit_text(response_text)
                        except Exception:
                            # 消息内容未变化或其他错误，忽略
                            pass

                elif event["type"] == "usage":
                    usage_info = event

        # 最终更新：完整文本 + token 使用信息
        final_text = response_text
        if usage_info:
            input_tokens = usage_info.get("input_tokens", 0)
            output_tokens = usage_info.get("output_tokens", 0)
            total_tokens = input_tokens + output_tokens
            final_text += f"\n\n💰 Token 使用: {input_tokens} 输入 + {output_tokens} 输出 = {total_tokens} 总计"

        try:
            await status_msg.edit_text(final_text)
        except Exception:
            # 如果编辑失败（可能消息太长），删除旧消息并发送新消息
            try:
                await status_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(final_text)

        # 保存到历史
        session.add_to_history("user", user_text)
        session.add_to_history("assistant", response_text)

    except Exception as e:
        logger.error(f"调用 Claude API 失败: {e}")
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ 调用 API 失败: {str(e)}\n\n"
            f"请检查 ANTHROPIC_API_KEY 环境变量是否正确设置"
        )


def _build_system_prompt_with_memory(user_id: int, is_first_message: bool = False) -> str:
    """构建包含长期记忆的系统提示词

    Args:
        user_id: 用户ID
        is_first_message: 是否为首次对话（首次会包含详细的工具使用指南）

    Returns:
        系统提示词字符串
    """
    base_prompt = (
        f"你是友好、专业的AI助手，使用{ANTHROPIC_MODEL}模型。用中文简洁回答。"
        f"你的名字不是'kiro'，不要称呼自己为'kiro'。\n\n"
    )

    # 只在首次对话时传入详细的工具使用指南
    if is_first_message:
        base_prompt += (
            "# 记忆管理\n\n"
            "你可以管理用户的长期记忆：\n"
            "1. 用read_user_memories读取现有记忆\n"
            "2. 判断新信息是否重复或冲突\n"
            "3. 去重、合并或更新后用write_user_memories写回\n\n"
            "原则：精炼（一句话）、去重、分类标记、不记录临时信息。\n\n"
        )

    # 注入用户的长期记忆（始终包含）
    try:
        memory_store = get_memory_store()
        memories = memory_store.get_recent_memories(user_id, limit=10)

        if memories:
            base_prompt += "## 已知信息\n\n"
            for mem in memories:
                base_prompt += f"- {mem.content}\n"
    except Exception as e:
        logger.error(f"加载记忆失败: {e}")

    return base_prompt


# ============ 记忆管理命令 ============


async def cmd_memory_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """手动添加记忆 - /memory_add <内容>"""
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "用法: /memory_add <记忆内容>\n\n"
            "示例: /memory_add 我喜欢喝咖啡"
        )
        return

    content = " ".join(context.args)

    try:
        memory_store = get_memory_store()
        memory = memory_store.add_memory(
            user_id=user_id,
            content=content,
            category="other",  # 手动添加默认为 other 分类
            tags=[]
        )

        await update.message.reply_text(
            f"✅ 已添加记忆\n\n"
            f"内容: {memory.content}\n"
            f"ID: {memory.id}"
        )

    except Exception as e:
        logger.error(f"添加记忆失败: {e}")
        await update.message.reply_text(f"❌ 添加记忆失败: {str(e)}")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有记忆 - /memory"""
    user_id = update.effective_user.id

    try:
        memory_store = get_memory_store()
        memories = memory_store.get_user_memories(user_id)

        if not memories:
            await update.message.reply_text("📝 暂无记忆")
            return

        # 按分类组织记忆
        categories = {
            "personal": "👤 个人信息",
            "preference": "⭐ 偏好设置",
            "work": "💼 工作相关",
            "fact": "📌 重要事实",
            "other": "📋 其他"
        }

        response = "📝 你的记忆列表：\n\n"

        for cat_key, cat_name in categories.items():
            cat_memories = [m for m in memories if m.category == cat_key]
            if cat_memories:
                response += f"{cat_name}\n"
                for mem in cat_memories:
                    tags_str = " ".join([f"#{tag}" for tag in mem.tags])
                    response += f"  • {mem.content}\n"
                    if tags_str:
                        response += f"    {tags_str}\n"
                    response += f"    ID: {mem.id}\n"
                response += "\n"

        response += "💡 使用 /memory_delete <ID> 删除指定记忆\n"
        response += "💡 使用 /memory_search <关键词> 搜索记忆\n"
        response += "💡 使用 /memory_clear 清空所有记忆"

        await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"查看记忆失败: {e}")
        await update.message.reply_text(f"❌ 查看记忆失败: {str(e)}")


async def cmd_memory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """搜索记忆 - /memory_search <关键词>"""
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("用法: /memory_search <关键词>")
        return

    keyword = " ".join(context.args)

    try:
        memory_store = get_memory_store()
        memories = memory_store.search_memories(user_id, keyword=keyword)

        if not memories:
            await update.message.reply_text(f"🔍 未找到包含 '{keyword}' 的记忆")
            return

        response = f"🔍 搜索结果（关键词: {keyword}）：\n\n"
        for mem in memories:
            tags_str = " ".join([f"#{tag}" for tag in mem.tags])
            response += f"• {mem.content}\n"
            if tags_str:
                response += f"  {tags_str}\n"
            response += f"  ID: {mem.id}\n\n"

        await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        await update.message.reply_text(f"❌ 搜索记忆失败: {str(e)}")


async def cmd_memory_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除指定记忆 - /memory_delete <ID>"""
    if not context.args:
        await update.message.reply_text("用法: /memory_delete <记忆ID>")
        return

    memory_id = context.args[0]

    try:
        memory_store = get_memory_store()
        success = memory_store.delete_memory(memory_id)

        if success:
            await update.message.reply_text(f"✅ 已删除记忆: {memory_id}")
        else:
            await update.message.reply_text(f"❌ 未找到记忆: {memory_id}")

    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        await update.message.reply_text(f"❌ 删除记忆失败: {str(e)}")


async def cmd_memory_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空所有记忆 - /memory_clear"""
    user_id = update.effective_user.id

    try:
        memory_store = get_memory_store()
        count = memory_store.clear_user_memories(user_id)

        if count > 0:
            await update.message.reply_text(f"✅ 已清空 {count} 条记忆")
        else:
            await update.message.reply_text("📝 暂无记忆")

    except Exception as e:
        logger.error(f"清空记忆失败: {e}")
        await update.message.reply_text(f"❌ 清空记忆失败: {str(e)}")


async def cmd_tool_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看工具使用统计 - /tool_stats"""
    try:
        summary = get_tool_usage_summary()
        await update.message.reply_text(f"📊 {summary}")
    except Exception as e:
        logger.error(f"获取工具统计失败: {e}")
        await update.message.reply_text(f"❌ 获取统计失败: {str(e)}")
