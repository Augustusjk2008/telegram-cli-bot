# Web Chat Native History Rich Events Design

日期：2026-04-14

本版重写后，旧的“应用自己持久化完整 rich trace”方案不再作为主方向。本设计以 Codex / Claude 原生本机会话历史为主数据源，只让应用保留极薄的一层运行态 overlay。

## 目标

解决当前 Web 聊天页在 `codex` / `claude` 上的三个核心问题：

- “终止任务”后，本轮对话不能消失；用户已经看到的内容和过程，必须能在刷新后继续可见。
- Web 端必须能区分并展示：
  - 中途进度 / commentary
  - 最终总结
  - tool call
  - tool result
  - cancel / error / incomplete
- 默认阅读体验仍以最终总结为中心：
  - 主气泡默认只显示最终总结或最后可见预览
  - “查看过程”默认折叠
  - tool call / tool result 默认继续折叠，单独可展开

## 方向性原则

本次设计只服务以下目标：

- `Web + Codex`
- `Web + Claude`
- 当前“CLI-backed assistant bot”

明确不为以下对象做兼容性设计：

- `kimi`
- Telegram 聊天链路
- 旧的非 CLI assistant bot
- 任何只为了历史兼容而保留的旧分支逻辑

这里的“当前 assistant bot”指的是：虽然 `bot_mode="assistant"`，但实际仍走 [`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 中的 CLI 聊天链路，只是在发送前额外编排 prompt、在收尾时写 assistant home 状态。旧的“自己调工具、不是 CLI 会话”的 assistant 运行形态视为放弃对象。

## 已确认约束

- 原生会话历史优先；应用不再以自己保存的完整对话正文作为真源。
- 终止动作不能直接写最终历史；只能由流循环 finalizer 统一收口。
- 第一版不要求把所有底层原始事件 100% 无损映射成漂亮 UI，但必须保留足够的结构和 `raw_type`，避免以后失真。
- Codex / Claude 的 tool-use 字段定义必须以官方文档为准，不能只靠仓库里当前解析逻辑或少量本地样本猜测。
- Web 最终显示必须维持“summary first”；过程与 tool call 默认折叠，不允许反客为主。

## 当前现状

### 1. 现有 Web 历史真源仍是应用内 `session.history`

[`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 的 `get_history()` 当前直接返回：

```python
return {"items": session.history[-max(1, limit):]}
```

而 [`bot/models.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py) 的 `UserSession.history` 当前只保存：

- `timestamp`
- `role`
- `content`
- `elapsed_seconds`

这意味着现在的 Web 历史既看不到原始 tool use，也看不到中途 commentary / progress / raw event type。

### 2. 当前 `/kill` 只杀进程，不保证本轮会话可回放

[`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 的 `kill_user_process()` 当前只做：

- 检查 `session.process`
- `terminate()`
- 必要时 `kill()`

它不会：

- 写 assistant 终态消息
- 写过程 trace
- 标记一条可重建的取消终态

而流循环在结尾才会：

- `session.add_to_history("assistant", response, ...)`
- `session.clear_running_reply()`

所以一旦 kill 时没有顺利走到 finalizer，用户刚刚看过的内容就会丢。

### 3. 当前前端只能看到“预览文本”和“最终文本”

[`front/src/services/realWebBotClient.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/realWebBotClient.ts) 当前只消费：

- `delta.text`
- `status.preview_text`
- `done.output`

[`front/src/screens/ChatScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx) 当前也只维护一个纯文本 assistant 气泡，因此：

- 看不到 CLI 的原始消息结构
- 看不到中途 commentary 与最终总结的区别
- 看不到 tool call / tool result
- 点击“终止任务”后，前端体感仍可能停在假 streaming 状态

## 本地原生会话调研结论

### Codex

当前机器上的 Codex 原生会话可用数据源已经足够丰富：

- 输入历史索引：[`C:\Users\JiangKai\.codex\history.jsonl`](/C:/Users/JiangKai/.codex/history.jsonl)
- 完整 session JSONL：[`C:\Users\JiangKai\.codex\sessions`](/C:/Users/JiangKai/.codex/sessions)
- session id 到 rollout 文件路径的索引：[`C:\Users\JiangKai\.codex\state_5.sqlite`](/C:/Users/JiangKai/.codex/state_5.sqlite)

已验证 `threads` 表能直接给出：

- `id`
- `rollout_path`
- `cwd`

这意味着 `session.codex_session_id -> rollout_path` 可以直接定位，不需要全量扫描 `~/.codex/sessions`。

原生 JSONL 中已经能看到：

- `session_meta`
- `turn_context`
- `response_item.message`
- `response_item.function_call`
- `response_item.function_call_output`
- `event_msg.agent_message`
- `event_msg.task_started`
- `event_msg.task_complete`

本地样本也证明：即使用户较早中断，Codex 原生 session 往往已经写入了用户轮次、commentary 和 tool call，足以成为 Web 历史主数据源。

### Claude

当前机器上的 Claude 原生会话数据源也足以做第一版：

- 输入历史索引：[`C:\Users\JiangKai\.claude\history.jsonl`](/C:/Users/JiangKai/.claude/history.jsonl)
- 完整项目会话：[`C:\Users\JiangKai\.claude\projects`](/C:/Users/JiangKai/.claude/projects)

Claude 的完整 session 按 `projects/<cwd-bucket>/<sessionId>.jsonl` 组织。对本仓库当前工作目录，样本 bucket 形态为：

- [`C:\Users\JiangKai\.claude\projects\C--Users-JiangKai-telegram-cli-bridge-refactoring`](/C:/Users/JiangKai/.claude/projects/C--Users-JiangKai-telegram-cli-bridge-refactoring)

本地样本中已经能看到：

- `type:"user"`
- `type:"assistant"`
- assistant `message.content[].type:"tool_use"`
- user follow-up `message.content[].type:"tool_result"`

但也已经验证一个重要 caveat：

- Claude 在“非常早”的 kill 场景下，原生文件有时只来得及写入用户消息，尚未写入 assistant/tool trace。

因此 Claude 不能做“纯原生零 overlay”方案。

## 官方协议参考

本设计以下两条语义，明确以官方文档为准：

- OpenAI / Responses / Function Calling：
  - `function_call`
  - `function_call_output`
  - 通过 `call_id` 关联
- Anthropic / Messages / Tool Use：
  - assistant 侧使用 `tool_use` block
  - tool 回填使用 `tool_result`
  - 通过 `tool_use_id` 关联

参考：

- OpenAI Function Calling：
  - https://platform.openai.com/docs/guides/function-calling
- Anthropic Tool Use：
  - https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use
  - https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/handle-tool-calls

额外说明：

- 对 Codex CLI 的编码型内置工具，第一版不把底层 item type 写死成仓库猜测值。
- 归一化层必须保留 `raw_type`、`tool_name`、`call_id` 等原始信息。
- 任何未识别 item 一律进入 `unknown`，不能直接丢弃。

## 方案比较

### 方案 A：继续由应用自己保存完整历史与 rich trace

优点：

- 不依赖外部 session 文件定位
- 逻辑集中在本仓库内

缺点：

- 与 Codex / Claude 已经存在的原生会话存储重复
- kill / resume / 重启后容易出现“双份真相”
- 后续一旦原生 CLI 输出结构升级，应用侧解析和持久化都要同步追赶

结论：

- 放弃。本次重写就是要避免继续扩张这条路线。

### 方案 B：完全只读原生历史，不保留任何应用 overlay

优点：

- 逻辑最干净
- 应用不存对话正文

缺点：

- 无法稳定处理“进程还活着但 native 文件尚未刷新”的运行态 UI
- 无法稳定覆盖 Claude 早停场景
- `/kill` 后无法保证一定能给用户看到一个完整的取消终态

结论：

- 放弃。它对 Codex 较友好，但对 Claude 过于乐观。

### 方案 C：原生历史为主，应用只保留轻量 overlay

优点：

- 避免重复存完整对话历史
- 保留对 kill / incomplete / early-stop 的可控兜底
- 可以把 Web 历史与 streaming 展示都统一到同一份“原生记录 + overlay 注解”

缺点：

- 需要新增 native lookup、adapter、overlay 三层
- 历史接口不再是简单的 `session.history`

结论：

- 采用。

## 已选方案

采用“原生历史为主 + 轻量 overlay 兜底”的方案。

### 真源定义

对 `web + codex/claude + 当前 CLI-backed assistant` 来说：

- 主对话历史真源：Codex / Claude 原生 session 文件
- 应用侧真源：仅限运行态与补注解数据

不再要求应用侧保存：

- 完整 assistant 正文历史
- 完整 rich trace 历史
- 与原生 transcript 等价的副本

### `session.history` 的定位

[`bot/models.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py) 的 `session.history` 在这条新链路中降级为：

- legacy 兼容字段
- 非 Web 首选真源

第一版不要求立刻删除它，但 Web 历史页和 Web streaming finalization 不再依赖它作为权威数据。

## 目标架构

### 1. Native Locator

负责从当前 `UserSession` 中已有的原生 session id 找到本地 transcript 文件。

#### Codex

输入：

- `session.codex_session_id`

主路径：

- 查询 `~/.codex/state_*.sqlite` 的 `threads` 表，拿到 `rollout_path`

兜底：

- 如果 SQLite 不可用，再扫描 `~/.codex/sessions/**/*.jsonl`

#### Claude

输入：

- `session.claude_session_id`
- 当前工作目录或 overlay 中保留的 cwd hint

主路径：

- 根据 Claude `projects/<cwd-bucket>/<sessionId>.jsonl` 规则定位

兜底：

- bucket 不匹配时，按 `sessionId.jsonl` 在 `~/.claude/projects` 下窄范围扫描

### 2. Native Adapter

负责把 Codex / Claude 原生 transcript 适配为统一的 Web 会话视图。

统一后的 assistant 终态对象建议至少包含：

```json
{
  "summary_text": "最终总结或最后预览",
  "summary_kind": "final",
  "completion_state": "completed",
  "trace_version": 1,
  "trace": []
}
```

统一后的 trace 事件建议至少包含：

```json
{
  "kind": "tool_call",
  "source": "native",
  "provider": "codex",
  "time": "2026-04-14T10:00:03.120000",
  "raw_type": "function_call",
  "tool_name": "shell_command",
  "call_id": "call_123",
  "title": "shell_command",
  "summary": "Get-ChildItem -Force",
  "payload": {
    "arguments": {
      "command": "Get-ChildItem -Force"
    }
  }
}
```

`kind` 第一版统一为：

- `message`
- `commentary`
- `tool_call`
- `tool_result`
- `status`
- `cancelled`
- `error`
- `unknown`

### 3. Overlay Store

Overlay 不是第二份聊天历史，只保存以下信息：

- 当前活动轮次的运行态
- `stop_requested`
- 最后一个 preview 文本
- native locator hint
- 针对 native 缺口生成的极小 synthetic 注解

建议 overlay 字段只覆盖：

- `turn_key`
- `cli_type`
- `native_session_id`
- `started_at`
- `updated_at`
- `last_preview_text`
- `stop_requested`
- `native_locator_hint`
- `synthetic_completion_state`
- `synthetic_summary_text`

禁止 overlay 继续演化为：

- 完整 message history 副本
- 完整 tool trace 副本
- 每条 native event 的镜像表

### 4. Conversation Builder

`/history` 不再直接回 `session.history`，而是：

1. 读取当前 bot/user 绑定的原生 session id
2. 找到 native transcript
3. 通过 adapter 生成统一 turn 列表
4. 将 overlay 中尚未落入 native transcript 的 running / cancelled 注解 merge 进去
5. 输出前端统一消息结构

这个 builder 才是 Web 聊天页新的历史真源。

## 当前 assistant bot 的处理原则

当前 `assistant` 模式仍在 [`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 中进入 CLI 聊天路径，因此它仍属于本设计的第一类对象。

处理原则是：

- prompt 编排、assistant home 收尾逻辑继续保留
- 历史展示层仍以 Codex / Claude 原生 transcript 为主
- assistant home 产生的 proposal / compaction / capture 不作为聊天主历史真源

换句话说：

- “当前 assistant bot”继续支持
- “旧的非 CLI assistant runtime”明确不纳入这份 spec 的目标面

## 历史与流式协议

### 历史接口

历史接口返回的 message 结构需要扩展，但重点不是“多存字段”，而是“明确区分 summary 与 process”：

```json
{
  "id": "turn_123",
  "role": "assistant",
  "content": "最终总结或最后可见预览",
  "created_at": "2026-04-14T10:00:12",
  "elapsed_seconds": 12,
  "meta": {
    "completion_state": "completed",
    "summary_kind": "final",
    "trace_version": 1,
    "trace": [],
    "native_source": {
      "provider": "codex",
      "session_id": "019d8847-1fa9-7d12-92e2-1086391920a9"
    }
  }
}
```

### SSE 协议

SSE 仍保留当前整体风格，但新增结构化 `trace`：

- `meta`
- `delta`
- `status`
- `trace`
- `done`
- `error`

语义：

- `delta`
  - 仅作兼容和轻量文本流
- `status`
  - 维护 preview 文本和耗时
- `trace`
  - 发送一条统一后的过程事件
- `done`
  - 返回统一终态消息对象，而不只是 `output`

这能让前端在 streaming 阶段和 history 阶段使用同一套 UI 模型。

## 终止与 finalization

### 后端原则

`/kill` 的职责只剩：

- 设置 `stop_requested`
- 尝试 terminate / kill 当前进程
- 返回“已发送终止请求”

`/kill` 不再负责：

- 写最终 assistant 历史
- 清空会话真源
- 抢先宣布这轮已经完成

只有流循环 finalizer 可以决定：

- 本轮最终 `completion_state`
- `summary_text`
- `summary_kind`
- 需要 merge 的 overlay 注解

### Finalizer 的判定顺序

1. 优先从 native transcript 读取这一轮已落盘的 assistant / tool / commentary
2. 若 native 已有完整 final answer：
   - `completion_state=completed`
   - `summary_kind=final`
3. 若 native 没 final，但已有可见 commentary / preview：
   - `completion_state=cancelled` 或 `error`
   - `summary_kind=partial_preview`
4. 若 native 几乎无 assistant 数据：
   - 使用 overlay 的 `last_preview_text`
   - 如果仍为空，则生成固定占位文案

建议取消兜底文案：

```text
已终止，未返回可显示内容
```

### Claude 特殊 caveat

由于 Claude 早停时可能只写入用户轮次而没有 assistant/tool 记录，因此第一版必须接受：

- Codex：主要依赖 native transcript
- Claude：更频繁依赖 overlay synthetic completion

这不是兼容性妥协，而是当前原生行为差异带来的必需设计。

## 终止按钮前端交互

为解决“点了像卡住”的体验问题，前端终止流程必须显式改成四段：

1. 先中断当前 SSE 读取
2. 再调用 `/kill`
3. 轮询 overview 或等待终态事件，直到后端 finalizer 完成
4. 用统一终态消息回填当前 assistant 气泡

具体要求：

- `sendMessage()` 需要支持 `AbortController`
- 点击“终止任务”后，当前前端 streaming 状态必须立即结束，不能继续假装在收流
- 按钮进入 `终止中...`
- 页面允许显示轻量等待态，但不能把这段等待误判成请求失败
- finalizer 完成后，当前 assistant 气泡必须变成：
  - `completed + final`，或
  - `cancelled/error + partial_preview`

因此“终止按钮生效”在产品语义上不再等价于“后端子进程瞬间退出”，而是等价于：

- 用户立刻脱离 streaming 态
- 后端随后给出一个可回放的终态

## UI 行为

### 主气泡

主气泡只显示：

- 最终总结，或
- 最后一个可见 preview

如果是取消终态：

- 显示 `已终止` 标识

### 过程区

assistant 消息存在 `trace` 时，在主气泡下方显示：

- `查看过程`

默认折叠。

展开后：

- `commentary` / `status` / `error` / `cancelled` 以轻量时间线显示
- `tool_call` / `tool_result` 以卡片显示

streaming 阶段也使用同一套结构：

- 主气泡只显示当前 preview
- 过程区仍默认折叠
- tool 卡片仍默认折叠

### Tool 卡片

tool 卡片默认继续折叠，只显示：

- tool 名称
- started / completed / failed 状态
- 一行摘要

用户点击后才展开：

- 入参摘要
- 输出摘要
- 裁剪后的 `payload`
- `raw_type`

这满足“能看结构”和“默认不吵”两个要求。

## 最终显示与格式化规则

最终显示分三层：

- 主 summary
  - 继续走 Markdown 渲染
- streaming preview
  - 继续走纯文本
- process / tool trace
  - 使用结构化时间线与卡片，不混进主 Markdown 气泡

因此 Web 最终会明确区分：

- 哪些是中途 commentary
- 哪些是最终回答
- 哪些是 tool use / tool result

而不是再把所有内容折叠成一个无法解释来源的字符串。

## 兼容性策略

这次设计不把“Kimi 正常”“Telegram 正常”“旧 assistant 正常”作为成功标准。

允许保留的最小过渡兼容只有两类：

- 前端旧逻辑若还只读 `done.output`，后端第一版继续保留该字段
- 极少数 native transcript 无法定位时，可临时退回 legacy 文本显示，但不作为产品承诺

除此之外，不为旧分支新增设计复杂度。

## 测试重点

### 后端

[`tests/test_web_api.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_web_api.py) 需要覆盖：

- `/history` 优先走 native transcript，而非 `session.history`
- Codex session id 能通过 SQLite 索引定位 rollout 文件
- Claude session id 能通过项目 bucket 或 fallback scan 找到 transcript
- `/kill` 不直接写终态，只有流循环 finalizer 写一次
- kill 后若 native 缺 final answer，仍能得到 `cancelled + partial_preview`
- 未识别 native item 会进入 `unknown`

### 前端

[`front/src/test/chat-screen.test.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/chat-screen.test.tsx) 需要覆盖：

- 默认只显示 summary
- “查看过程”默认折叠，可展开 / 收起
- tool card 默认折叠，可展开 / 收起
- 点击“终止任务”后，前端立即退出 streaming 显示并进入等待 finalization 状态
- cancelled 消息会显示 `已终止`
- summary 仍保持 Markdown 渲染，过程区不混入 summary

### 客户端

[`front/src/test/real-client.test.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/real-client.test.ts) 需要覆盖：

- `trace` 事件解析
- kill 时中断当前 SSE 读取
- `done` 返回富消息对象后，能正确映射到前端 message 结构

## 实施顺序

1. 建立 native locator：Codex SQLite + Claude project transcript 查找。
2. 建立 native adapter：Codex / Claude transcript 归一化为统一 turn / trace。
3. 定义 overlay 数据结构，只保留运行态与 synthetic finalization 注解。
4. 改造 Web `/history` 与 streaming finalizer，切换为“native + overlay”真源。
5. 扩展前端类型和 SSE 处理，加入 process / tool card 折叠 UI。
6. 改造终止按钮交互：前端立即结束本地 streaming 视图，再等待后端 finalizer 收口。
7. 跑针对性前后端测试，只以 `web + codex/claude + 当前 CLI-backed assistant` 为验收面。

## 回归清单

- `codex` Web 聊天在正常完成、kill、中途刷新三条路径下都能回放。
- `claude` Web 聊天在正常完成与早停场景下都能保住可见终态。
- 过程区默认折叠，tool call 默认折叠。
- 主聊天流仍以 summary 为中心，不被长过程污染。
- 当前 assistant bot 仍可用，因为它本质上仍走 CLI transcript。
- Kimi / Telegram / 旧 assistant 的回归不作为本次验收阻塞项。
