\# 个人助手机器人策划方案



\## 一、现有基础总结



当前项目已具备：

\- 多 Bot 管理框架（`MultiBotManager`）

\- 会话隔离模型（`sessions.py`）

\- 三个 AI CLI 后端（Kimi / Claude / Codex）

\- 语音输入（Whisper）

\- 文件收发（`file.py`）

\- Shell 执行（`shell.py`）

\- Handler 注册机制（`register\_handlers`，支持 `include\_admin` 开关）



这是一个极好的基础。个人助手机器人可以\*\*完全复用\*\*这套多 Bot 框架，作为一个新的"助手 Bot"类型叠加进来。



---



\## 二、可以做什么（功能版图）



按优先级和实用性分层：



\### 第一层：核心对话与记忆（最高价值）

| 功能 | 说明 |

|---|---|

| \*\*长期记忆\*\* | 持久化存储对话摘要/事实到本地 JSON/SQLite，每次对话注入上下文 |

| \*\*直接 AI 对话\*\* | 不走 CLI，直接调用 Claude/OpenAI API，响应更快、可流式输出 |

| \*\*个性化 System Prompt\*\* | 用户可自定义助手人格、偏好、常用背景信息 |

| \*\*对话历史搜索\*\* | `/search <关键词>` 搜索历史对话内容 |



\### 第二层：信息与效率工具

| 功能 | 说明 |

|---|---|

| \*\*网页摘要\*\* | 发送 URL → 抓取正文 → AI 摘要 |

| \*\*每日简报\*\* | 定时推送天气、待办、日历摘要 |

| \*\*备忘录/Todo\*\* | `/memo <内容>` 存储，`/todos` 查看，`/done <id>` 完成 |

| \*\*快速翻译\*\* | `/tr <文本>` 中英互译 |

| \*\*图片理解\*\* | 发送图片 → 多模态 AI 描述/解析 |



\### 第三层：系统与工作流自动化

| 功能 | 说明 |

|---|---|

| \*\*定时任务\*\* | `/schedule "每天9点" <命令>` 定时执行或提醒 |

| \*\*文件管理助手\*\* | 问"帮我整理下载目录" → AI 生成 Shell 命令后确认执行 |

| \*\*剪贴板同步\*\* | 本地 hook 监听剪贴板变化，自动发到 Telegram |

| \*\*Git 日报\*\* | 定时查询各仓库 git log，推送当日开发摘要 |



\### 第四层：扩展集成（后期）

| 功能 | 说明 |

|---|---|

| \*\*飞书/Notion 集成\*\* | 笔记同步、任务管理联动 |

| \*\*本地知识库 RAG\*\* | 对本地文档做向量检索，回答问题时引用 |

| \*\*多模态输入\*\* | 语音已有，补全图片/文档输入链路 |



---



\## 三、怎么实施



\### 架构原则：最小侵入，插件式扩展



核心思想：\*\*新增一种 Bot 类型 `assistant`，与现有 `cli` 类型并列\*\*，复用所有基础设施，只在 Handler 层分叉。



```

现有架构                    扩展后

─────────────────────      ───────────────────────────────

BotProfile.cli\_type        BotProfile.bot\_mode

&nbsp; kimi / claude / codex      "cli"    → 现有逻辑不变

&nbsp;                            "assistant" → 新增助手逻辑

```



\### 文件结构规划



```

bot/

├── handlers/

│   ├── chat.py          # 现有 CLI 对话（不改）

│   ├── assistant.py     # 新增：助手对话 Handler

│   ├── memo.py          # 新增：备忘录命令

│   └── scheduler.py     # 新增：定时任务

├── assistant/

│   ├── \_\_init\_\_.py

│   ├── llm.py           # 直接 API 调用（Claude/OpenAI）

│   ├── memory.py        # 长期记忆存储与检索

│   ├── tools.py         # 工具调用定义（网页抓取、翻译等）

│   └── context.py       # 构建对话上下文（注入记忆）

├── data/

│   ├── memories.json    # 长期记忆持久化

│   └── memos.json       # 备忘录数据

```



\### 关键实现细节



\*\*1. 在 `BotProfile` 上增加 `bot\_mode` 字段\*\*

```python

\# bot/models.py - 新增字段

@dataclass

class BotProfile:

&nbsp;   ...

&nbsp;   bot\_mode: str = "cli"  # "cli" | "assistant"

```



\*\*2. `register\_handlers` 按 `bot\_mode` 分支\*\*

```python

\# bot/handlers/\_\_init\_\_.py

def register\_handlers(app, include\_admin=False):

&nbsp;   bot\_mode = app.bot\_data.get("bot\_mode", "cli")

&nbsp;   if bot\_mode == "assistant":

&nbsp;       \_register\_assistant\_handlers(app, include\_admin)

&nbsp;   else:

&nbsp;       \_register\_cli\_handlers(app, include\_admin)  # 现有逻辑

```



\*\*3. 长期记忆设计\*\*

\- 每条记忆有：`user\_id`, `type`(fact/summary/preference), `content`, `timestamp`, `tags`

\- 对话结束后，异步触发 AI 提炼本次对话的关键事实写入记忆

\- 下次对话开始时，检索最相关的 N 条记忆注入 System Prompt



---



\## 四、增量式更新架构



这是关键。整套方案按以下\*\*6个阶段\*\*交付，每个阶段独立可用、不破坏现有功能：



```

Phase 0 ── 已完成 ──────────────────────────────────────────

&nbsp; CLI Bridge Bot（当前状态）



Phase 1 ── 基础助手框架（1-2天）─────────────────────────────

&nbsp; 目标：让一个 Bot 能以"助手模式"运行，直接调 API 对话

&nbsp; 交付：

&nbsp; - BotProfile 增加 bot\_mode 字段

&nbsp; - bot/assistant/llm.py：封装 Claude API 直接调用

&nbsp; - bot/handlers/assistant.py：基础对话 Handler

&nbsp; - managed\_bots.json 新增一个 mode=assistant 的 Bot 配置

&nbsp; 风险：零，不改现有任何文件逻辑



Phase 2 ── 长期记忆（2-3天）────────────────────────────────

&nbsp; 目标：跨会话记住用户信息

&nbsp; 交付：

&nbsp; - bot/assistant/memory.py：记忆 CRUD + 关键词检索

&nbsp; - 对话后自动提炼记忆（后台异步任务）

&nbsp; - /memory 命令查看/删除记忆

&nbsp; 风险：低，纯新增文件



Phase 3 ── 效率工具集（3-5天）──────────────────────────────

&nbsp; 目标：备忘录、翻译、网页摘要

&nbsp; 交付：

&nbsp; - bot/handlers/memo.py：/memo /todos /done

&nbsp; - bot/assistant/tools.py：网页抓取、翻译工具

&nbsp; - 工具调用集成到 assistant.py

&nbsp; 风险：低



Phase 4 ── 定时与主动推送（3-5天）──────────────────────────

&nbsp; 目标：Bot 能主动发消息

&nbsp; 交付：

&nbsp; - bot/handlers/scheduler.py：定时任务管理

&nbsp; - APScheduler 集成（新依赖）

&nbsp; - /schedule /reminders 命令

&nbsp; 风险：中（需要集成 APScheduler）



Phase 5 ── 本地知识库 RAG（1周）────────────────────────────

&nbsp; 目标：对本地文档提问

&nbsp; 交付：

&nbsp; - 文档向量化（chromadb/faiss）

&nbsp; - /index <路径> 建索引

&nbsp; - 对话时自动检索相关段落

&nbsp; 风险：中（新增重型依赖）



Phase 6 ── 外部服务集成（按需）─────────────────────────────

&nbsp; 目标：飞书、Notion、日历等

&nbsp; 交付：按具体服务单独实现

&nbsp; 风险：视集成难度

```



\### 增量架构的关键保障



1\. \*\*功能开关\*\*：每个新能力都通过 `.env` 变量控制开关（`ASSISTANT\_ENABLED=true`），确保渐进启用

2\. \*\*依赖隔离\*\*：新功能的 Python 依赖全部标记为 optional，缺少时优雅降级（同现有 Whisper 的处理方式）

3\. \*\*数据隔离\*\*：所有持久化数据存在 `bot/data/` 目录，不干扰现有配置文件

4\. \*\*Handler 隔离\*\*：通过 `bot\_mode` 字段完全隔离助手逻辑和 CLI 逻辑，老 Bot 实例行为完全不变

5\. \*\*测试策略\*\*：每个 Phase 附带对应测试文件，沿用现有 pytest + mock 风格



---



\## 五、推荐起始点



\*\*建议从 Phase 1 开始\*\*，用 2 天完成最小可用的助手 Bot：



1\. 在 `managed\_bots.json` 里新增一条 `"bot\_mode": "assistant"` 的配置

2\. 创建 `bot/assistant/llm.py`，直接调用 `anthropic` SDK（或 openai）

3\. 创建 `bot/handlers/assistant.py`，接收文本 → 调 API → 回复

4\. 修改 `register\_handlers` 和 `\_start\_profile` 识别 `bot\_mode`



这样在不触碰任何现有文件的情况下（除了 `register\_handlers` 的一个分支），你就有了一个可用的个人助手 Bot 实例。后续每个 Phase 都是在这个基础上叠加，随时可以暂停。

