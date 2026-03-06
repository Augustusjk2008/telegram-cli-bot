"""直接调用 LLM API（Claude/OpenAI）"""

import logging
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 尝试导入 anthropic SDK
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic SDK 未安装，助手模式将不可用")


async def call_claude_api(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """调用 Claude API

    Args:
        messages: 对话历史 [{"role": "user", "content": "..."}, ...]
        system_prompt: 系统提示词
        max_tokens: 最大生成 token 数

    Returns:
        AI 回复内容
    """
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic SDK 未安装")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 ANTHROPIC_API_KEY 环境变量")

    client = anthropic.Anthropic(api_key=api_key)

    kwargs = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        "max_tokens": max_tokens,
        "messages": messages,
    }

    if system_prompt:
        kwargs["system"] = system_prompt

    response = client.messages.create(**kwargs)

    # 提取文本内容
    content = ""
    for block in response.content:
        if block.type == "text":
            content += block.text

    return content
