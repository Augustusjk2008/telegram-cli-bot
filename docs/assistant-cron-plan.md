# Assistant Cron 设计方案

本文替代此前“cron 独立后台执行、默认不通知”的方案。

新结论只有一条最重要：cron 不是脱离对话体系的后台任务，而是 assistant 统一执行队列里的系统对话消息。调度器只负责“到点生成一条待执行消息”，真正执行时仍走 assistant 现有对话链路，并且和人工消息串行。

## 1. 结论摘要

这次方案保留原策划案里大部分正确方向：

- 宿主管理配置，不让 assistant 直接修改生效 cron
- 调度器挂在 `MultiBotManager` 生命周期上，不绑某个 Telegram Application
- 执行链复用现有 `run_chat(...)`
- 配置、状态、审计都落到 `.assistant/` 下
- v1 仍然只做单机、单进程、单 assistant

需要调整的是执行语义与范围：

- 不再把 cron 当成“独立跑完就算”的后台任务
- 不再默认静默成功、对话里完全不可见
- 不再把“assistant 忙时直接 skip”作为默认策略
- v1 不开放完整 cron 表达式，只支持 `daily` 和 `interval`

新的默认策略是：

- cron 到点后，先进入 assistant 统一队列
- 如果 assistant 正在处理人工消息或别的 cron，就等待当前这一轮执行结束
- 当前执行结束后，按入队顺序继续处理
- cron 的运行结果必须可审计、可查询，失败默认通知管理员
- 同一 job 忙时不无限积压，只保留一个 pending run

这里把“等待对话结束”具体定义为：等待当前正在执行的那一轮 `run_chat(...)` 结束，而不是等待用户长时间不说话。否则只要用户持续聊天，cron 可能永久不执行。

## 2. 目标

给 `assistant` bot 增加长期、可配置、可审计的定时任务能力。

任务本质仍然是：

- 定时向 assistant 发送一条宿主定义的 prompt

v1 只解决：

- job 配置
- 定时触发（仅 `daily` / `interval`）
- 启动补跑
- 手动立即运行
- 与人工消息统一串行
- 失败记录与基础通知
- Web 管理接口

## 3. 非目标

v1 不做：

- 多 assistant
- 多进程选主
- 分布式高可用
- 通用 DAG / workflow 平台
- 外部 webhook 编排
- assistant 直接修改生效 cron 配置
- 将 cron 强行混入当前真人用户会话上下文
- 完整 cron 表达式语法
- 复杂优先级与多级重试策略

最后一条需要明确：cron 应该进入 assistant 的统一执行序列，但不应默认污染真人聊天上下文。当前系统同时有 Telegram / Web 入口，也没有“唯一真人会话”的稳定定义，所以 v1 仍然使用 job 自己的 synthetic session 承载上下文，只是在调度和可见性上并入统一对话体系。

## 4. 设计原则

- 宿主控制：job 配置由宿主写入 `.assistant/automation/jobs/`，assistant 不能直接让变更自动生效
- 生命周期解耦：cron service 由 `MultiBotManager` 持有，跟 assistant 生命周期绑定
- 执行链复用：真正执行仍走 `run_chat(manager, alias, user_id, user_text)`
- 文件系统优先：配置、状态、审计全部放在 `.assistant/`
- 统一串行：人工聊天、Web chat、手动 run、cron 全部进入 assistant 统一队列
- 可见而不刷屏：成功默认不主动推送整段输出，但必须留痕；失败默认通知管理员
- 上下文隔离：cron 进入统一对话序列，但默认不复用真人用户 session
- 先收敛范围：v1 优先把统一串行与最小调度模型做稳，再扩展更复杂语法

## 5. 核心改动

原方案里最需要修正的不是 cron 表达式，而是执行入口。

### 5.1 从“调度器直接执行”改成“调度器只负责入队”

新模型：

`schedule tick -> 生成 run request -> 入 assistant 队列 -> worker 串行执行 -> 更新 state/audit -> 按策略通知`

这意味着调度器不直接持有 assistant 运行锁，也不直接和 CLI 进程打交道。它只负责判断“什么时候应该有一条 cron 对话消息进入队列”。

### 5.2 新增 assistant 级统一队列

需要新增一个 assistant 级的运行协调器，建议命名为：

- `AssistantRuntimeCoordinator`

它负责：

- 为 assistant 维护单一 FIFO 队列
- 保证同一时刻只有一个执行单元运行
- 接受四类来源的工作项：
  - Telegram 的人工消息
  - Web 的人工消息
  - cron schedule 触发
  - Web 管理页的 manual run
- 对交互型请求返回最终结果，对后台请求返回 `run_id` 和状态

没有这层队列，只做一把锁还不够，因为：

- 锁只能保证“不并发”，不能表达“先来先执行”
- cron 忙时等待和补跑，会退化成很多分散逻辑
- Web / Telegram / cron 无法共享同一套排队语义

### 5.3 “对话的一部分”在 v1 里的精确定义

这里建议把“cron 属于对话”定义成三件事：

- 走和聊天同一条 assistant 执行链
- 进入和聊天同一个 assistant 串行队列
- 产生可查询的对话式运行记录

但不定义为：

- 直接塞进当前真人用户正在使用的 session history

原因很简单：

- 当前没有跨 Telegram / Web 的唯一“主对话线程”
- 把日报、巡检、整理记忆这类 cron prompt 混进真人会话，会明显污染上下文
- job 自己长期复用一个 synthetic session，更适合持续性自动任务

所以 v1 采用：

- 统一队列
- job 级 session
- host 可见的 run 记录

如果未来真的需要“cron 和真人共用一个上下文线程”，那是 v2 的单独能力，不应作为 v1 默认。

## 6. 目录规划

在 `bot/assistant_home.py` 的 `REQUIRED_DIRS` 增加：

- `.assistant/automation/jobs/`
- `.assistant/state/cron/`
- `.assistant/audit/cron/`

目录职责：

- `.assistant/automation/jobs/`
  - job 配置文件
- `.assistant/state/cron/`
  - 每个 job 的运行态
- `.assistant/audit/cron/`
  - 每次运行一行 JSONL 审计

v1 不强制增加独立 queue 落盘目录。队列是进程内结构；程序重启后的补跑由 misfire 规则负责恢复。

## 7. 数据模型

每个 job 一个 YAML 文件：

`/.assistant/automation/jobs/<job_id>.yaml`

推荐字段：

```yaml
id: daily_repo_review
enabled: true
title: Daily Repo Review
schedule:
  type: daily
  time: "09:00"
  timezone: "Asia/Shanghai"
  misfire_policy: "once"
task:
  prompt: |
    请检查当前仓库的改动、测试状态和未完成事项，
    输出一份简短日报，必要时更新 .assistant/memory/working。
execution:
  timeout_seconds: 1800
  session_mode: "persistent"
notify:
  on_success: false
  on_failure: true
  channel: "main_bot_admin"
meta:
  created_by: "web_admin"
  updated_by: "web_admin"
```

`interval` 示例：

```yaml
id: hourly_check
enabled: true
title: Hourly Check
schedule:
  type: interval
  every_seconds: 3600
  misfire_policy: "skip"
task:
  prompt: |
    请检查当前项目状态并输出简短巡检摘要。
execution:
  timeout_seconds: 1800
  session_mode: "persistent"
notify:
  on_success: false
  on_failure: true
  channel: "main_bot_admin"
```

字段说明：

- `schedule.type`
  - v1 只支持 `daily` / `interval`
- `misfire_policy`
  - v1 只支持 `skip` / `once`
- `session_mode`
  - v1 默认使用 `persistent`
  - `ephemeral` 可作为内部预留能力，但不作为 v1 必做项
- `busy_policy`
  - v1 不开放配置
  - 固定语义为：到点先入队，同一 job 最多保留一个 pending run，重复命中只增加 `coalesced_count`

### 7.1 队列工作项

需要明确一个 assistant 统一工作项模型，建议最小字段如下：

```json
{
  "run_id": "run_xxx",
  "source": "telegram|web|cron|manual",
  "bot_alias": "assistant1",
  "user_id": -100123,
  "text": "prompt text",
  "job_id": "daily_repo_review",
  "interactive": false,
  "scheduled_at": "2026-04-13T09:00:00+08:00",
  "enqueued_at": "2026-04-13T09:00:01+08:00"
}
```

字段语义：

- `interactive=true`
  - Telegram / Web 人工消息
  - 提交方等待该工作项执行完成，再拿最终结果
- `interactive=false`
  - cron / manual run
  - 提交方只拿 `queued` / `running` / `completed` 与 `run_id`
- `job_id`
  - 仅 cron / manual run 必填

每个 job 一个运行态文件：

`/.assistant/state/cron/<job_id>.json`

建议字段：

```json
{
  "next_run_at": "",
  "last_scheduled_at": "",
  "last_enqueued_at": "",
  "last_started_at": "",
  "last_finished_at": "",
  "last_success_at": "",
  "last_status": "",
  "last_error": "",
  "current_run_id": "",
  "pending_run_id": "",
  "pending_scheduled_at": "",
  "coalesced_count": 0,
  "last_trigger_source": ""
}
```

审计日志：

`/.assistant/audit/cron/<job_id>.jsonl`

每行建议字段：

```json
{
  "run_id": "",
  "job_id": "",
  "trigger_source": "schedule",
  "scheduled_at": "",
  "enqueued_at": "",
  "started_at": "",
  "finished_at": "",
  "status": "success",
  "elapsed_seconds": 12.3,
  "timed_out": false,
  "queue_wait_seconds": 0.8,
  "prompt_excerpt": "",
  "output_excerpt": "",
  "error": ""
}
```

这里新增 `enqueued_at` 和 `queue_wait_seconds`，是因为 cron 已经不再是“到点立刻执行”，而是“到点入队、按序执行”。

## 8. 运行模型

### 8.1 服务挂载

新增：

- `AssistantCronService`
- `AssistantRuntimeCoordinator`

由 `MultiBotManager` 持有。

生命周期建议：

- `manager.start_all()` 完成后启动 `AssistantRuntimeCoordinator`
- assistant profile 存在时再启动 `AssistantCronService`
- `manager.shutdown_all()` 时先停 cron，再停 coordinator

### 8.2 调度循环

v1 不使用 APScheduler，也不引入完整 cron 表达式解析。

主循环：

1. 启动时扫描 `.assistant/automation/jobs/*.yaml`
2. 按 `daily` / `interval` 规则计算每个 job 的 `next_run_at`
3. 睡眠到最近一次触发时间，或等待配置变更事件
4. 醒来后处理所有到期 job
5. 对每个到期 job 生成 run request，并提交给 `AssistantRuntimeCoordinator`
6. 更新 state 后重新计算下一轮

### 8.3 配置热重载

配置变更后通过一个 `asyncio.Event` 唤醒 cron service 重新加载。

触发来源：

- Web API 新增 / 删除 / 修改 job
- 程序启动后的首次扫描
- 可选的文件时间戳轮询

v1 不要求引入复杂文件监听。

## 9. 执行模型

### 9.1 cron job 的实际执行

cron 触发后不直接发 Telegram 文本，而是创建一个 assistant 工作项：

`job -> queue item -> synthetic_user_id -> run_chat(manager, assistant_alias, synthetic_user_id, prompt)`

### 9.2 synthetic user_id

synthetic user_id 必须稳定且可重复计算。

建议：

- 对 `assistant_id + job_id` 做哈希
- 映射成固定负数 `int64`

效果：

- 每个 job 都有自己的会话
- 每个 job 都能长期复用 CLI session id
- 不会和真人用户串话
- `persistent` 容易实现，未来若要支持 `ephemeral` 也能平滑扩展

### 9.3 为什么不直接复用真人会话

因为这会带来三个问题：

- 无法定义到底复用 Telegram 还是 Web 的哪一个 user_id
- 自动任务会污染人工对话上下文
- 不同 job 的长期上下文会互相干扰

因此 v1 的推荐做法是：

- 调度层并入统一对话队列
- 上下文层仍然按 job 隔离

## 10. 队列语义

这是新方案的关键。

### 10.1 统一串行

同一 assistant 任一时刻只允许一个执行单元运行。

进入统一队列的来源包括：

- Telegram chat
- Web chat
- cron schedule
- manual run

### 10.2 顺序规则

建议采用：

- 单 worker
- FIFO ready queue
- 当前执行中的任务完成后，再取下一个 ready item

这样 cron 的“等待当前对话结束”会被具体化为：

- 如果到点时 assistant 正在跑别的 turn，cron 先入队
- 当前 turn 完成后，cron 作为已入队 item 继续执行
- 在 cron 入队之后才到达的新人工消息，排在 cron 后面

这样可以避免 cron 永远被新消息饿死。

### 10.3 同一 job 的积压策略

如果某个 job 已经：

- 正在运行
- 或已经在队列中等待

这时又来了新的 schedule tick，v1 默认不无限堆积，而是：

- 固定保留一个 pending run
- 重复命中只增加 `coalesced_count`
- 当前 run 结束后最多补跑一次

这相当于原策划案里提过的 `defer_once`，但现在它应当成为默认，而不是预留。

### 10.4 “对话结束”的具体边界

v1 只识别“当前执行中的一轮消息结束”，不识别“用户整段会话结束”。

这点必须写清楚：

- assistant 无法可靠判断用户是不是“真的聊完了”
- 如果等到会话静默再跑，cron 会变成不确定行为

所以可执行定义就是：

- 当前 `run_chat(...)` 完成
- 队列继续取下一项

### 10.5 人工消息与后台任务的返回语义

虽然所有来源都进入同一个 coordinator，但返回语义分两种：

- 人工消息（Telegram / Web chat）
  - 提交后仍等待自己的那条工作项执行完成
  - 外部行为尽量保持与现在一致
- 后台任务（cron / manual run）
  - 提交后立即返回 `run_id`
  - 返回当前状态：`queued` / `running` / `completed`
  - 不要求 HTTP 或 Telegram 调用端长连接阻塞到任务结束

这保证了统一串行与现有交互体验可以同时成立。

## 11. 触发来源与补跑

触发来源支持三种：

- `schedule`
- `manual`
- `startup_misfire`

`misfire_policy` v1 只支持：

- `skip`
- `once`

语义：

- `skip`
  - 错过就跳过
- `once`
  - 启动恢复后补一条 run request 进队列

补跑进入队列后，仍然遵守统一串行和同一 job 的单 pending 语义。

## 12. 通知与可见性

原方案里“单独跑、也不通知”是最不适合 assistant 模式的部分，需要改掉。

v1 建议：

- 每次运行都写 state 和 audit
- 失败默认通知主 bot 管理员
- 成功默认不主动推送完整输出，避免刷屏
- manual run 必须返回排队或执行状态

通知内容只放摘要：

- job 标题
- 触发来源
- 排队等待时间
- 结果状态
- 日志入口 / run_id
- 简短错误摘要

不放整段输出。

“作为对话的一部分”的可见性，在 v1 里主要靠两层：

- job 自己的 persistent synthetic session history
- Web 管理页可查看 run history / last result

如果后面要把 cron turn 直接展示到聊天 UI，可以从 synthetic session 历史继续演进，但 v1 不强行把它插进真人消息流。

## 13. Web / API 规划

建议先做 Web 管理，不急着加 Telegram 管理命令。

接口：

- `GET /api/bots/{alias}/cron/jobs`
- `POST /api/bots/{alias}/cron/jobs`
- `PATCH /api/bots/{alias}/cron/jobs/{job_id}`
- `DELETE /api/bots/{alias}/cron/jobs/{job_id}`
- `POST /api/bots/{alias}/cron/jobs/{job_id}/run`
- `GET /api/bots/{alias}/cron/jobs/{job_id}/runs`

`run-now` 接口要改成队列语义：

- 返回 `run_id`
- 返回当前状态：`queued` / `running` / `completed`
- 若队列中等待，不要求 HTTP 长连接阻塞到完成

前端位置：

- 先放 `Settings` 下新增 `Automation` 区块
- 展示 job 列表、下次运行时间、最近结果、是否排队中
- 详情页展示最近 runs 和失败摘要

## 14. 后端模块拆分

建议拆成：

- `bot/assistant_runtime.py`
  - assistant 统一队列与 worker
- `bot/assistant_cron.py`
  - cron 调度服务与主循环
- `bot/assistant_cron_store.py`
  - job/state/audit 读写
- `bot/assistant_cron_types.py`
  - 数据结构、枚举、校验
- `bot/assistant_cron_api.py`
  - 给 Web/API 层复用的查询和管理函数

现有接入点：

- `bot/manager.py`
  - 生命周期挂载 coordinator 与 cron service
- `bot/assistant_home.py`
  - 目录初始化
- `bot/handlers/chat.py`
  - assistant 模式下改为通过 coordinator 入队
- `bot/web/api_service.py`
  - assistant 模式 Web chat 也通过 coordinator 入队
- `bot/web/server.py`
  - 新增 cron HTTP 路由

这里有一个重要实现要求：

- 不能只让 cron 走 coordinator，而 Telegram / Web 继续直连执行链

否则仍然没有真正的 assistant 全局串行，只是“cron 被动等锁”，语义不完整。

## 15. 测试方案

至少补这些测试：

- `daily` / `interval` 的 `next_run_at` 计算
- Windows / Linux 下路径落盘一致性
- startup misfire 行为
- 同一 job 单 pending 的排队行为
- cron 与人工消息的先后顺序
- 同一 job 重复触发时的 `coalesced_count`
- synthetic `user_id` 稳定性
- `persistent` session 行为
- 执行成功、失败、超时后的 state / audit 更新
- 配置热重载
- assistant 不存在时 cron service 不启动
- manual run 返回 `queued` / `running` 状态

还应增加一类回归测试：

- assistant 模式下 Telegram 和 Web chat 经过 coordinator 后，原有交互结果不变

## 16. 迭代顺序

建议顺序改成：

1. 先实现 `AssistantRuntimeCoordinator`
2. 把 assistant 模式下的 Telegram / Web chat 改为走统一队列
3. 再实现 cron store、scheduler、manual run
4. 接入 `MultiBotManager` 生命周期
5. 加 Web API
6. 加前端 Automation 页面和运行历史
7. 最后再考虑 Telegram 管理命令和 proposal 集成

这个顺序比“先做 cron 再补锁”更稳，因为真正的根问题是 assistant 统一串行，不是 cron 本身。

## 17. 风险

最大风险仍然不是调度时间计算，而是 assistant 运行模型。

主要风险：

- 如果不先统一 assistant 队列，人工消息和 cron 仍可能交错改 `.assistant` 状态
- 如果把 cron 直接混进真人 session，会污染上下文并且很难解释
- 如果把“等待对话结束”定义成等待用户静默，cron 会变成不确定行为
- 如果同一 job 不做 coalesce，长时间忙碌后可能积压大量无价值补跑
- 如果文档不明确说明“这是进程内调度”，用户会误以为它是系统级可靠调度

## 18. 最终建议

新的 v1 方案应当是：

- cron 作为 assistant 统一对话队列里的系统消息
- 与人工消息共享同一串行执行器
- 到点时先入队，忙时等待当前 turn 完成
- 默认保留 job 独立上下文，不污染真人会话
- v1 只支持 `daily` / `interval` 两种 schedule
- 成功可留痕但不刷屏，失败默认通知管理员

这既吸收了原策划案中“宿主控制、文件系统优先、复用执行链”的优点，也采纳了“cron 应属于对话体系、忙时等待而不是静默旁路执行”的关键修正。
