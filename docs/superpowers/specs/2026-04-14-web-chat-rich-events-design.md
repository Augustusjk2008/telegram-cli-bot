# Web Chat Rich Events Design

日期：2026-04-14

## 目标

解决当前 Web 聊天页 CLI 对话的两个核心问题：

- “终止任务”后，当前轮回复不能再直接丢失，必须把已得到的可见内容与过程摘要保存进历史并继续可见。
- Web 端不能再只把 CLI 输出当作一段纯文本；需要为 Codex / Claude / Kimi 引入统一的“富事件”轨迹，让页面能区分：
  - 中途预览
  - 最终总结
  - tool call / tool result
  - 取消 / 错误 / 其他状态

同时保留当前聊天页的阅读效率：

- 默认只显示最终总结。
- “查看过程”默认折叠。
- tool call 卡片也默认折叠，可单独展开。

## 已确认约束

- 采用“富事件方案”，不做只保存 partial preview 的最小补丁。
- “终止任务”不能由 `/kill` 直接写历史；只能由流循环在收口时统一 finalization，一次性决定写入什么。
- 终止后如果没有 final summary，则主气泡显示最后一个 partial preview，并带 `已终止` 标识。
- tool call 必须默认收起，否则过程区会过长。
- 当前仓库仍需兼容旧历史记录；新字段必须全部为可选字段。
- 实施时必须参考官方文档确认 Codex / Claude 的 tool-use 字段定义，不能只靠当前仓库里已有的文本解析逻辑猜测。

## 现状

### 1. 当前 Web 可见的数据形态

[`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 当前 SSE 实际向前端送出的终端事件主要是：

- `meta`
- `delta`
- `status`
- `done`
- `error`

[`front/src/services/realWebBotClient.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/realWebBotClient.ts) 当前只消费：

- `delta.text`
- `status.preview_text`
- `done.output`

因此当前 Web UI 只能看到“预览文本”和“最终文本”，看不到原始 CLI 事件结构，也看不到 tool call。

### 2. 当前历史存储形态

[`bot/models.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/models.py) 的 `UserSession.history` 当前消息结构基本只有：

- `timestamp`
- `role`
- `content`
- `elapsed_seconds`

也就是说：

- 现在不会保存 CLI 流式过程。
- `/kill` 后如果流循环没有补一次最终落盘，这一轮可见内容就会消失。

### 3. 当前终止行为的问题

[`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 里当前 `/kill` 只负责杀进程，且会把 `running_reply` 清掉；而 `_stream_cli_chat()` 的 `finally` 也会清 `running_reply`。因此终止后常见结果是：

- 进程停了
- 页面不再流了
- 但 partial preview 没被写入历史
- 前端刷新后什么都没了

此外，[`front/src/screens/ChatScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx) 当前点击“终止任务”只调用 `/kill`，没有主动中断当前 SSE 读取，也没有在 kill 后等待后端 finalization 再刷新历史，因此体感上会像“点了但卡住”。

### 4. 当前最终显示格式化

[`front/src/screens/ChatScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx) 当前对 assistant 消息的处理是：

- `state=done` 且非 error：走 [`front/src/components/ChatMarkdownMessage.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/ChatMarkdownMessage.tsx)
- `state=streaming` 或 `state=error`：走 [`front/src/components/ChatPlainTextMessage.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/ChatPlainTextMessage.tsx)

Markdown 最终由 [`front/src/components/MarkdownPreview.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/components/MarkdownPreview.tsx) 做渲染和样式包装；流式预览与错误仍是纯文本，不具备结构化过程视图。

## 外部协议参考

本次设计不把 Codex / Claude 的 tool-use 字段写死成“仓库猜测值”，而是明确以官方文档为准：

- OpenAI Function Calling / Responses 官方文档：
  - https://platform.openai.com/docs/guides/function-calling
- OpenAI 内置工具官方文档：
  - https://platform.openai.com/docs/guides/tools-shell
  - https://platform.openai.com/docs/guides/tools-apply-patch
- Anthropic Claude tool use 官方文档：
  - https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/handle-tool-calls
  - https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use

当前已确认的高层约束：

- Claude Messages / tool-use 模型里，assistant 侧 tool 调用以 `tool_use` block 表达，核心字段是 `id`、`name`、`input`；tool 回填使用 `tool_result` block，并通过 `tool_use_id` 关联。
- OpenAI Responses / Codex 路径里，tool 调用不是单一固定类型；除了 `function_call` 之外，还可能出现 `shell_call`、`apply_patch_call` 等内置工具项。

因此第一版实现必须遵守两条规则：

- 统一归一化层只抽象“语义类型”，不把底层 item type 限死成 1 种。
- 未识别事件必须保留为 `unknown` 轨迹项，而不是直接丢弃。

## 方案比较

### 方案 A：只保存 partial preview，不保存过程

- kill 时把 `running_preview_text` 写成 assistant 最终消息。
- 前端继续只有纯文本消息，不新增过程面板。

优点：

- 改动小。
- 能解决“终止后内容丢失”。

缺点：

- 无法回答“Web 端现在到底收到了什么结构化事件”。
- tool call 仍然不可见。
- 之后再补过程视图时需要二次改历史格式。

### 方案 B：引入富事件 trace，但只在前端内存里保留

- SSE 期间显示过程。
- `done` 后只保存最终摘要，不把 trace 落到历史。

优点：

- UI 能看到过程。
- 后端历史结构变动小。

缺点：

- 刷新页面或 kill 后仍会丢过程。
- 与“显示和保存对话”目标不符。

### 方案 C：引入富事件 trace，并把终态 assistant 消息持久化为“摘要 + 过程”

- assistant 历史消息仍以 `content` 作为主显示文本。
- 新增可选 trace 元数据保存过程。
- SSE 增加过程事件，历史接口回传持久化 trace。
- kill 只发停止请求，最终写历史由流循环统一完成。

优点：

- 同时解决“终止后丢失”“tool call 不可见”“最终显示过长”三类问题。
- 兼容旧历史。
- 后续若要做过滤、导出、诊断页，可直接复用 trace。

缺点：

- 改动涉及后端模型、SSE、前端类型与聊天 UI。
- 需要加入严格的 trace 体积控制，避免历史膨胀。

## 已选方案

采用方案 C。

原因：

- 用户已经明确选择富事件方案。
- 只有把 trace 作为 assistant 历史消息的一部分持久化，才能保证 kill、刷新、重新进入页面后仍能看到这一轮的可见内容与过程。
- 默认折叠“查看过程”后，阅读负担仍与当前最终摘要模式接近，不会把主对话流变成长日志。

## 设计细节

### 1. 历史消息模型扩展

在不破坏现有 `role/content/timestamp/elapsed_seconds` 的前提下，为 assistant 历史消息增加可选 `meta`：

```json
{
  "timestamp": "2026-04-14T10:00:00",
  "role": "assistant",
  "content": "最终总结或终止时的最后预览",
  "elapsed_seconds": 12,
  "meta": {
    "completion_state": "completed",
    "summary_kind": "final",
    "trace_version": 1,
    "stream_trace": []
  }
}
```

字段语义：

- `completion_state`
  - `completed`
  - `cancelled`
  - `error`
- `summary_kind`
  - `final`：`content` 来自最终总结
  - `partial_preview`：`content` 来自最后可见预览或取消占位文案
- `trace_version`
  - 第一版固定为 `1`
- `stream_trace`
  - 保存结构化过程事件

如果这一轮被取消且没有任何可见文本，则仍写 assistant 消息，但 `content` 使用固定占位文案：

```text
已终止，未返回可显示文本
```

这样可以保证每一轮用户消息在历史里都有对应 assistant 终态，过程 trace 也有挂载位置。

### 2. 统一 trace 事件模型

后端对不同 CLI 的原始事件做归一化，统一成以下语义类型：

- `preview`
- `tool_call`
- `tool_result`
- `status`
- `cancelled`
- `done`
- `error`
- `unknown`

每个 trace 项建议结构如下：

```json
{
  "kind": "tool_call",
  "cli_type": "codex",
  "time": "2026-04-14T10:00:03.120000",
  "title": "shell",
  "summary": "Get-ChildItem -Force",
  "call_id": "call_123",
  "status": "started",
  "raw_type": "shell_call",
  "payload": {
    "command": "Get-ChildItem -Force"
  }
}
```

字段规则：

- `kind`：统一语义类型
- `cli_type`：`codex | claude | kimi`
- `time`：生成该 trace 项的宿主时间
- `title`：过程面板里展示的短标题
- `summary`：过程面板里默认可见的一行摘要
- `call_id`：tool call / result 关联键，没有则省略
- `status`：如 `started | completed | failed | cancelled`
- `raw_type`：底层原始事件或 item 的类型名
- `payload`：可展开查看的裁剪后结构体

`payload` 不追求完整保真；目标是“足够诊断、不会撑爆历史”。原始事件中无法提炼但又不能丢的信息，进入 `unknown` 轨迹项并附带裁剪后的 `payload`。

### 3. trace 体积控制

第一版必须限制 trace 尺寸，避免 `session.history` 和 assistant 私有状态无限膨胀。规则如下：

- 只记录“有意义事件”，不记录心跳或纯重复状态。
- 连续 `preview` 事件做合并：
  - 只在文本明显变化、跨行、进入/退出 tool 阶段、或距离上次持久化快照超过 1 秒时追加一条。
- 单个 `payload` 内字符串字段裁剪到合理上限，建议 2000 到 4000 字符。
- 单轮 `stream_trace` 建议上限 200 条；超限后：
  - 继续保留最终 summary
  - 追加一条 `status` 事件说明“过程过长，已截断后续细节”
- `content` 始终只保存最终 summary 或最后 preview，不把完整 token 流拼进主消息。

### 4. SSE 协议扩展

保持当前 SSE 总体风格，但新增 `trace` 事件，避免前端只能靠 `delta/status/done` 拼文本。

第一版 SSE 终端事件集合：

- `meta`
- `delta`
- `status`
- `trace`
- `done`
- `error`

语义如下：

- `meta`
  - 保留当前 bot / cli 基础信息
- `delta`
  - 保留给现有纯文本流式路径做兼容
- `status`
  - 保留 `elapsed_seconds`
  - 保留主气泡预览用的 `preview_text`
- `trace`
  - 新增，携带一条统一后的 trace 事件
- `done`
  - 终态事件
  - 除 `output` 外，新增完整的终态 assistant 消息对象，至少包含 `content`、`elapsed_seconds`、`meta`
- `error`
  - 仅用于请求级失败或无法生成可落盘终态的异常

这样前端在 live streaming 期间就能实时显示过程区；最终持久化后，再用历史里的同一份 trace 回填。

### 5. CLI 归一化层

在 [`bot/cli.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py) 现有“只提取文本”的解析逻辑之上，新增一层只服务 Web rich trace 的归一化器。

建议职责边界：

- 继续保留现有 `parse_codex_json_output()` / `parse_claude_stream_json_output()` 供纯文本回退逻辑使用。
- 新增 Web 专用归一化 helper，例如：
  - `normalize_codex_stream_event()`
  - `normalize_claude_stream_event()`
  - `normalize_kimi_stream_chunk()`
- `_stream_cli_chat()` 不再只累计原始文本，而是同时维护：
  - 主预览文本
  - trace collector
  - tool call 关联状态

各 CLI 的第一版目标：

- `codex`
  - 依据 OpenAI 官方文档识别 `function_call`、`shell_call`、`apply_patch_call` 等 tool item。
  - 不要求第一版把每一种 item 都格式化得很漂亮，但必须能区分 tool call / tool result / text / unknown。
- `claude`
  - 依据 Anthropic 官方文档识别 `tool_use` 与对应 `tool_result`。
  - 流式 `content_block_*` 事件中出现的 tool 相关 block 要映射成 trace。
- `kimi`
  - 若当前 CLI 不暴露稳定 tool-use 结构，则先只产出 `preview` / `status` / `done` / `error` / `unknown`。

### 6. 终止与 finalization 语义

这是本次设计最关键的状态机变更。

#### `/kill` 的职责

`/api/bots/{alias}/kill` 不再负责“终止并清空当前回复状态”，而只负责：

- 把 `session.stop_requested` 设为 `True`
- 向进程发送 terminate / kill
- 返回“已发送终止请求”

`/kill` 明确不做：

- 不直接 `add_to_history()`
- 不直接 `clear_running_reply()`
- 不直接把 `is_processing` 最终置为 `False`

这样才能避免 `/kill` 和 `_stream_cli_chat()` 两处同时写历史、相互覆盖或重复写入。

#### 流循环的职责

只有 [`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 的流循环 finalizer 才能决定本轮如何结束：

- 正常完成：
  - `completion_state=completed`
  - `summary_kind=final`
- 用户终止：
  - `completion_state=cancelled`
  - `summary_kind=partial_preview`
- 超时或异常：
  - `completion_state=error`
  - summary 优先用已有可见文本，否则用错误回退文案

并且 finalizer 必须满足：

- 一轮只写一次终态 assistant 历史
- 写完历史后才清 `running_reply`
- 写完历史后才把 `is_processing` 置为 `False`

#### 与 Claude done detector 的关系

本仓库已经存在 Claude done detector。它决定的是“何时可判定本轮逻辑上已完成”；而本设计增加的是“无论自然完成还是用户 kill，如何统一落成终态消息与 trace”。两者不冲突，后者应覆盖 Codex / Claude / Kimi。

### 7. 前端消息模型与页面行为

[`front/src/services/types.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/types.ts) 的 `ChatMessage` 需要扩展可选元数据：

- `completionState?: "completed" | "cancelled" | "error"`
- `summaryKind?: "final" | "partial_preview"`
- `traceVersion?: number`
- `streamTrace?: ChatTraceEvent[]`

#### 主气泡显示规则

- `summary_kind=final`
  - 主气泡显示最终总结
- `summary_kind=partial_preview`
  - 主气泡显示最后预览或取消占位文案
  - 追加 `已终止` 徽标

#### 过程区显示规则

- assistant 消息若存在 `streamTrace`，则在主气泡下方显示一个统一切换入口：
  - `查看过程`
- 默认折叠。
- 展开后显示紧凑过程时间线。
- 其中 `tool_call` / `tool_result` 按“卡片”展示，每张卡片默认再折叠一次，只显示：
  - tool 名称
  - started/completed/failed 状态
  - 一行摘要

展开 tool 卡片后，才展示裁剪后的输入 / 输出 payload。

#### 流式阶段

当前正在生成的 assistant 临时消息也使用同一套 UI 结构：

- 主气泡仍只显示当前 preview 文本
- 下方可展开“查看过程”
- 过程区随着 `trace` 事件流式更新

因此用户能在输出过程中看到 tool call，但不会默认被大段过程占满页面。

### 8. 终止按钮前端交互

[`front/src/screens/ChatScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx) 和 [`front/src/services/realWebBotClient.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/services/realWebBotClient.ts) 需按以下顺序改造：

1. `sendMessage()` 支持 `AbortController`，让当前 SSE 读取可以被前端主动中断。
2. 点击“终止任务”时：
   - 先 abort 当前 SSE 请求
   - 再调用 `/kill`
   - 然后轮询 overview，直到 `isProcessing=false`
   - 最后重新拉历史，拿到 finalization 后的 assistant 消息
3. 轮询期间按钮进入 `终止中...`
4. 如果 kill 请求已发送，但后端还在等子进程退出，则页面可保留一条轻量系统提示，不立刻报错。

这样可以消除“按钮点了像卡住”的感觉，因为前端流读取会立即结束，剩下只是等待后端把终态消息写完。

### 9. 最终渲染与格式化规则

当前“最终 summary 用 Markdown、流式过程用纯文本”的大方向保留，但扩展为三层：

- 主 summary
  - 对 assistant 终态 summary 继续使用 Markdown 渲染
  - 保留当前本地文件链接预览、表格、代码块、引用块等样式处理
- 流式主预览
  - 仍走纯文本，避免未完成 Markdown 反复抖动
- 过程区
  - `preview` / `status` / `cancelled` / `error` 用轻量纯文本时间线
  - `tool_call` / `tool_result` 用结构化卡片

因此最终页面将能明确区分：

- “这是主回答”
- “这是生成过程”
- “这是工具调用”

而不是把所有东西塞进一个 Markdown 气泡里。

### 10. 向后兼容

- 旧历史消息没有 `meta` 时，前端按当前逻辑渲染，不出现“查看过程”。
- 旧版客户端如果仍只消费 `done.output`，新后端仍保留 `output` 字段，不立即打断兼容性。
- 新版客户端读取 `/history` 时，若没有 `meta.stream_trace`，过程区直接隐藏。

## 测试

### 后端测试

[`tests/test_web_api.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/tests/test_web_api.py) 需要补齐以下覆盖：

- kill 后流循环会把最后 preview 与 trace 写入 assistant 历史，而不是丢失。
- `/kill` 自身不写历史，最终只由流循环写一次。
- `completion_state=cancelled` 时：
  - 有 preview 则 `content` 为最后 preview
  - 无 preview 则 `content` 为取消占位文案
- `done` 事件包含终态 assistant 消息对象及其 `meta`。
- trace 中能保存 `preview` / `tool_call` / `tool_result` / `cancelled` / `done` / `error`。
- 未识别事件进入 `unknown` 而不是丢失。
- 旧历史项不带 `meta` 时，history API 仍正常返回。

### 前端测试

[`front/src/test/chat-screen.test.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/chat-screen.test.tsx) 需要补齐：

- 终止按钮点击后会立刻退出 SSE 流式状态，并进入等待 finalization 的轮询状态。
- cancelled assistant 消息默认只显示 summary，过程区折叠。
- 点击“查看过程”可以展开 / 收起。
- tool call 卡片默认折叠，点击后才展开 payload。
- 旧消息没有 trace 时不出现额外 UI。
- 终态 summary 仍保持 Markdown 渲染，不回退成纯文本。

### 客户端测试

[`front/src/test/real-client.test.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/test/real-client.test.ts) 需要补齐：

- `sendMessage()` 能解析新增 `trace` 事件。
- `sendMessage()` 支持 abort，abort 后不会把用户态错误误判成请求失败。
- `done` 事件里的富消息对象会被正确映射到 `ChatMessage`。

## 实施顺序

1. 扩展后端 history 消息模型，定义 `meta` 与 `stream_trace`。
2. 引入 CLI rich trace 归一化层，并补单元测试。
3. 改造 `_stream_cli_chat()` 的 finalization 状态机与 `/kill` 语义。
4. 扩展 history API / SSE `done` 数据结构，并保持兼容字段。
5. 扩展前端类型与 `RealWebBotClient` 的 SSE 解析、abort 控制。
6. 改造聊天页，加入“查看过程”与默认折叠的 tool call 卡片。
7. 跑后端与前端聚焦测试，确认 kill、cancel、legacy message、Markdown summary 四类路径不回退。

## 回归清单

- “终止任务”后，这一轮对话不会消失。
- 终止按钮点击后，前端不会长时间停留在假流式状态。
- assistant 最终 summary 仍能正确渲染 Markdown。
- 旧历史记录不会因为缺少 `meta` 崩溃。
- Claude done detector 现有行为不被这次 finalization 逻辑破坏。
- Codex / Claude 未识别 tool 事件不会导致整个回复变空或 SSE 崩溃。
- 过程区与 tool call 默认折叠，不会显著拉长主聊天流。
