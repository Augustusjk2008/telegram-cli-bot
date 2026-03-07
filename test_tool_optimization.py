"""测试工具优化效果"""

import json
from bot.assistant.llm import MEMORY_TOOLS, get_tool_usage_stats, get_tool_usage_summary, _tool_stats


def test_tool_description_length():
    """测试工具描述长度优化"""
    print("=" * 60)
    print("工具描述长度对比")
    print("=" * 60)

    # 旧版描述（估算）
    old_read_desc = "读取当前用户的所有长期记忆。返回 JSON 格式的记忆列表，每条记忆包含 id、content、category、tags、created_at、updated_at 字段。"
    old_write_desc = "更新当前用户的长期记忆。你需要提供完整的记忆列表（JSON 数组），系统会用它覆盖现有记忆。你应该先调用 read_user_memories 读取现有记忆，然后进行去重、合并、更新操作，最后调用此工具写回。每条记忆必须包含：id（格式 user_{user_id}_{timestamp}）、content（精炼的一句话）、category（personal/preference/work/fact/other）、tags（关键词数组）、created_at（ISO 时间）、updated_at（ISO 时间）。"

    # 新版描述
    new_read_desc = MEMORY_TOOLS[0]["description"]
    new_write_desc = MEMORY_TOOLS[1]["description"]

    print(f"\nread_user_memories:")
    print(f"  旧版: {len(old_read_desc)} 字符")
    print(f"  新版: {len(new_read_desc)} 字符")
    print(f"  节省: {len(old_read_desc) - len(new_read_desc)} 字符 ({(1 - len(new_read_desc)/len(old_read_desc))*100:.1f}%)")

    print(f"\nwrite_user_memories:")
    print(f"  旧版: {len(old_write_desc)} 字符")
    print(f"  新版: {len(new_write_desc)} 字符")
    print(f"  节省: {len(old_write_desc) - len(new_write_desc)} 字符 ({(1 - len(new_write_desc)/len(old_write_desc))*100:.1f}%)")

    total_old = len(old_read_desc) + len(old_write_desc)
    total_new = len(new_read_desc) + len(new_write_desc)
    print(f"\n总计:")
    print(f"  旧版: {total_old} 字符")
    print(f"  新版: {total_new} 字符")
    print(f"  节省: {total_old - total_new} 字符 ({(1 - total_new/total_old)*100:.1f}%)")

    # 估算 token 节省（中文约 1.5-2 字符/token）
    token_saved = (total_old - total_new) / 1.7
    print(f"  估算节省 token: ~{token_saved:.0f} tokens")


def test_system_prompt_optimization():
    """测试 system prompt 优化"""
    print("\n" + "=" * 60)
    print("System Prompt 长度对比")
    print("=" * 60)

    # 旧版 system prompt（估算）
    old_prompt = """你是一个友好、专业的 AI 助手。
你当前使用的模型是 claude-opus-4-6。
用中文回答问题，保持简洁明了。

# 长期记忆管理

你拥有管理用户长期记忆的能力。当用户告诉你值得记住的信息时（如个人信息、偏好、工作内容等），你应该：

1. 使用 `read_user_memories` 工具读取现有记忆
2. 判断新信息是否与现有记忆重复或冲突
3. 进行去重、合并或更新操作
4. 使用 `write_user_memories` 工具写回更新后的记忆

记忆管理原则：
- 每条记忆应该精炼（一句话说清楚）
- 相同或相似的信息只保留一条
- 如果新信息更准确，更新旧记忆的 content 和 updated_at
- 为记忆添加合适的 category 和 tags 便于检索
- 不要记录临时性、一次性的信息

注意：用户也可以通过 /memory 命令查看和管理记忆，所以记忆内容要清晰易懂。"""

    # 新版 system prompt（首次对话）
    new_prompt_first = """你是友好、专业的AI助手，使用claude-opus-4-6模型。用中文简洁回答。

# 记忆管理

你可以管理用户的长期记忆：
1. 用read_user_memories读取现有记忆
2. 判断新信息是否重复或冲突
3. 去重、合并或更新后用write_user_memories写回

原则：精炼（一句话）、去重、分类标记、不记录临时信息。
"""

    # 新版 system prompt（后续对话）
    new_prompt_subsequent = """你是友好、专业的AI助手，使用claude-opus-4-6模型。用中文简洁回答。
"""

    print(f"\n旧版 (每次都传):")
    print(f"  长度: {len(old_prompt)} 字符")
    print(f"  估算 token: ~{len(old_prompt)/1.7:.0f} tokens")

    print(f"\n新版 (首次对话):")
    print(f"  长度: {len(new_prompt_first)} 字符")
    print(f"  估算 token: ~{len(new_prompt_first)/1.7:.0f} tokens")
    print(f"  节省: {len(old_prompt) - len(new_prompt_first)} 字符 ({(1 - len(new_prompt_first)/len(old_prompt))*100:.1f}%)")

    print(f"\n新版 (后续对话):")
    print(f"  长度: {len(new_prompt_subsequent)} 字符")
    print(f"  估算 token: ~{len(new_prompt_subsequent)/1.7:.0f} tokens")
    print(f"  节省: {len(old_prompt) - len(new_prompt_subsequent)} 字符 ({(1 - len(new_prompt_subsequent)/len(old_prompt))*100:.1f}%)")


def test_tool_stats():
    """测试工具使用统计功能"""
    print("\n" + "=" * 60)
    print("工具使用统计功能测试")
    print("=" * 60)

    # 模拟工具使用
    _tool_stats.record_usage("read_user_memories")
    _tool_stats.record_usage("read_user_memories")
    _tool_stats.record_usage("write_user_memories")

    print("\n统计信息:")
    stats = get_tool_usage_stats()
    print(json.dumps(stats, indent=2, default=str, ensure_ascii=False))

    print("\n统计摘要:")
    print(get_tool_usage_summary())


def test_total_optimization():
    """测试总体优化效果"""
    print("\n" + "=" * 60)
    print("总体优化效果估算")
    print("=" * 60)

    # 假设一次对话有 10 轮
    rounds = 10

    # 旧版每轮的 token 消耗（工具描述 + system prompt）
    old_tool_tokens = 300  # 估算
    old_system_tokens = 250  # 估算
    old_total_per_round = old_tool_tokens + old_system_tokens

    # 新版每轮的 token 消耗
    new_tool_tokens = 150  # 估算（减少 50%）
    new_system_first = 120  # 首次
    new_system_subsequent = 30  # 后续

    new_total = new_tool_tokens * rounds + new_system_first + new_system_subsequent * (rounds - 1)
    old_total = old_total_per_round * rounds

    print(f"\n假设 {rounds} 轮对话:")
    print(f"  旧版总消耗: ~{old_total} tokens")
    print(f"  新版总消耗: ~{new_total} tokens")
    print(f"  节省: ~{old_total - new_total} tokens ({(1 - new_total/old_total)*100:.1f}%)")
    print(f"\n如果按 $15/1M input tokens 计算:")
    print(f"  节省成本: ${(old_total - new_total) * 15 / 1_000_000:.6f} per conversation")


if __name__ == "__main__":
    test_tool_description_length()
    test_system_prompt_optimization()
    test_tool_stats()
    test_total_optimization()

    print("\n" + "=" * 60)
    print("✅ 所有测试完成")
    print("=" * 60)
