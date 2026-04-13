# Claude Done Detector Design

日期：2026-04-13

## 目标

解决 Claude CLI 在本项目中“已经完成回答，但进程迟迟不退出”的问题，尤其覆盖 team agent 等更容易挂住的场景。

本次设计目标：

- 为 Claude 每一轮对话注入一个宿主生成的唯一结束标记。
- 在宿主侧基于“显式标记 + 短静默窗口”判断本轮是否真正完成。
- 完成判定后优雅终止 Claude，避免一直卡住等待进程自行退出。
- Telegram 和 Web 两条 Claude 路径都支持该机制。
- 标记对用户完全不可见，也不进入任何持久化历史。

## 已确认边界

- 该能力只对 `claude` 生效，不改 `codex`、`kimi`。
- 该能力必须是实验开关，不可做成 Claude 全局默认且不可关闭。
- 结束判定不能依赖“完成了 / done / 已结束”等自然语言语义。
- sentinel 出现后不能立刻 kill，必须进入短暂 quiet window。
- quiet window 内如果又出现新的非空正文输出，要取消本次完成判定。
- Telegram 路径和 Web 路径都要支持，不能只改一条链路。
- Web 非流式 `run_cli_chat()` 不能继续只依赖 `communicate(timeout=...)`。
- sentinel 必须从所有用户可见面和持久化面完全剥离：
  - Telegram 最终消息
  - Web SSE preview / done output
  - Web 非流式 output
  - `session.history`
  - assistant capture / compaction 输入

## 现状

### Claude 输出形态

- [`bot/cli.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/cli.py) 已支持 Claude `stream-json` 解析：
  - `parse_claude_stream_json_line()`
  - `parse_claude_stream_json_output()`
- 当前 Claude 可见文本主要来自两类事件：
  - `stream_event -> content_block_delta -> text_delta`
  - `assistant` / `result` 事件里的完成文本

### Telegram Claude 路径

- [`bot/handlers/chat.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py) 中：
  - `handle_text_message()` 负责拼装 prompt、启动进程、写入 session history。
  - `stream_claude_json_output()` 当前走 `_stream_json_cli_output()`，已经是流式读取 stdout。
- 这条链路适合直接增加 done detector 状态机。

### Web Claude 路径

- [`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 中：
  - `_stream_cli_chat()` 已经是增量读 stdout，适合接 done detector。
  - `run_cli_chat()` 对 Claude 仍依赖 `_communicate_claude_process()`，而后者仍走 `communicate(timeout=...)`。
- 如果不改 `run_cli_chat()`，Web 只会在 SSE 场景提前收口，非流式接口仍可能卡住。

### Prompt 注入位置

- Telegram：
  - `handle_text_message()` 会在 assistant 模式下先执行 `compile_assistant_prompt()`，再调用 `build_cli_command()`。
- Web：
  - `_stream_cli_chat()` 和 `run_cli_chat()` 会在 assistant 模式下先经过 `_prepare_assistant_prompt()`，再调用 `build_cli_command()`。

因此 done sentinel 最合适的注入点是：

- assistant prompt 已完成编译之后
- CLI 命令构造之前

## 方案比较

### 方案 A：Claude 专用共享 done-protocol 模块

- 新增一个 Claude 专用 helper，负责：
  - nonce 生成
  - prompt 注入
  - sentinel 剥离
  - done detector 状态机
- Telegram 和 Web 共用该 helper。
- Web 非流式 Claude 路径改为与流式路径共用同类增量 collector，而不再只用 `communicate()`。

优点：

- 逻辑集中，行为一致。
- 回退简单，只受实验开关控制。
- 最符合“Telegram/Web 一起改、并且不靠纯进程退出”的要求。

缺点：

- 需要改动 Web 非流式 Claude 收集逻辑，不是最小改动。

### 方案 B：只改 Telegram 和 Web SSE

- Telegram 流式路径和 Web SSE 路径增加 detector。
- `run_cli_chat()` 继续保留 `communicate()`。

优点：

- 改动最小，短期风险低。

缺点：

- Web 非流式路径仍可能挂住。
- 不满足“Web 也要支持提前收口”的完整要求。

### 方案 C：重构成所有 CLI 共用的统一 collector 框架

- 把 Codex / Claude / Kimi 的 stdout 收集统一重写，再把 Claude done detector 作为插件挂入。

优点：

- 长期结构最整齐。

缺点：

- 会扩大本次变更范围。
- 把与问题无关的 CLI 一并卷入，回归面过大。

## 已选方案

采用方案 A：Claude 专用共享 done-protocol 模块。

原因：

- 需求明确只解决 Claude 挂住问题，不需要把 Codex/Kimi 一并泛化。
- Telegram 和 Web 都能接入同一套规则，避免出现“某一条路判定方式不同”的后续维护问题。
- 通过共享模块可以把 prompt 注入、状态机、剥离和优雅终止收敛为一处实现，降低误判和回退成本。

## 总体架构

新增一个 Claude 专用模块，例如：

[`bot/claude_done.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/claude_done.py)

该模块只负责 Claude done protocol，不承担通用 CLI 职责。

建议包含以下职责：

1. 读取实验配置并判断当前轮是否启用。
2. 生成每轮唯一 nonce 与 sentinel 文本。
3. 为 Claude prompt 追加宿主协议说明。
4. 维护增量状态机，检测“最后一个非空行 == sentinel”。
5. 剥离 preview / final output 中的 sentinel。
6. 在 quiet window 满足后返回“可提前收口”的判定。

建议包含以下数据结构：

- `ClaudeDoneConfig`
- `ClaudeDoneSession`
- `ClaudeDoneDetector`

这些名字仅是建议，实现时可以按仓库风格调整。

## Prompt 注入设计

### 启用条件

同时满足以下条件时才注入：

- `cli_type == "claude"`
- `CLAUDE_DONE_DETECTOR_ENABLED=true`
- `CLAUDE_DONE_SENTINEL_MODE=nonce`

不满足时，Claude 保持当前行为。

### 注入内容

宿主在本轮 prompt 末尾追加一段固定协议说明，要求 Claude：

- 当它完全结束本轮任务时
- 在最终回复末尾
- 单独输出一行当前轮唯一 sentinel
- sentinel 必须是最后一个非空行
- 输出 sentinel 后不要再继续输出正文

要求宿主注入的是当前轮实际 sentinel，例如：

```text
__TCB_DONE_<nonce>__
```

其中 `<nonce>` 由宿主生成，保证本轮唯一。

### nonce 作用域

- 作用域是“单个用户轮次”。
- 同一轮内如果 Claude 因 session 恢复失败而自动重试，沿用同一个 nonce。
- 下一轮用户消息必须生成新的 nonce。

### 不修改宿主管理文件

本次设计明确：

- 不把 done sentinel 协议写入 workdir 根的 `AGENTS.md` / `CLAUDE.md`
- 不把该协议做成永久系统规则

原因：

- 这是宿主实验能力，不应污染长期身份文件。
- 一旦实验需要回退，只关闭 env 即可，不需要重写宿主文件。

## 输出收集与状态机

### 检测对象

done detector 检测的不是原始 stdout 字节流，而是“Claude 可见文本流”。

具体规则：

- `delta_text` 到来时，追加到当前可见文本缓冲。
- `completed_text` 到来时，用其作为当前最终文本快照。
- `error_text` 不触发完成判定，但仍可进入最终错误文本回退路径。
- JSON 元数据、system 事件不视为“继续输出正文”。

### 状态

状态机只有三个状态：

- `idle`
- `done_pending`
- `completed`

### 进入 `done_pending`

当当前文本的“最后一个非空行”精确匹配本轮 sentinel 时，进入 `done_pending`。

精确匹配要求：

- 独占一行
- 与本轮 sentinel 完全相等
- 不接受前后拼接额外字符

### quiet window

进入 `done_pending` 后：

- 记录进入时间
- 继续监听 stdout
- 等待 `CLAUDE_DONE_QUIET_SECONDS`

若在 quiet window 内没有新的非空正文输出，则进入 `completed`。

### 取消完成判定

如果在 `done_pending` 期间又收到新的非空正文输出：

- 取消本次完成判定
- 清空 pending 计时
- 回到 `idle`

这可覆盖以下场景：

- Claude 先输出 sentinel，又继续追加正文
- team agent 中间有额外补充
- Claude 对协议遵守不稳定，误把 sentinel 提前发出

### 处理分片输出

sentinel 可能被拆在多个 `delta_text` 分片里到达。

因此检测逻辑必须基于“累计后的当前文本”判断最后一个非空行，而不能假设 sentinel 总是一次性完整出现在单个 JSON 事件中。

## 提前收口后的进程处理

### 原则

- sentinel 一出现时，不立即终止进程。
- quiet window 满足后，先优雅终止。
- 如果 Claude 仍不退出，再走现有兜底 kill 路径。

### 建议流程

1. detector 进入 `completed`
2. 宿主进入本轮 `done_pending` 的“收口完成”分支
3. 调用 `process.terminate()`
4. 短暂等待进程退出
5. 如仍未退出，再走现有 `kill` / 进程树终止逻辑

### returncode 语义

如果进程是因为宿主在 detector 完成后主动终止：

- 不应把它视为用户可见失败
- Telegram / Web 最终 UI 应按“本轮正常完成”展示

但原始 returncode 仍可用于日志诊断。

## 文本剥离规则

### 剥离对象

sentinel 必须从以下位置全部移除：

- Telegram 处理中 preview
- Telegram 最终回复
- Web SSE `status.preview_text`
- Web SSE `done.output`
- Web 非流式 `run_cli_chat()` 的 `output`
- `session.history`
- assistant capture
- 后续 compaction 输入

### 剥离方式

只移除“独占一行且精确等于当前轮 sentinel”的非空行。

不做以下模糊处理：

- 不移除普通正文中看起来像 `done`
- 不移除别的 nonce
- 不移除用户原文中的相似字符串

### preview 行为

如果当前 preview 的最后一行是 sentinel：

- preview 对用户显示时应当省略这一行
- 但 detector 内部仍保留其判定信息

## Telegram 接入设计

### Prompt 注入

在 [`bot/handlers/chat.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/chat.py) 的 `handle_text_message()` 中：

- assistant prompt 编译完成后
- 调用 `build_cli_command()` 之前
- 对 Claude 追加 done protocol

### 输出读取

当前 `stream_claude_json_output()` 已是流式读取，可直接挂 detector。

建议把 Claude 路径从当前通用 `_stream_json_cli_output()` 的纯“整段 parse + 定时 preview”逻辑中抽出，或者给通用逻辑增加 Claude 专属 hook，至少支持：

- 每次消费新行时更新 detector
- preview 使用剥离后的文本
- detector 完成后提前收口，不再单纯等待进程自己退出

### 最终回复

最终发给 Telegram 的 assistant 文本必须是剥离后的文本。

如果剥离后为空：

- 超时场景仍使用现有 `timeout_no_output`
- 非超时场景仍使用现有 `no_output`

## Web 接入设计

### SSE 路径

在 [`bot/web/api_service.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/api_service.py) 的 `_stream_cli_chat()` 中：

- Claude prompt 注入 done protocol
- 增量读取 stdout 时更新 detector
- `status.preview_text` 使用剥离后的 preview
- detector 完成后提前收口

### 非流式路径

在同文件的 `run_cli_chat()` 中：

- Claude 不能继续只走 `_communicate_claude_process()` -> `communicate()`
- 应改为使用与 SSE 同类的增量 collector，只是不产出中间事件

目标是让 Web 非流式 Claude 也能：

- 在 sentinel + quiet window 后提前收口
- 不被进程迟迟不退出拖住整个 HTTP 请求

### 共用 collector

建议抽一个只服务于 Claude 的共享 collector helper，供：

- `stream_claude_json_output()`
- `_stream_cli_chat()`
- `run_cli_chat()` 的 Claude 分支

共同复用。

这样可以避免 Telegram / Web 三处维护三套 detector。

## 配置设计

在 [`bot/config.py`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/config.py) 中新增：

- `CLAUDE_DONE_DETECTOR_ENABLED`
- `CLAUDE_DONE_QUIET_SECONDS`
- `CLAUDE_DONE_SENTINEL_MODE`

建议语义如下：

- `CLAUDE_DONE_DETECTOR_ENABLED`
  - `true` 时启用实验能力
  - 默认 `false`
- `CLAUDE_DONE_QUIET_SECONDS`
  - 浮点或整数秒数
  - 默认 `2`
  - 建议允许 `1.5` 到 `3` 之间的值
- `CLAUDE_DONE_SENTINEL_MODE`
  - 第一版只支持 `nonce`
  - 其他值视为关闭并记录日志

## 超时与手动终止

### 硬超时

保留现有 `CLI_EXEC_TIMEOUT` 作为硬超时，不因 detector 而移除。

### 软超时

第一版只做保守设计，不主动自动收口。

可选行为：

- 如果 Claude 已有输出，但长期静默且未出现 sentinel，可记一条日志。
- 如后续需要再考虑是否增加轻量状态提示。

第一版不做：

- 软超时自动 kill
- 软超时语义推断完成

### 手动 `/kill`

保留现有手动终止能力。

无论 detector 是否启用：

- 用户手动停止仍优先级更高
- 手动停止会直接终止进程

## 会话与历史语义

### user history

`session.add_to_history("user", ...)` 继续保存原始用户输入，不保存注入后的宿主协议 prompt。

### assistant history

`session.add_to_history("assistant", ...)` 只能保存剥离 sentinel 后的文本。

### assistant session 初始化

`should_mark_claude_session_initialized()` 与 `should_reset_claude_session()` 的判断应继续基于“剥离后的最终文本 + returncode”进行，避免 sentinel 干扰原有 session 管理逻辑。

## 可观察性

建议增加调试日志，但不把 sentinel 暴露给最终用户。

建议记录：

- 本轮 detector 是否启用
- nonce 是否生成
- detector 是否命中 sentinel
- 是否进入 `done_pending`
- 是否因 quiet window 满足而提前收口
- 是否在 pending 后被新正文取消
- 是否在优雅终止后仍需强杀

日志中可以记录 nonce 的短前缀用于排障，但不要把完整带 sentinel 的文本回显到用户界面。

## 测试策略

### 单元测试

- 生成的 sentinel 含唯一 nonce，且格式符合 `__TCB_DONE_<nonce>__`
- detector 在“最后一个非空行精确匹配 sentinel”时进入 `done_pending`
- quiet window 满足后进入 `completed`
- sentinel 后又出现新的非空正文时，取消完成判定
- sentinel 被多个 `delta_text` 分片拆开时仍能识别
- `completed_text` 覆盖 delta 快照时不会造成重复文本
- 剥离函数只移除当前轮精确匹配 sentinel 的独立行
- preview 剥离后不会把 sentinel 暴露给用户
- detector 关闭时，prompt 不注入 sentinel

### 集成测试

- Telegram Claude 流式路径在出现 sentinel 且 quiet window 满足后可提前收口
- Web SSE Claude 路径在相同条件下可提前收口
- Web 非流式 `run_cli_chat()` 的 Claude 分支不再死等进程退出
- 提前收口后最终返回给用户的文本不含 sentinel
- `session.history` 中 assistant 文本不含 sentinel
- assistant capture / compaction 输入不含 sentinel
- detector 关闭时，Telegram / Web Claude 行为回到当前实现
- manual kill 仍可中断启用 detector 的 Claude 任务

## 风险与取舍

### 风险

- Claude 可能不总是严格把 sentinel 放在最后一个非空行。
- Claude 可能偶尔输出 sentinel 后又继续补充正文，导致多次进入/退出 `done_pending`。
- 宿主主动终止后，进程退出码可能变成非 0，需要避免 UI 误报失败。
- Web 非流式路径的 collector 改造如果处理不慎，可能影响当前超时和错误回退行为。

### 取舍

- 本次优先保证可靠收口和可回退，不追求把所有 CLI 收集逻辑一次性统一。
- 先把 detector 做成 Claude 专用、实验开关控制的能力。
- 软超时第一版只保守记录，不做额外自动行为，避免引入新误判。

## 实施顺序

1. 在 `config.py` 增加 Claude done detector 配置。
2. 新增 `bot/claude_done.py`，封装 sentinel 生成、prompt 注入、剥离、状态机。
3. 接入 Telegram Claude 流式路径。
4. 接入 Web SSE Claude 流式路径。
5. 改造 Web 非流式 Claude 路径，移除对纯 `communicate()` 的依赖。
6. 调整最终文本、history、assistant capture 的剥离逻辑。
7. 补齐单元测试与集成测试。
8. 视测试结果再决定是否补充轻量软超时提示。
