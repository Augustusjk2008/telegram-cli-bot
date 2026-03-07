"""直接调用 LLM API（Claude/OpenAI）"""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

from bot.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_BASE_URL

logger = logging.getLogger(__name__)

# 尝试导入 anthropic SDK
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic SDK 未安装，助手模式将不可用")


# ============ Tool Definitions ============

MEMORY_TOOLS = [
    {
        "name": "read_user_memories",
        "description": "读取用户长期记忆（JSON格式）",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "write_user_memories",
        "description": "覆盖更新用户记忆。需提供完整记忆列表，每条包含id/content/category/tags/created_at/updated_at",
        "input_schema": {
            "type": "object",
            "properties": {
                "memories": {
                    "type": "array",
                    "description": "完整记忆列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "category": {"type": "string", "enum": ["personal", "preference", "work", "fact", "other"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "created_at": {"type": "string"},
                            "updated_at": {"type": "string"}
                        },
                        "required": ["id", "content", "category", "tags", "created_at", "updated_at"]
                    }
                }
            },
            "required": ["memories"]
        }
    }
]


# ============ Tool Usage Statistics ============

class ToolUsageStats:
    """工具使用统计"""

    def __init__(self):
        self._stats = {}  # {tool_name: {"count": int, "last_used": datetime}}

    def record_usage(self, tool_name: str):
        """记录工具使用"""
        if tool_name not in self._stats:
            self._stats[tool_name] = {"count": 0, "last_used": None}

        self._stats[tool_name]["count"] += 1
        self._stats[tool_name]["last_used"] = datetime.now()

        logger.info(f"工具使用统计: {tool_name} 已使用 {self._stats[tool_name]['count']} 次")

    def get_stats(self, tool_name: str = None) -> Dict[str, Any]:
        """获取统计信息"""
        if tool_name:
            return self._stats.get(tool_name, {"count": 0, "last_used": None})
        return self._stats.copy()

    def get_summary(self) -> str:
        """获取统计摘要（用于日志）"""
        if not self._stats:
            return "暂无工具使用记录"

        lines = ["工具使用统计:"]
        for tool_name, data in sorted(self._stats.items(), key=lambda x: x[1]["count"], reverse=True):
            last_used = data["last_used"].strftime("%Y-%m-%d %H:%M:%S") if data["last_used"] else "从未使用"
            lines.append(f"  - {tool_name}: {data['count']} 次 (最后使用: {last_used})")

        return "\n".join(lines)


# 全局统计实例
_tool_stats = ToolUsageStats()


def get_tool_usage_stats(tool_name: str = None) -> Dict[str, Any]:
    """获取工具使用统计

    Args:
        tool_name: 工具名称，如果为 None 则返回所有工具的统计

    Returns:
        统计信息字典
    """
    return _tool_stats.get_stats(tool_name)


def get_tool_usage_summary() -> str:
    """获取工具使用统计摘要（用于日志或调试）

    Returns:
        统计摘要字符串
    """
    return _tool_stats.get_summary()


async def call_claude_api(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """调用 Claude API（非流式）

    Args:
        messages: 对话历史 [{"role": "user", "content": "..."}, ...]
        system_prompt: 系统提示词
        max_tokens: 最大生成 token 数
        tools: 工具定义列表（用于 tool use）

    Returns:
        API 响应，包含 content 和可能的 tool_use
        格式: {
            "text": "文本回复",
            "tool_uses": [{"id": "...", "name": "...", "input": {...}}],
            "usage": {"input_tokens": 100, "output_tokens": 50}
        }
    """
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic SDK 未安装")

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("未设置 ANTHROPIC_API_KEY 环境变量")

    # 构建 client 参数
    client_kwargs = {"api_key": ANTHROPIC_API_KEY}

    # 如果设置了自定义 base_url（代理商），则使用
    if ANTHROPIC_BASE_URL:
        client_kwargs["base_url"] = ANTHROPIC_BASE_URL
        logger.info(f"使用自定义 API 地址: {ANTHROPIC_BASE_URL}")

    client = anthropic.Anthropic(**client_kwargs)

    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    if system_prompt:
        kwargs["system"] = system_prompt

    if tools:
        kwargs["tools"] = tools

    response = client.messages.create(**kwargs)

    # 解析响应
    result = {
        "text": "",
        "tool_uses": [],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens
        }
    }

    for block in response.content:
        if block.type == "text":
            result["text"] += block.text
        elif block.type == "tool_use":
            result["tool_uses"].append({
                "id": block.id,
                "name": block.name,
                "input": block.input
            })

    return result


async def call_claude_api_stream(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    tools: Optional[List[Dict[str, Any]]] = None,
):
    """调用 Claude API（流式）

    Args:
        messages: 对话历史
        system_prompt: 系统提示词
        max_tokens: 最大生成 token 数
        tools: 工具定义列表

    Yields:
        流式事件，格式:
        - {"type": "text", "text": "..."}
        - {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
        - {"type": "usage", "input_tokens": 100, "output_tokens": 50}
    """
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic SDK 未安装")

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("未设置 ANTHROPIC_API_KEY 环境变量")

    # 构建 client 参数
    client_kwargs = {"api_key": ANTHROPIC_API_KEY}

    if ANTHROPIC_BASE_URL:
        client_kwargs["base_url"] = ANTHROPIC_BASE_URL
        logger.info(f"使用自定义 API 地址: {ANTHROPIC_BASE_URL}")

    client = anthropic.Anthropic(**client_kwargs)

    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    if system_prompt:
        kwargs["system"] = system_prompt

    if tools:
        kwargs["tools"] = tools

    # 流式调用
    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            if event.type == "content_block_start":
                if event.content_block.type == "text":
                    # 文本块开始
                    pass
                elif event.content_block.type == "tool_use":
                    # 工具调用块开始
                    yield {
                        "type": "tool_use_start",
                        "id": event.content_block.id,
                        "name": event.content_block.name
                    }

            elif event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    # 文本增量
                    yield {
                        "type": "text",
                        "text": event.delta.text
                    }
                elif event.delta.type == "input_json_delta":
                    # 工具输入增量（暂不处理）
                    pass

            elif event.type == "content_block_stop":
                # 内容块结束
                pass

            elif event.type == "message_delta":
                # 消息增量（包含 usage）
                if hasattr(event, "usage") and event.usage:
                    yield {
                        "type": "usage",
                        "output_tokens": event.usage.output_tokens
                    }

            elif event.type == "message_stop":
                # 消息结束
                pass

        # 获取最终消息（包含完整的 tool_use 和 usage）
        final_message = stream.get_final_message()

        # 提取完整的 tool_use
        for block in final_message.content:
            if block.type == "tool_use":
                yield {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                }

        # 提取完整的 usage
        yield {
            "type": "usage",
            "input_tokens": final_message.usage.input_tokens,
            "output_tokens": final_message.usage.output_tokens
        }


async def call_claude_with_memory_tools_stream(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    user_id: int = None,
    max_tokens: int = 4096,
):
    """调用 Claude API 并支持记忆工具（流式版本）

    自动处理 tool use 循环，直到 AI 返回最终文本回复

    Args:
        messages: 对话历史
        system_prompt: 系统提示词
        user_id: 用户 ID（用于记忆工具）
        max_tokens: 最大生成 token 数

    Yields:
        流式事件:
        - {"type": "text", "text": "..."}
        - {"type": "usage", "input_tokens": 100, "output_tokens": 50}
    """
    from bot.assistant.memory import get_memory_store
    import json

    memory_store = get_memory_store()
    current_messages = messages.copy()

    total_input_tokens = 0
    total_output_tokens = 0

    # 最多循环 5 次（防止无限循环）
    for iteration in range(5):
        if iteration == 0:
            # 第一次调用使用流式输出
            text_buffer = ""
            tool_uses = []
            usage_data = {}

            async for event in call_claude_api_stream(
                messages=current_messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                tools=MEMORY_TOOLS
            ):
                if event["type"] == "text":
                    text_buffer += event["text"]
                    yield event  # 流式输出文本
                elif event["type"] == "tool_use":
                    tool_uses.append(event)
                elif event["type"] == "usage":
                    usage_data.update(event)

            # 累计 token 使用
            total_input_tokens += usage_data.get("input_tokens", 0)
            total_output_tokens += usage_data.get("output_tokens", 0)

            # 如果没有 tool use，返回最终 usage
            if not tool_uses:
                yield {
                    "type": "usage",
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens
                }
                return

            # 处理 tool use（后续轮次使用非流式）
            response = {
                "text": text_buffer,
                "tool_uses": tool_uses,
                "usage": usage_data
            }

        else:
            # 后续轮次使用非流式（tool use 场景）
            response = await call_claude_api(
                messages=current_messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                tools=MEMORY_TOOLS
            )

            # 累计 token 使用
            total_input_tokens += response["usage"]["input_tokens"]
            total_output_tokens += response["usage"]["output_tokens"]

            # 如果没有 tool use，返回文本和 usage
            if not response["tool_uses"]:
                if response["text"]:
                    yield {"type": "text", "text": response["text"]}
                yield {
                    "type": "usage",
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens
                }
                return

        # 处理 tool use
        tool_results = []
        for tool_use in response["tool_uses"]:
            tool_name = tool_use["name"]
            tool_input = tool_use["input"]
            tool_id = tool_use["id"]

            logger.info(f"AI 调用工具: {tool_name}, input={tool_input}")

            # 记录工具使用统计
            _tool_stats.record_usage(tool_name)

            if tool_name == "read_user_memories":
                # 读取记忆
                result_content = memory_store.read_user_memories_json(user_id)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_content
                })

            elif tool_name == "write_user_memories":
                # 写入记忆
                memories_data = tool_input.get("memories", [])
                memories_json = json.dumps(memories_data, ensure_ascii=False)
                success = memory_store.write_user_memories_json(user_id, memories_json)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps({"success": success}, ensure_ascii=False)
                })

        # 构建下一轮消息（添加 assistant 的 tool use 和 tool result）
        assistant_content = []
        if response["text"]:
            assistant_content.append({"type": "text", "text": response["text"]})
        for tool_use in response["tool_uses"]:
            assistant_content.append({
                "type": "tool_use",
                "id": tool_use["id"],
                "name": tool_use["name"],
                "input": tool_use["input"]
            })

        current_messages.append({
            "role": "assistant",
            "content": assistant_content
        })

        current_messages.append({
            "role": "user",
            "content": tool_results
        })

    # 如果循环结束还没返回
    logger.warning("Tool use 循环达到最大次数")
    yield {"type": "text", "text": "抱歉，处理超时了"}
    yield {
        "type": "usage",
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens
    }


async def call_claude_with_memory_tools(
    messages: List[Dict[str, str]],
    system_prompt: Optional[str] = None,
    user_id: int = None,
    max_tokens: int = 4096,
) -> str:
    """调用 Claude API 并支持记忆工具（非流式版本，用于向后兼容）

    自动处理 tool use 循环，直到 AI 返回最终文本回复

    Args:
        messages: 对话历史
        system_prompt: 系统提示词
        user_id: 用户 ID（用于记忆工具）
        max_tokens: 最大生成 token 数

    Returns:
        AI 最终回复文本
    """
    from bot.assistant.memory import get_memory_store
    import json

    memory_store = get_memory_store()
    current_messages = messages.copy()

    # 最多循环 5 次（防止无限循环）
    for _ in range(5):
        response = await call_claude_api(
            messages=current_messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            tools=MEMORY_TOOLS
        )

        # 如果没有 tool use，直接返回文本
        if not response["tool_uses"]:
            return response["text"]

        # 处理 tool use
        tool_results = []
        for tool_use in response["tool_uses"]:
            tool_name = tool_use["name"]
            tool_input = tool_use["input"]
            tool_id = tool_use["id"]

            logger.info(f"AI 调用工具: {tool_name}, input={tool_input}")

            # 记录工具使用统计
            _tool_stats.record_usage(tool_name)

            if tool_name == "read_user_memories":
                # 读取记忆
                result_content = memory_store.read_user_memories_json(user_id)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_content
                })

            elif tool_name == "write_user_memories":
                # 写入记忆
                memories_data = tool_input.get("memories", [])
                memories_json = json.dumps(memories_data, ensure_ascii=False)
                success = memory_store.write_user_memories_json(user_id, memories_json)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps({"success": success}, ensure_ascii=False)
                })

        # 构建下一轮消息（添加 assistant 的 tool use 和 tool result）
        assistant_content = []
        if response["text"]:
            assistant_content.append({"type": "text", "text": response["text"]})
        for tool_use in response["tool_uses"]:
            assistant_content.append({
                "type": "tool_use",
                "id": tool_use["id"],
                "name": tool_use["name"],
                "input": tool_use["input"]
            })

        current_messages.append({
            "role": "assistant",
            "content": assistant_content
        })

        current_messages.append({
            "role": "user",
            "content": tool_results
        })

    # 如果循环结束还没返回，返回最后一次的文本
    logger.warning("Tool use 循环达到最大次数")
    return response.get("text", "抱歉，处理超时了")

