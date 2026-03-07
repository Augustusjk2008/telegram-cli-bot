"""测试记忆提取功能"""
import asyncio
import logging
from bot.assistant.llm import extract_memories_from_conversation
from bot.assistant.memory import get_memory_store

# 设置日志
logging.basicConfig(level=logging.DEBUG)

async def test_extraction():
    """测试记忆提取"""

    # 测试用例 1: 明确的个人信息
    print("\n=== 测试 1: 明确的个人信息 ===")
    user_msg = "我叫张三，是一名软件工程师"
    assistant_msg = "你好张三！很高兴认识你。作为软件工程师，你平时主要使用什么编程语言呢？"

    result = await extract_memories_from_conversation(user_msg, assistant_msg)
    print(f"提取结果: {result}")

    # 测试用例 2: 偏好信息
    print("\n=== 测试 2: 偏好信息 ===")
    user_msg = "我喜欢喝咖啡，不喜欢茶"
    assistant_msg = "明白了，你更喜欢咖啡。咖啡确实能提神醒脑。"

    result = await extract_memories_from_conversation(user_msg, assistant_msg)
    print(f"提取结果: {result}")

    # 测试用例 3: 普通闲聊（不应该记住）
    print("\n=== 测试 3: 普通闲聊 ===")
    user_msg = "今天天气怎么样？"
    assistant_msg = "抱歉，我无法获取实时天气信息。建议你查看天气预报应用。"

    result = await extract_memories_from_conversation(user_msg, assistant_msg)
    print(f"提取结果: {result}")

    # 测试用例 4: 明确要求记住
    print("\n=== 测试 4: 明确要求记住 ===")
    user_msg = "请记住，我的生日是 3 月 15 日"
    assistant_msg = "好的，我会记住你的生日是 3 月 15 日。"

    result = await extract_memories_from_conversation(user_msg, assistant_msg)
    print(f"提取结果: {result}")

    # 如果提取成功，测试保存
    if result:
        print("\n=== 测试保存记忆 ===")
        memory_store = get_memory_store()
        memory = memory_store.add_memory(
            user_id=999,  # 测试用户 ID
            content=result["content"],
            category=result["category"],
            tags=result["tags"]
        )
        print(f"保存成功: {memory}")

        # 读取记忆
        memories = memory_store.get_user_memories(999)
        print(f"用户 999 的记忆: {memories}")

if __name__ == "__main__":
    asyncio.run(test_extraction())
