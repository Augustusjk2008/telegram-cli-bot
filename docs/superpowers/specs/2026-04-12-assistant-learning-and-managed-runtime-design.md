# Assistant Learning And Managed Runtime Design

日期：2026-04-12

## 目标

在当前“全机唯一 assistant”方案上，补齐三个最小可落地能力：

1. 修正 assistant `/reset`，只清当前用户运行态，不清 assistant 自有记忆。
2. 引入由宿主统一管理的 `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md`。
3. 落地最小学习闭环：
   `capture -> working memory`
   `capture -> proposal`

本次设计明确：assistant 是当前电脑上的全局 assistant，不是本项目私有 assistant。本项目只是它的 Telegram / Web 宿主与管理面。

## 已确认边界

- 当前机器只允许一个 `assistant` 型 Bot。
- assistant 创建时必须指定 `working_dir`，之后不允许修改。
- 如需更换 assistant 工作路径，只能删除 bot 后重建。
- assistant 的对话历史、记忆、proposal、upgrade 不进入项目级 session store。
- assistant 自有数据全部存储在 `<assistant_workdir>/.assistant/`。
- `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md` 由宿主管理，不允许 assistant 自己替换或修改。
- learning loop 采用 LLM 压缩，不采用纯规则压缩。
- 压缩不单独开新的 LLM 对话，而是在正常用户对话中顺带完成。
- 压缩频率应降低，不是每轮都做。
- 压缩过程默认对用户静默，不主动在回复中提及；若用户主动询问，assistant 可以说明本次 session 的压缩结果或压缩行为。

## 现状

### assistant 运行态

- [`bot/assistant_state.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_state.py) 已能把 assistant 私有运行态写入 `.assistant/state/users/<user_id>.json`。
- 该运行态包含：
  - `history`
  - `codex_session_id`
  - `kimi_session_id`
  - `claude_session_id`
  - `browse_dir`
  - running reply 状态

### assistant prompt

- [`bot/assistant_context.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_context.py) 已从 `memory/working/*.md` 和 approved knowledge 编译本地上下文。
- 当前 working memory 目录已存在，但没有真正的自动维护闭环。

### capture

- 每轮 assistant 回复后，都会经 [`record_assistant_capture()`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_state.py) 写入 `.assistant/inbox/captures/*.json`。
- 但 capture 目前只是堆积，没有继续转成 working memory 或 proposal。

### reset

- 当前 Telegram `/reset` 和 Web reset 都只调用 [`reset_session()`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py)。
- `reset_session()` 只清项目内 session 与项目 session store。
- assistant 真正的运行态在 `.assistant/state/users/<user>.json`，所以 assistant reset 现在不生效。

### assistant 身份文件

- assistant workdir 根目录目前没有宿主托管的 `AGENTS.md` / `CLAUDE.md` 生命周期。
- 仓库根已有 [`AGENTS.md`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/AGENTS.md) 和 [`CLAUDE.md`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/CLAUDE.md)，但没有同步到 assistant workdir，也没有被 assistant runtime 用作稳定身份约束。

## 方案比较

### 方案 A：宿主驱动 + 规则压缩

- 宿主负责同步 `AGENTS.md` / `CLAUDE.md`。
- 每次 capture 后用规则更新 working memory。

优点：

- 实现和测试最简单。
- 输出最稳定。

缺点：

- 学习质量低。
- 难以准确抽取偏好、目标切换、隐含待办。

### 方案 B：宿主驱动 + LLM 增量压缩

- 宿主负责同步 `AGENTS.md` / `CLAUDE.md`。
- assistant 在正常对话中顺带完成压缩。
- 压缩只处理“旧 working memory + 新增 captures + 当前请求”。

优点：

- 智能性足够。
- 不额外开新的压缩对话。
- 通过增量和限长可以控制上下文体积。

缺点：

- 需要宿主为“何时压缩、压缩后如何审计”加一层调度。

### 方案 C：完整反思式学习

- assistant 定期主动跑一轮“回顾全部历史并重写记忆”。

优点：

- 自主性最强。

缺点：

- 极易膨胀。
- 与上游 CLI 原生 session、系统提示词、已有上下文高度重复。
- 当前项目阶段明显过重。

## 已选方案

采用方案 B：宿主驱动 + LLM 增量压缩。

理由：

- 你已明确否定规则压缩。
- 又明确不希望为压缩单独开新对话。
- 因此最合适的是：把压缩约束成“同轮顺带完成的、低频触发的、增量式 LLM 压缩”。

## 总体架构

assistant 结构仍分为两层。

### 宿主层

由本项目负责：

- 创建、删除、启动、停止唯一 assistant bot
- Telegram / Web 聊天入口
- `AGENTS.md` / `CLAUDE.md` 的宿主同步
- assistant reset
- proposal 审批与 upgrade 应用
- learning loop 调度与审计

### assistant 私有数据层

由 `<assistant_workdir>` 承担，作为唯一真相来源。

目录：

```text
<assistant_workdir>/
  AGENTS.md
  CLAUDE.md
  .assistant/
    manifest.yaml
    state/
    inbox/
    memory/
    proposals/
    upgrades/
    evals/
    audit/
    indexes/
    prompts/
```

说明：

- `AGENTS.md` 和 `CLAUDE.md` 放在 workdir 根，不放在 `.assistant/` 内。
- `.assistant/` 只保存 assistant 私有数据与元数据。

## 宿主管理的 AGENTS.md / CLAUDE.md

### 文件位置

- `<assistant_workdir>/AGENTS.md`
- `<assistant_workdir>/CLAUDE.md`

### 宿主同步时机

宿主在以下时机强制同步这两个文件：

1. 创建 assistant bot 时
2. 加载已有 assistant bot 时
3. 每次 assistant 对话开始前

结果：

- 文件不存在会自动重建。
- 文件被 assistant 或外部修改后，会被宿主覆盖回宿主版本。

### 内容职责

这两个文件作为稳定身份与能力边界说明，至少包含：

- assistant 是“本机唯一、全局的 assistant”
- 本项目只是宿主入口，不是 assistant 本体
- `.assistant` 的关键目录位置
- assistant 可以维护的内容：
  - `memory/working/*.md`
  - `proposals/*.json`
  - 审计记录
- assistant 不可修改的内容：
  - `AGENTS.md`
  - `CLAUDE.md`
  - `manifest.yaml`
  - 宿主定义的 schema / 根目录结构
  - 未经审批的长期知识生效区

### 与运行时 prompt 的关系

- `AGENTS.md` / `CLAUDE.md` 承担稳定、不常变的身份约束。
- 运行时本地 prompt 只补充短期 working memory、approved knowledge、当前请求。
- 这样可以减少与 Codex / Claude 原生系统提示、会话历史的重复。

## 记忆读取设计

### 目标

不仅要定义 assistant 怎么写记忆，还要定义 assistant 平时怎么读记忆。

读取侧必须解决四个问题：

1. 哪些内容每轮都读，哪些只按需读
2. 哪些内容只在没有 native session 时读
3. 哪些内容绝不能默认读，避免上下文爆炸
4. assistant 被用户问到“你记得什么、刚才压缩了什么”时，应该读哪一层数据回答

### 读取分层

assistant 的读取分为五层，自上而下优先级递减：

1. 当前用户请求与实时文件 / 命令结果
2. 宿主管理的身份边界
3. working memory
4. approved knowledge
5. 当前用户 runtime state 的最小摘要回退

说明：

- `captures`、`audit`、`pending proposals` 不进入默认主读取链。
- 这些内容只在明确需要时按需读取。

### 各层职责

#### 第 1 层：当前请求与实时结果

最高优先级，包含：

- 当前用户输入
- 当前轮命令输出
- 当前轮文件读取结果
- 当前轮错误信息

这层永远覆盖其它记忆层。

#### 第 2 层：宿主管理的身份边界

来源：

- `<assistant_workdir>/AGENTS.md`
- `<assistant_workdir>/CLAUDE.md`

职责：

- 告诉 assistant 自己是谁
- 告诉 assistant 自己的数据根在哪里
- 告诉 assistant 哪些内容能改，哪些不能改

读取策略：

- 不把这两个文件全文在每轮 prompt 中重复展开。
- 宿主维护一个 `identity_digest`，从这两个文件提取最小稳定摘要。
- 只在以下情况注入 `identity_digest`：
  - 当前 native session 尚未建立
  - 或宿主管理文件内容发生版本变化

这样既保证 assistant 知道自己的身份，又避免每轮重复塞入整份身份说明。

#### 第 3 层：working memory

来源：

- `.assistant/memory/working/current_goal.md`
- `.assistant/memory/working/open_loops.md`
- `.assistant/memory/working/user_prefs.md`
- `.assistant/memory/working/recent_summary.md`

职责：

- 提供短期跨 session 的最小上下文
- 承接 capture 压缩结果

读取策略：

- `current_goal` 默认每轮都读
- `user_prefs` 默认每轮都读，但只取与当前请求最相关的少量条目
- `open_loops` 默认每轮都读，但只取与当前请求相关或最近的少量条目
- `recent_summary` 只在需要时读，不默认每轮读满

#### 第 4 层：approved knowledge

来源：

- `.assistant/memory/knowledge/*.md`
- `.assistant/indexes/chunks.sqlite`

职责：

- 提供已审批、可长期复用的知识和规则

读取策略：

- 只做按需检索，不全量注入
- 检索 query 由 `当前用户请求 + current_goal` 组成
- 默认只取少量 top chunks
- 未审批 proposal 不参与这层检索

#### 第 5 层：runtime state 最小回退

来源：

- `.assistant/state/users/<user_id>.json`

职责：

- 当 native CLI session 不存在时，补一层轻量的当前用户会话摘要

读取策略：

- 有 native session 时，不从 runtime `history` 再推导近期摘要
- 无 native session 时，才允许从当前用户 history 推导一个极短的 `current_goal` / `recent_summary`

这样避免和 Codex / Claude / Kimi 原生会话历史重复。

## 按场景读取

### 普通任务模式

适用于绝大多数正常对话。

默认读取：

- 当前用户请求
- 实时文件 / 命令结果
- `identity_digest`（仅首次 session 或身份版本变化时）
- `current_goal`
- 少量相关 `user_prefs`
- 少量相关 `open_loops`
- 少量 approved knowledge chunks

条件读取：

- `recent_summary`
  - 当前 native session 不存在时读取
  - 任务明显切换时读取

默认不读：

- 原始 captures
- compaction audit
- pending proposals
- 全量 history

### 记忆解释模式

适用于用户问这类问题时：

- “你记得什么”
- “你刚才压缩了什么”
- “你现在的记忆文件里有什么”
- “你为什么这么理解我”

读取：

- 四个 working memory 文件
- `.assistant/audit/compactions.jsonl`
- 必要时读取最近少量 captures 作为佐证

仍然默认不读：

- 全量 capture 历史
- 全量 proposal 历史

### proposal / 升级模式

适用于用户问这类问题时：

- “有哪些待审批 proposal”
- “这次升级建议是什么”
- “为什么生成这个 proposal”

读取：

- 相关 proposal 文件
- 当前 working memory
- 相关 approved knowledge
- 必要时读取少量最近 capture 解释 proposal 来源

### 精确追溯模式

只在用户明确要求“找原话、找原始记录”时启用。

读取：

- 指定时间范围或最近少量 `captures`

限制：

- 不允许默认把大量原始 capture 回灌进主上下文
- 只返回与问题直接相关的少量原始片段

## Prompt 编译设计

### 编译目标

将读取到的多层信息编译成一个很小的本地上下文块，交给 CLI 主对话使用。

编译后的 prompt 只保留“完成当前请求所需的最小上下文”，不是把 assistant 全部记忆倒进去。

### 编译结构

建议保持如下结构：

```text
[LOCAL_ASSISTANT_CONTEXT]
assistant_identity:
- ...

current_goal:
- ...

open_loops:
- ...

user_preferences:
- ...

recent_summary:
- ...

retrieved_knowledge:
- ...

meta_context:
- ...

[USER_REQUEST]
...
```

说明：

- `assistant_identity` 只在首次 session 或身份版本变化时出现
- `meta_context` 只在“记忆解释模式”或“proposal / 升级模式”出现
- 普通任务模式下通常不会出现 `meta_context`

### 编译预算

为了控制体积，读取后还要做二次裁剪。

建议预算：

- `assistant_identity`: 最多 3 条
- `current_goal`: 1 条
- `open_loops`: 最多 3 条
- `user_preferences`: 最多 4 条
- `recent_summary`: 最多 3 条
- `retrieved_knowledge`: 最多 3 条
- `meta_context`: 只在特殊模式下开启，且最多 3 条

这意味着：

- working memory 可以比最终注入的上下文略多一点
- 但真正送进 prompt 的内容永远比存储层更小

### 相关性选择

对 `open_loops`、`user_prefs`、`retrieved_knowledge`，宿主需要做一层相关性筛选。

第一版可采用简单策略：

- 使用 `当前用户请求 + current_goal` 做关键词匹配
- 先选命中的条目
- 若命中不足，再用最近条目补齐

这层是“读取裁剪”，不是“写入压缩”。

## 默认不读取的内容

以下内容不进入默认主 prompt：

- 全量 `captures`
- 全量 `history`
- 全量 `audit`
- 未审批 proposals
- `AGENTS.md` / `CLAUDE.md` 全文

原因：

- 这些内容过长
- 大多数轮次并不需要
- 容易和 native session、自带系统提示词产生重复

## 读取冲突优先级

当多层信息冲突时，优先级固定为：

1. 当前用户显式要求
2. 当前轮实时文件 / 命令结果
3. 宿主管理的身份边界
4. approved knowledge
5. working memory
6. runtime state 的 history 回退
7. 原始 captures / audit / proposals 的按需解释内容

解释：

- 低层内容只能补充，不能覆盖高层明确要求。
- 如果用户当前要求和历史偏好冲突，按当前要求执行。

## Reset 语义

### 目标

assistant `/reset` 必须真正让“当前用户会话”重新开始，但不能抹掉 assistant 的持续学习成果。

### assistant 模式下 reset 的行为

清除以下内容：

- 内存中的当前 `(bot_id, user_id)` session
- `.assistant/state/users/<user_id>.json`
- 当前运行中的 CLI 进程
- 该用户的 native session id
- 该用户的当前会话 history 与 running reply 状态

保留以下内容：

- `.assistant/inbox/captures/`
- `.assistant/memory/working/`
- `.assistant/memory/knowledge/`
- `.assistant/memory/skills/`
- `.assistant/proposals/`
- `.assistant/upgrades/`
- `.assistant/audit/`
- `<assistant_workdir>/AGENTS.md`
- `<assistant_workdir>/CLAUDE.md`

### 非 assistant 模式

`cli` 模式保持原语义，继续调用项目级 [`reset_session()`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py)。

### 接口影响

以下入口都必须遵循新语义：

- Telegram `/reset`
- Web reset API

## Learning Loop MVP

### 目标

落地两个最小闭环：

1. `capture -> working memory`
2. `capture -> proposal`

本次不做：

- 自动写入长期 knowledge
- 自动应用 code upgrade
- 大规模历史回顾式重写

### capture

assistant 每轮成功回复后继续写入：

```text
.assistant/inbox/captures/*.json
```

capture 保留原始事实，不直接进主 prompt。

### working memory

working memory 固定只维护四个文件：

```text
.assistant/memory/working/current_goal.md
.assistant/memory/working/open_loops.md
.assistant/memory/working/user_prefs.md
.assistant/memory/working/recent_summary.md
```

每个文件都必须强制定长：

- `current_goal`: 1 条，约 200 字内
- `open_loops`: 最多 5 条
- `user_prefs`: 最多 8 条
- `recent_summary`: 最多 4 条

working memory 是 assistant 的短期跨 session 认知层，不等于当前单次 history。

### proposal

压缩过程中识别出“应进入长期规则/知识/升级候选”的内容时，不直接写生效区，只生成 proposal。

proposal 首期覆盖：

- 长期知识候选
- 身份/规则候选
- 升级建议候选

## LLM 增量压缩

### 基本策略

压缩采用 LLM，但不是单独开的新对话，而是在正常用户对话里顺带完成。

也就是说：

- 正常聊天仍只发起一次主对话。
- 当宿主判断“本轮应该压缩”时，在本轮送给 CLI 的本地上下文里增加一段宿主指令。
- 指令要求 assistant：
  - 正常回答用户
  - 必要时在后台更新 working memory
  - 不要在回复中主动提及压缩行为

### 为什么不单独开压缩对话

- 避免多出一条额外 session / history 分支
- 避免重复消耗模型上下文
- 保持“assistant 在工作中顺手维护记忆”的行为模型

### 压缩输入

每次触发压缩时，输入仅限于：

- 当前四个 working memory 文件
- 自上次压缩后新增的 captures
- 当前用户请求

不把全部历史重新送进模型。

### 压缩输出

压缩结果直接落到文件，不通过额外对用户显示的文本通道回传。

宿主只接受对以下文件的更新：

- `current_goal.md`
- `open_loops.md`
- `user_prefs.md`
- `recent_summary.md`

如果 assistant 同轮产出了 proposal，则额外生成 proposal 文件。

### 静默原则

- assistant 默认不在用户回复里提“我刚做了压缩”。
- 若用户主动问：
  - 本次 session 做了哪些压缩工作
  - working memory 现在是什么
  assistant 可以读取 working memory 与审计记录后回答。

## 压缩频率控制

### 原则

- 压缩应低频，不在每轮对话都做。
- 宿主判断是否需要压缩，assistant 不自行无限触发。

### 触发条件

满足任一条件时，标记“需要压缩”，并在下一次正常对话中顺带执行：

1. 自上次压缩后新增 `6` 条 capture
2. 或距离上次压缩已过 `30` 分钟，且至少新增 `2` 条 capture
3. 或出现强信号事件：
   - 用户明确表达新的长期偏好
   - assistant 身份/规则发生新的明确约束
   - 当前任务目标明显切换

### 增量状态

宿主维护一个很小的压缩状态文件，例如：

```text
.assistant/state/compaction.json
```

用于记录：

- 上次成功压缩时间
- 上次消费到的 capture 游标
- 待压缩 capture 数

## 防止上下文爆炸

本方案通过以下方式控制上下文规模：

1. 不全量回放历史，只做增量压缩
2. 压缩频率降低，不是每轮都压缩
3. 主 prompt 只读 working memory 和 approved knowledge
4. working memory 固定槽位、固定上限
5. capture 只做底层存档，不直接注入主 prompt
6. 稳定身份放在 workdir 根的 `AGENTS.md` / `CLAUDE.md`，不在每轮动态 prompt 里重复展开

## 审计与可观察性

### 审计

每次压缩成功后，宿主写入：

```text
.assistant/audit/compactions.jsonl
```

记录至少包括：

- 时间
- 消费的 capture 范围
- 更新了哪些 working memory 文件
- 是否生成 proposal

### 面向用户的可见性

- 默认不主动展示压缩行为。
- 当用户主动询问时，assistant 可以基于 working memory 与 compaction audit 说明：
  - 本次 session 进行了哪些压缩
  - 当前有哪些 working memory 条目

## 实现范围

### 本次实现

- assistant 模式下真正生效的 reset
- 宿主管理的 `AGENTS.md` / `CLAUDE.md` 生成与同步
- capture 累积后的“低频、同轮、静默” LLM 压缩设计落点
- working memory 四文件维护
- proposal 最小生成路径
- 压缩审计

### 本次不实现

- assistant 自动修改长期 knowledge 生效区
- assistant 自动应用宿主代码升级
- 复杂检索排序优化
- 大规模 eval / rollback 平台

## 测试策略

### 单元测试

- assistant reset 会删除 `.assistant/state/users/<user>.json`
- assistant reset 不会删除 `memory/working`、`captures`、`proposals`
- `bootstrap/load assistant home` 会生成并同步 `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md`
- 若 workdir 根的 `AGENTS.md` / `CLAUDE.md` 被修改，宿主同步会覆盖回宿主版本
- `identity_digest` 只在首次 native session 或身份版本变化时注入
- 有 native session 时，不再从 runtime `history` 推导 `recent_summary`
- 无 native session 时，允许从 runtime `history` 做最小回退
- 普通任务模式不会读取 `audit`、原始 `captures`、pending proposals
- 记忆解释模式会读取 working memory 与 compaction audit
- approved knowledge 检索只返回少量 top chunks，且不混入未审批 proposal
- 压缩调度器只在达到阈值时标记压缩
- 压缩后 working memory 文件被限长写回
- proposal 候选会生成到 `.assistant/proposals/`

### 集成测试

- Telegram assistant 对话后能写 capture
- 达到阈值后的下一次对话会执行同轮压缩
- 压缩不改变用户可见回复格式
- assistant 普通对话的本地 prompt 只包含裁剪后的 working memory / knowledge，而不包含全量 capture
- 用户主动询问“你记得什么”时，assistant 能基于 working memory 和 audit 给出说明
- Web assistant reset 与 Telegram reset 语义一致

## 风险与取舍

### 风险

- 因为不单独开压缩对话，具体 CLI 是否会稳定遵循“静默压缩”指令，存在模型依赖。
- 如果 assistant 在本轮没有按预期完成压缩，宿主只能通过文件未变化识别失败，并延后到后续轮次再试。

### 取舍

- 这版优先保证边界正确、上下文可控、数据位置清晰。
- 不追求第一版就做到完美自主学习。
- 一旦该 MVP 稳定，再考虑更强的 proposal 分类、评测与长期知识合并。

## 实现建议顺序

1. assistant reset 真正清理私有运行态
2. 宿主管理 `AGENTS.md` / `CLAUDE.md`
3. 压缩状态文件与触发判断
4. 对话内静默压缩入口
5. working memory 写回与 proposal 生成
6. 审计与测试补齐
