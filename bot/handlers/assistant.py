"""助手模式的消息处理器"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot.assistant.llm import call_claude_api, ANTHROPIC_AVAILABLE
from bot.context_helpers import get_current_session

logger = logging.getLogger(__name__)


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
        # 调用 Claude API
        response = await call_claude_api(
            messages=messages,
            system_prompt="你是一个友好、专业的个人助手。用中文回答问题，保持简洁明了。"
        )

        # 删除状态消息
        try:
            await status_msg.delete()
        except Exception:
            pass

        # 保存到历史
        session.add_to_history("user", user_text)
        session.add_to_history("assistant", response)

        # 发送回复
        await update.message.reply_text(response)

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
