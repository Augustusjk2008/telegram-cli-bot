# 记忆系统重构：从 Python 去重到 AI Tool Use

## 改动概述

将记忆管理从"Python 提取 + 直接写入"模式改为"AI Tool Use"模式，让 AI 自己负责记忆的去重、合并和更新。

## 改动前的问题

1. **重复记忆**：每次对话都可能提取相同信息，导致记忆重复
2. **无去重逻辑**：`add_memory()` 直接添加，不检查是否已存在
3. **维护成本高**：需要在 Python 层实现复杂的去重/合并逻辑

## 改动后的方案

### 核心思路

AI 通过 tool use 直接操作记忆文件：
- `read_user_memories` - 读取当前用户的所有记忆（JSON 格式）
- `write_user_memories` - 覆盖写入记忆（AI 负责去重/合并）

### 工作流程

1. 用户发送消息
2. AI 回复时，如果发现值得记住的信息：
   - 调用 `read_user_memories` 读取现有记忆
   - 判断是否重复，决定新增/更新/合并
   - 调用 `write_user_memories` 写回
3. 用户仍可通过 `/memory` 命令查看和手动管理

### 优势

- **AI 自主决策**：去重、合并逻辑由 AI 判断，更灵活
- **代码简化**：Python 层只提供读写接口，不需要复杂逻辑
- **符合 Agent 设计模式**：工具调用是主流 AI Agent 架构

## 代码改动

### 1. `bot/assistant/memory.py`

新增两个方法：

```python
def read_user_memories_json(self, user_id: int) -> str:
    """读取用户记忆（JSON 格式，供 AI tool use）"""

def write_user_memories_json(self, user_id: int, memories_json: str) -> bool:
    """写入用户记忆（JSON 格式，供 AI tool use）"""
```

### 2. `bot/assistant/llm.py`

- 定义 `MEMORY_TOOLS` 工具列表
- 修改 `call_claude_api()` 支持 tool use
- 新增 `call_claude_with_memory_tools()` 处理 tool use 循环
- 删除旧的 `extract_memories_from_conversation()` 函数

### 3. `bot/handlers/assistant.py`

- 使用 `call_claude_with_memory_tools()` 替代 `call_claude_api()`
- 删除 `_extract_and_save_memory()` 后台任务
- 更新系统提示词，告诉 AI 如何使用记忆工具

## 用户体验

### 人工操作（保持不变）

- `/memory` - 查看记忆列表
- `/memory_delete <ID>` - 删除指定记忆
- `/memory_search <关键词>` - 搜索记忆
- `/memory_clear` - 清空所有记忆
- 直接编辑 `bot/data/memories.json` 文件

### AI 操作（新增）

AI 在对话中自动：
- 识别值得记住的信息
- 读取现有记忆
- 去重、合并、更新
- 写回记忆文件

## 测试

运行测试脚本验证工具功能：

```bash
python test_memory_tools.py
```

测试覆盖：
- 读取记忆（JSON 格式）
- 写入记忆（模拟 AI 去重）
- 验证去重效果

## ID 格式说明

记忆 ID 格式：`user_{user_id}_{timestamp}`

- `user_id`：用户 Telegram ID
- `timestamp`：Unix 时间戳（秒）

示例：`user_5472815837_1772769686` 表示用户 5472815837 在 2026-03-06 某时刻创建的记忆。

## 注意事项

1. **Tool use 循环限制**：最多 5 次循环，防止无限调用
2. **user_id 强制校验**：写入时强制设置正确的 user_id，防止 AI 错误
3. **向后兼容**：现有记忆文件格式不变，人工管理命令不受影响
