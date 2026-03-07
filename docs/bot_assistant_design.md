# 个人助手机器人策划方案（更新版）

## 一、现有基础总结

当前项目已具备：

- 多 Bot 管理框架（`MultiBotManager`）
- 会话隔离模型（`sessions.py`）
- 三个 AI CLI 后端（Kimi / Claude / Codex）
- 语音输入（Whisper）
- 文件收发（`file.py`）
- Shell 执行（`shell.py`）
- Handler 注册机制（`register_handlers`，支持 `include_admin` 开关）

这是一个极好的基础。个人助手机器人可以**完全复用**这套多 Bot 框架，作为一个新的"助手 Bot"类型叠加进来。

---

## 二、可以做什么（功能版图）

按优先级和实用性分层：

### 第一层：核心对话与记忆（最高价值）

| 功能 | 说明 |
|---|---|
| **长期记忆** | 持久化存储对话摘要/事实到本地 JSON/SQLite，每次对话注入上下文 |
| **直接 AI 对话** | 不走 CLI，直接调用 Claude/OpenAI API，响应更快、可流式输出 |
| **个性化 System Prompt** | 用户可自定义助手人格、偏好、常用背景信息 |
| **对话历史搜索** | `/search <关键词>` 搜索历史对话内容 |

### 第二层：信息与效率工具

| 功能 | 说明 |
|---|---|
| **网页摘要** | 发送 URL → 抓取正文 → AI 摘要 |
| **每日简报** | 定时推送天气、待办、日历摘要 |
| **备忘录/Todo** | `/memo <内容>` 存储，`/todos` 查看，`/done <id>` 完成 |
| **快速翻译** | `/tr <文本>` 中英互译 |
| **图片理解** | 发送图片 → 多模态 AI 描述/解析 |

### 第三层：系统与工作流自动化

| 功能 | 说明 |
|---|---|
| **定时任务** | `/schedule "每天9点" <命令>` 定时执行或提醒 |
| **文件管理助手** | 问"帮我整理下载目录" → AI 生成 Shell 命令后确认执行 |
| **剪贴板同步** | 本地 hook 监听剪贴板变化，自动发到 Telegram |
| **Git 日报** | 定时查询各仓库 git log，推送当日开发摘要 |

### 第四层：扩展集成（后期）

| 功能 | 说明 |
|---|---|
| **飞书/Notion 集成** | 笔记同步、任务管理联动 |
| **本地知识库 RAG** | 对本地文档做向量检索，回答问题时引用 |
| **多模态输入** | 语音已有，补全图片/文档输入链路 |

---

## 三、怎么实施

### 架构原则：最小侵入，插件式扩展

核心思想：**新增一种 Bot 类型 `assistant`，与现有 `cli` 类型并列**，复用所有基础设施，只在 Handler 层分叉。

```
现有架构                    扩展后
─────────────────────      ───────────────────────────────
BotProfile.cli_type        BotProfile.bot_mode
  kimi / claude / codex      "cli"    → 现有逻辑不变
                             "assistant" → 新增助手逻辑
```

### 文件结构规划

```
bot/
├── handlers/
│   ├── chat.py          # 现有 CLI 对话（不改）
│   ├── assistant.py     # 新增：助手对话 Handler
│   ├── memo.py          # 新增：备忘录命令
│   └── scheduler.py     # 新增：定时任务
├── assistant/
│   ├── __init__.py
│   ├── llm.py           # 直接 API 调用（Claude/OpenAI）
│   ├── memory.py        # 长期记忆存储与检索
│   ├── tools.py         # 工具调用定义（网页抓取、翻译等）
│   └── context.py       # 构建对话上下文（注入记忆）
├── data/
│   ├── memories.json    # 长期记忆持久化
│   └── memos.json       # 备忘录数据
```

---

## 四、增量式更新架构

这是关键。整套方案按以下**6个阶段**交付，每个阶段独立可用、不破坏现有功能：

```
Phase 0 ── 已完成 ──────────────────────────────────────────
  CLI Bridge Bot（当前状态）

Phase 1 ── 基础助手框架 ✅ 已完成 ─────────────────────────────
  目标：让一个 Bot 能以"助手模式"运行，直接调 API 对话
  交付：
  - ✅ BotProfile 增加 bot_mode 字段
  - ✅ bot/assistant/llm.py：封装 Claude API 直接调用
  - ✅ bot/handlers/assistant.py：基础对话 Handler
  - ✅ register_handlers 支持 bot_mode 分支逻辑
  - ✅ 支持自定义 ANTHROPIC_BASE_URL（代理商 API）
  - ✅ 会话历史管理（保留最近 10 条对话）
  - ✅ 完整的测试覆盖
  风险：零，不改现有任何文件逻辑
  详细文档：docs/ASSISTANT_PHASE1.md

Phase 2 ── 长期记忆 ✅ 已完成 ─────────────────────────────
  目标：跨会话记住用户信息
  交付：
  - ✅ bot/assistant/memory.py：记忆 CRUD + 关键词检索
  - ✅ AI Tool Use 驱动的记忆管理（read_user_memories / write_user_memories）
  - ✅ AI 自动去重、合并、更新记忆
  - ✅ /memory /memory_search /memory_delete /memory_clear /memory_add 命令
  - ✅ 记忆注入到对话上下文（最近 10 条）
  - ✅ 精炼、准确、易于人工修改的 JSON 格式
  - ✅ 完整的测试覆盖（19 个测试用例）
  风险：零，纯新增文件
  详细文档：docs/ASSISTANT_PHASE2.md
  实施总结：docs/PHASE2_SUMMARY.md

Phase 3 ── 效率工具集（3-5天）──────────────────────────────
  目标：备忘录、翻译、网页摘要
  交付：
  - bot/handlers/memo.py：/memo /todos /done
  - bot/assistant/tools.py：网页抓取、翻译工具
  - 工具调用集成到 assistant.py
  风险：低

Phase 4 ── 定时与主动推送（3-5天）──────────────────────────
  目标：Bot 能主动发消息
  交付：
  - bot/handlers/scheduler.py：定时任务管理
  - APScheduler 集成（新依赖）
  - /schedule /reminders 命令
  风险：中（需要集成 APScheduler）

Phase 5 ── 本地知识库 RAG（1周）────────────────────────────
  目标：对本地文档提问
  交付：
  - 文档向量化（chromadb/faiss）
  - /index <路径> 建索引
  - 对话时自动检索相关段落
  风险：中（新增重型依赖）

Phase 6 ── 外部服务集成（按需）─────────────────────────────
  目标：飞书、Notion、日历等
  交付：按具体服务单独实现
  风险：视集成难度
```

### 增量架构的关键保障

1. **功能开关**：每个新能力都通过 `.env` 变量控制开关（`ASSISTANT_ENABLED=true`），确保渐进启用
2. **依赖隔离**：新功能的 Python 依赖全部标记为 optional，缺少时优雅降级（同现有 Whisper 的处理方式）
3. **数据隔离**：所有持久化数据存在 `bot/data/` 目录，不干扰现有配置文件
4. **Handler 隔离**：通过 `bot_mode` 字段完全隔离助手逻辑和 CLI 逻辑，老 Bot 实例行为完全不变
5. **测试策略**：每个 Phase 附带对应测试文件，沿用现有 pytest + mock 风格

---

## 五、当前状态与下一步推荐

### Phase 1 完成情况 ✅

Phase 1 已全部完成，实现了基础的个人助手机器人框架：

- ✅ 架构层面：`bot_mode` 字段区分 CLI/助手模式，Handler 注册支持分支逻辑
- ✅ API 调用：`bot/assistant/llm.py` 封装 Claude API，支持官方和代理商 API
- ✅ 对话处理：`bot/handlers/assistant.py` 实现基础对话，保留最近 10 条历史
- ✅ 测试覆盖：`tests/test_assistant.py` 提供完整测试
- ✅ 文档完善：`docs/ASSISTANT_PHASE1.md` 详细说明配置和使用

当前助手 Bot 已可用于日常对话，响应速度快，支持上下文记忆（会话内）。

### 推荐的下一步工作

根据实用性和技术难度，推荐按以下优先级推进：

#### 优先级 1：Phase 2 - 长期记忆（2-3天）

**为什么优先**：这是助手 Bot 与普通聊天机器人的核心区别，能显著提升用户体验。

**实现要点**：

1. 创建 `bot/assistant/memory.py`：
   - 记忆数据结构：`{user_id, type, content, timestamp, tags, embedding?}`
   - 存储方式：JSON 文件（简单）或 SQLite（可扩展）
   - 检索方式：关键词匹配（简单）或向量相似度（高级）

2. 对话后自动提炼记忆：
   - 在 `handle_assistant_message` 结束后，异步调用 Claude API
   - Prompt："从以下对话中提取用户的关键信息、偏好、事实"
   - 将提炼结果存入 `bot/data/memories.json`

3. 对话前注入记忆：
   - 在构建 `messages` 前，检索相关记忆（按关键词或时间）
   - 将记忆注入 `system_prompt`："关于用户的已知信息：..."

4. 新增命令：
   - `/memory` - 查看所有记忆
   - `/memory_search <关键词>` - 搜索记忆
   - `/memory_delete <id>` - 删除指定记忆
   - `/memory_clear` - 清空所有记忆

**技术风险**：低，纯新增文件，不影响现有逻辑

**预期效果**：助手能记住用户的姓名、偏好、工作内容等，跨会话提供个性化服务

#### 优先级 2：Phase 3 部分功能 - 快速翻译和备忘录（1-2天）

**为什么优先**：实用性高，实现简单，能快速增加助手的工具属性。

**实现要点**：

1. 快速翻译（`bot/handlers/memo.py`）：
   - `/tr <文本>` - 中英互译
   - 直接调用 Claude API，System Prompt 指定翻译任务
   - 无需额外依赖

2. 备忘录系统（`bot/handlers/memo.py`）：
   - `/memo <内容>` - 添加备忘
   - `/memos` - 查看所有备忘
   - `/memo_done <id>` - 标记完成
   - `/memo_delete <id>` - 删除备忘
   - 数据存储：`bot/data/memos.json`，按 user_id 隔离

**技术风险**：极低，纯命令处理 + JSON 读写

**预期效果**：助手成为轻量级的个人备忘工具

#### 优先级 3：Phase 3 高级功能 - 网页摘要（2-3天）

**为什么延后**：需要额外依赖（网页抓取库），且实用性略低于记忆和备忘。

**实现要点**：

1. 创建 `bot/assistant/tools.py`：
   - `fetch_webpage(url)` - 使用 `requests` + `BeautifulSoup` 抓取正文
   - `summarize_webpage(url)` - 抓取后调用 Claude API 生成摘要

2. 在 `handle_assistant_message` 中检测 URL：
   - 正则匹配消息中的 URL
   - 自动触发网页摘要功能

3. 新增依赖：
   - `pip install requests beautifulsoup4 lxml`
   - 优雅降级：缺少依赖时提示用户安装

**技术风险**：中（网页抓取可能遇到反爬、编码问题）

**预期效果**：发送 URL 即可获得内容摘要

#### 优先级 4：Phase 4 - 定时任务（3-5天）

**为什么延后**：需要引入 APScheduler，架构复杂度较高，且需求不如前三项紧迫。

**实现要点**：

1. 集成 APScheduler：
   - 在 `MultiBotManager` 中初始化 `AsyncIOScheduler`
   - 持久化任务配置到 `bot/data/schedules.json`

2. 新增命令：
   - `/schedule <时间表达式> <命令>` - 创建定时任务
   - `/schedules` - 查看所有任务
   - `/schedule_delete <id>` - 删除任务

3. 支持的任务类型：
   - 定时提醒（发送消息）
   - 定时执行命令（如 `/memo` 等）

**技术风险**：中（需要处理任务持久化、Bot 重启后恢复）

**预期效果**：助手能主动推送提醒和信息

### 推荐实施路径

```
当前 → Phase 2（长期记忆）→ Phase 3 部分（翻译+备忘）→ Phase 3 高级（网页摘要）→ Phase 4（定时任务）
```

**理由**：
- Phase 2 是助手的"灵魂"，优先实现能让助手真正"认识"用户
- Phase 3 部分功能实现简单，能快速增加实用工具
- Phase 3 高级和 Phase 4 可根据实际需求灵活调整顺序

### 技术债务与优化建议

1. **流式输出** ✅ 已完成：使用 `call_claude_api_stream()` 实现流式输出，提升用户体验
2. **Token 计数** ✅ 已完成：每次回复末尾显示 token 使用统计，便于成本控制
3. **错误重试**：API 调用失败时可增加自动重试机制
4. **多模型支持**：当前只支持 Claude，可扩展支持 OpenAI GPT 系列

详细文档：docs/STREAMING_TOKEN_OPTIMIZATION.md

---

## 六、快速开始指南

### 配置助手 Bot

1. 安装依赖：
```bash
pip install anthropic
```

2. 在 `.env` 中添加：
```bash
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
# 可选：使用代理商 API
ANTHROPIC_BASE_URL=
```

3. 在 `managed_bots.json` 中添加：
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

4. 启动：
```bash
python -m bot
```

详细说明见 `docs/ASSISTANT_PHASE1.md`。
