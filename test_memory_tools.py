"""测试记忆工具的 tool use 功能"""

import asyncio
import json
from bot.assistant.memory import get_memory_store

async def test_memory_tools():
    """测试记忆读写工具"""

    memory_store = get_memory_store()
    test_user_id = 999999  # 测试用户 ID

    print("=== 测试记忆工具 ===\n")

    # 1. 清空测试用户的记忆
    print("1. 清空测试用户记忆...")
    memory_store.clear_user_memories(test_user_id)

    # 2. 添加一些测试记忆
    print("2. 添加测试记忆...")
    memory_store.add_memory(
        user_id=test_user_id,
        content="用户名叫张三",
        category="personal",
        tags=["姓名"]
    )
    memory_store.add_memory(
        user_id=test_user_id,
        content="职业是软件工程师",
        category="work",
        tags=["职业"]
    )

    # 3. 测试读取记忆（JSON 格式）
    print("\n3. 读取记忆（JSON 格式）:")
    memories_json = memory_store.read_user_memories_json(test_user_id)
    print(memories_json)

    # 4. 测试写入记忆（模拟 AI 去重）
    print("\n4. 模拟 AI 去重并写回...")
    memories_data = json.loads(memories_json)

    # 模拟 AI 发现重复，合并为一条
    from datetime import datetime
    merged_memories = [
        {
            "id": f"user_{test_user_id}_{int(datetime.now().timestamp())}",
            "content": "用户名叫张三，职业是软件工程师",
            "category": "personal",
            "tags": ["姓名", "职业"],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
    ]

    success = memory_store.write_user_memories_json(
        test_user_id,
        json.dumps(merged_memories, ensure_ascii=False)
    )
    print(f"写入结果: {'成功' if success else '失败'}")

    # 5. 验证写入结果
    print("\n5. 验证写入结果:")
    final_memories = memory_store.get_user_memories(test_user_id)
    print(f"记忆数量: {len(final_memories)}")
    for mem in final_memories:
        print(f"  - {mem.content}")
        print(f"    分类: {mem.category}, 标签: {mem.tags}")

    # 6. 清理
    print("\n6. 清理测试数据...")
    memory_store.clear_user_memories(test_user_id)
    print("✅ 测试完成")

if __name__ == "__main__":
    asyncio.run(test_memory_tools())
