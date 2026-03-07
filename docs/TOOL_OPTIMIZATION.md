# 工具选择与Token优化实现总结

## 优化目标

为助手bot添加工具选择机制和token优化，提升性能和降低成本。

## 实现的优化

### 1. 工具描述优化（减少 75.4% 字符）

**优化前：**
```python
"description": "读取当前用户的所有长期记忆。返回 JSON 格式的记忆列表，每条记忆包含 id、content、category、tags、created_at、updated_at 字段。"
```

**优化后：**
```python
"description": "读取用户长期记忆（JSON格式）"
```

**效果：**
- `read_user_memories`: 87 → 16 字符（节省 81.6%）
- `write_user_memories`: 259 → 69 字符（节省 73.4%）
- 总计节省约 **154 tokens**

### 2. System Prompt 优化（减少 57.6%-89.8%）

**策略：** 首次对话传详细指南，后续对话只传精简版

**优化前（每次都传）：**
```python
"""你是一个友好、专业的 AI 助手。
你当前使用的模型是 claude-opus-4-6。
用中文回答问题，保持简洁明了。

# 长期记忆管理

你拥有管理用户长期记忆的能力。当用户告诉你值得记住的信息时...
（共 410 字符，约 241 tokens）
"""
```

**优化后（首次对话）：**
```python
"""你是友好、专业的AI助手，使用claude-opus-4-6模型。用中文简洁回答。

# 记忆管理

你可以管理用户的长期记忆：
1. 用read_user_memories读取现有记忆
2. 判断新信息是否重复或冲突
3. 去重、合并或更新后用write_user_memories写回

原则：精炼（一句话）、去重、分类标记、不记录临时信息。
（共 174 字符，约 102 tokens）
"""
```

**优化后（后续对话）：**
```python
"""你是友好、专业的AI助手，使用claude-opus-4-6模型。用中文简洁回答。
（共 42 字符，约 25 tokens）
"""
```

**效果：**
- 首次对话节省 57.6%
- 后续对话节省 89.8%

### 3. 工具使用统计

新增 `ToolUsageStats` 类，自动记录每个工具的使用情况：

```python
class ToolUsageStats:
    """工具使用统计"""

    def record_usage(self, tool_name: str):
        """记录工具使用"""
        # 自动记录使用次数和时间

    def get_stats(self, tool_name: str = None) -> Dict[str, Any]:
        """获取统计信息"""
        # 返回统计数据

    def get_summary(self) -> str:
        """获取统计摘要"""
        # 返回可读的摘要文本
```

**使用方式：**
- 自动统计：每次工具调用时自动记录
- 查看统计：`/tool_stats` 命令
- 编程访问：`get_tool_usage_stats()` 和 `get_tool_usage_summary()`

## 总体优化效果

### 假设 10 轮对话的 Token 消耗对比

| 项目 | 旧版 | 新版 | 节省 |
|------|------|------|------|
| 工具描述（每轮） | ~300 tokens | ~150 tokens | 50% |
| System Prompt（首次） | ~250 tokens | ~120 tokens | 52% |
| System Prompt（后续） | ~250 tokens | ~30 tokens | 88% |
| **10轮总计** | **~5500 tokens** | **~1890 tokens** | **65.6%** |

### 成本节省

按 Claude Opus 4.6 定价（$15/1M input tokens）：
- 每次对话节省约 **3610 tokens**
- 成本节省约 **$0.054** per conversation
- 如果每天 100 次对话，年节省约 **$1,971**

## 代码变更

### 修改的文件

1. **bot/assistant/llm.py**
   - 优化 `MEMORY_TOOLS` 描述
   - 新增 `ToolUsageStats` 类
   - 新增 `get_tool_usage_stats()` 和 `get_tool_usage_summary()` 函数
   - 在工具调用处添加统计记录

2. **bot/handlers/assistant.py**
   - 优化 `_build_system_prompt_with_memory()` 函数
   - 添加 `is_first_message` 参数，区分首次和后续对话
   - 新增 `cmd_tool_stats()` 命令处理器

3. **bot/handlers/__init__.py**
   - 导入 `cmd_tool_stats`
   - 注册 `/tool_stats` 命令

### 新增的文件

- **test_tool_optimization.py**: 优化效果测试脚本

## 使用指南

### 用户命令

```bash
# 查看工具使用统计
/tool_stats

# 查看记忆（已有）
/memory

# 添加记忆（已有）
/memory_add <内容>

# 搜索记忆（已有）
/memory_search <关键词>

# 删除记忆（已有）
/memory_delete <ID>

# 清空记忆（已有）
/memory_clear
```

### 编程接口

```python
from bot.assistant.llm import get_tool_usage_stats, get_tool_usage_summary

# 获取所有工具的统计
all_stats = get_tool_usage_stats()

# 获取特定工具的统计
read_stats = get_tool_usage_stats("read_user_memories")

# 获取可读的摘要
summary = get_tool_usage_summary()
print(summary)
```

## 未来扩展建议

### 当工具数量增长时的策略

#### Phase 1: 工具数量 < 10（当前阶段）✅
- **策略**: 全量传输 + 简化描述
- **已实现**: 描述优化、System Prompt优化、统计功能

#### Phase 2: 工具数量 10-30
- **策略**: 工具分组 + 上下文感知
- **实现方式**:
  ```python
  TOOL_GROUPS = {
      "memory": ["read_user_memories", "write_user_memories"],
      "file": ["read_file", "write_file", "list_files"],
      "web": ["search_web", "fetch_url"],
      "system": ["execute_command", "get_system_info"]
  }

  def select_tool_groups(user_message: str) -> List[str]:
      """根据用户消息选择相关工具组"""
      groups = []
      if any(kw in user_message for kw in ["记住", "记忆", "忘记"]):
          groups.append("memory")
      if any(kw in user_message for kw in ["文件", "读取", "写入"]):
          groups.append("file")
      return groups or ["memory"]  # 默认返回memory组
  ```

#### Phase 3: 工具数量 > 30
- **策略**: 向量检索 + 两阶段选择
- **实现方式**:
  ```python
  from sentence_transformers import SentenceTransformer

  class ToolRetriever:
      def __init__(self):
          self.model = SentenceTransformer('all-MiniLM-L6-v2')
          self.tool_embeddings = {}

      def retrieve_tools(self, query: str, top_k: int = 5):
          """检索最相关的k个工具"""
          query_emb = self.model.encode(query)
          # 计算相似度并返回top-k
  ```

## 测试验证

运行测试脚本验证优化效果：

```bash
python test_tool_optimization.py
```

测试覆盖：
- ✅ 工具描述长度对比
- ✅ System Prompt 长度对比
- ✅ 工具使用统计功能
- ✅ 总体优化效果估算

## 最佳实践

### 工具描述编写原则

1. **精简但完整**: 去掉冗余词汇，保留核心信息
2. **避免重复**: 不要在描述中重复 schema 中的信息
3. **使用简称**: "JSON格式" 而不是 "JSON 格式的记忆列表"
4. **省略显而易见的内容**: 如"当前用户"可以省略

### System Prompt 优化原则

1. **分层传递**: 首次详细，后续精简
2. **去除格式化**: 减少换行、标题符号
3. **合并句子**: 用逗号代替句号连接相关内容
4. **动态注入**: 只在需要时注入记忆内容

### 统计数据使用

1. **监控工具使用频率**: 识别高频工具
2. **优化工具顺序**: 将高频工具放在前面
3. **发现未使用工具**: 考虑移除或改进描述
4. **A/B测试**: 对比不同描述的使用率

## 总结

通过三个方面的优化：
1. **工具描述优化**: 减少 75.4% 字符
2. **System Prompt 优化**: 减少 57.6%-89.8%
3. **工具使用统计**: 为未来优化提供数据支持

在 10 轮对话中可节省约 **65.6% 的 input tokens**，显著降低 API 成本。

当前实现适用于工具数量 < 10 的场景，未来可根据工具数量增长采用分组或检索策略。
