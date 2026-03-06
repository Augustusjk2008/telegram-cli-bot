# 个人助手机器人 - Phase 1 实现

## 概述

Phase 1 实现了基础的个人助手机器人框架，支持通过 Telegram Bot 直接调用 Claude API 进行对话。

## 功能特性

- ✅ 支持 `bot_mode` 字段区分 CLI 模式和助手模式
- ✅ 直接调用 Claude API（不通过 CLI）
- ✅ 会话历史管理（保留最近 10 条对话）
- ✅ 优雅的错误处理和用户提示
- ✅ 完整的测试覆盖

## 配置步骤

### 1. 安装依赖

```bash
pip install anthropic
```

### 2. 设置环境变量

在 `.env` 文件中添加：

```bash
# Claude API Key（用于助手模式）
ANTHROPIC_API_KEY=your_api_key_here

# 可选：指定 Claude 模型
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

### 3. 配置助手 Bot

在 `managed_bots.json` 中添加助手 Bot 配置：

```json
{
  "alias": "assistant1",
  "token": "YOUR_TELEGRAM_BOT_TOKEN",
  "cli_type": "kimi",
  "cli_path": "kimi",
  "working_dir": "C:\\Users\\YourName\\workspace",
  "enabled": true,
  "bot_mode": "assistant"
}
```

**注意**：
- `bot_mode` 必须设置为 `"assistant"`
- `cli_type` 和 `cli_path` 字段在助手模式下不会被使用，但仍需提供（保持向后兼容）
- 从 @BotFather 获取新的 Telegram Bot Token

### 4. 启动 Bot

```bash
python -m bot
```

## 使用方法

### 基本对话

直接向助手 Bot 发送消息即可：

```
用户: 你好
助手: 你好！我是你的个人助手，有什么可以帮助你的吗？

用户: 今天天气怎么样？
助手: 抱歉，我目前无法获取实时天气信息...
```

### 可用命令

助手模式支持以下命令：

- `/start` - 显示帮助信息
- `/reset` - 重置当前会话
- `/history` - 查看对话历史

### 管理命令（仅主 Bot）

如果助手 Bot 是主 Bot，还支持：

- `/bot_list` - 查看所有 Bot 状态
- `/bot_add` - 添加新的 Bot
- `/restart` - 重启程序
- 等等...

## 架构说明

### 文件结构

```
bot/
├── assistant/
│   ├── __init__.py
│   └── llm.py              # Claude API 调用封装
├── handlers/
│   ├── __init__.py         # Handler 注册（支持 bot_mode 分支）
│   └── assistant.py        # 助手模式消息处理器
└── models.py               # BotProfile 增加 bot_mode 字段
```

### 工作流程

1. 用户发送消息到助手 Bot
2. `handle_assistant_message` 接收消息
3. 从会话中获取最近 10 条对话历史
4. 调用 `call_claude_api` 发送到 Claude API
5. 将 AI 回复保存到会话历史
6. 发送回复给用户

### bot_mode 分支逻辑

在 `register_handlers` 中：

```python
bot_mode = application.bot_data.get("bot_mode", "cli")

if bot_mode == "assistant":
    _register_assistant_handlers(application, include_admin)
else:
    _register_cli_handlers(application, include_admin)
```

## 测试

运行助手模式测试：

```bash
# 运行所有助手测试
python -m pytest tests/test_assistant.py -v

# 运行所有测试（确保无回归）
python -m pytest tests/ -v
```

## 与 CLI 模式的区别

| 特性 | CLI 模式 | 助手模式 |
|------|---------|---------|
| 消息处理 | 通过 CLI 子进程 | 直接调用 API |
| 响应速度 | 较慢（需启动进程） | 快速 |
| 会话管理 | CLI 自带 | 手动管理历史 |
| 文件操作 | 支持（/cd, /ls, /exec） | 不支持 |
| 工作目录 | 需要 | 不需要 |
| CLI 可执行文件 | 需要 | 不需要 |

## 后续 Phase 计划

- **Phase 2**: 长期记忆（跨会话记住用户信息）
- **Phase 3**: 效率工具集（备忘录、翻译、网页摘要）
- **Phase 4**: 定时任务与主动推送
- **Phase 5**: 本地知识库 RAG
- **Phase 6**: 外部服务集成（飞书、Notion 等）

## 故障排查

### 问题：提示 "anthropic SDK 未安装"

**解决**：
```bash
pip install anthropic
```

### 问题：提示 "未设置 ANTHROPIC_API_KEY"

**解决**：在 `.env` 文件中添加：
```bash
ANTHROPIC_API_KEY=sk-ant-...
```

### 问题：Bot 无法启动

**检查**：
1. `managed_bots.json` 中的 token 是否正确
2. `bot_mode` 是否设置为 `"assistant"`
3. 查看日志输出中的错误信息

## 开发说明

### 添加新功能

1. 在 `bot/assistant/` 目录下创建新模块
2. 在 `bot/handlers/assistant.py` 中集成
3. 在 `tests/test_assistant.py` 中添加测试

### 修改 System Prompt

编辑 `bot/handlers/assistant.py` 中的 `system_prompt` 参数：

```python
response = await call_claude_api(
    messages=messages,
    system_prompt="你的自定义提示词..."
)
```

## 贡献

欢迎提交 Issue 和 Pull Request！
