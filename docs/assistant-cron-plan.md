# Assistant Cron 设计方案

日期：2026-04-16

本文是当前仓库可执行的 `Assistant Cron` 方案，已经按现有代码基线改写。旧版里和 Telegram、多入口、旧 API 前缀绑定的部分，不再作为本分支实现依据。

## 1. 结论

`assistant cron` 在当前仓库里不应实现成“独立后台任务”，而应实现成 assistant 统一执行序列里的系统消息。

也就是说：

- Web chat、cron、manual run 必须共享同一个 assistant 串行执行器
- cron 到点时只负责生成一条待执行请求并入队
- 真正执行时仍走 assistant 现有执行链
- cron 默认使用 job 自己的 synthetic session，不污染真人聊天上下文

v1 范围明确收敛为：

- 单 assistant
- 单进程
- 单 worker
- Web-only
- schedule 只支持 `daily` / `interval`

## 2. 当前仓库约束

当前分支里已经稳定存在这些约束：

- 运行时已经是 `Web-only`
- 当前只允许一个 `assistant` bot
- `assistant` 默认工作目录创建后不可修改
- `.assistant/` 已经有 memory / state / capture / proposal / upgrade 体系
- assistant 结束一轮执行后会写 capture，并进入现有收尾流程
- 现在 assistant 模式的 Web chat 仍然按 `(bot_id, user_id)` 直接执行，没有 assistant 全局队列

因此，本功能的真正前置条件不是 scheduler，而是 assistant 统一串行执行模型。

## 3. 旧方案里已经过时的点

以下内容不应继续沿用：

- 把 Telegram 作为当前 v1 的正式入口
- 假设 `manager.start_all()` 已经承担后台服务生命周期
- 使用旧的 `/api/bots/{alias}/cron/...` 路由风格
- 让 coordinator 反调公开 `run_chat(...)`
- 把失败通知默认理解为 Telegram 主动推送

当前仓库版应改成：

- 入口来源只有 `Web chat`、`cron schedule`、`Web admin manual run`
- cron 路由走 `/api/admin/bots/{alias}/assistant/cron/...`
- coordinator 调用 assistant 低层执行器，不回调公开 Web 入口
- 失败可见性优先靠 state / audit / admin UI / 后端日志

## 4. 设计目标

为当前仓库里的 `assistant` bot 增加宿主管理、可审计、可查询的定时任务能力。

v1 只解决：

- job 配置
- `daily` / `interval` 调度
- startup misfire 补跑
- manual run
- 与人工消息统一串行
- state / audit 留痕
- Web 管理接口

v1 不做：

- 多 assistant
- 多进程选主
- 完整 cron 表达式
- 分布式调度
- Telegram 管理命令
- 主动推送通知

## 5. 核心设计

### 5.1 AssistantRuntimeCoordinator

需要新增 assistant 级统一协调器，建议命名为 `AssistantRuntimeCoordinator`。

职责：

- 维护单一 FIFO 队列
- 保证同一时刻只有一个 assistant 执行单元运行
- 接收三类来源：
  - Web chat
  - cron schedule
  - manual run
- 对 interactive 请求返回最终结果
- 对 background 请求返回 `run_id` 和当前状态

没有这层协调器，只补一把锁是不够的。锁只能阻止并发，不能表达统一排队、pending、manual run、补跑这些语义。

### 5.2 assistant 低层执行器

需要把 assistant 的真实执行逻辑从公开 Web 入口里抽出来，形成一个低层执行器，例如：

- `execute_assistant_turn(...)`

它负责复用现在 assistant 模式已有流程：

- managed prompt 同步
- prompt 编译
- CLI 命令构建
- Codex / Claude 输出解析
- capture 写入
- 后续 compaction / managed prompt 收尾

`AssistantRuntimeCoordinator` 只能调用这个低层执行器，不能去反调公开 `run_chat(...)`，否则当 Web chat 也改成先入队后，会出现递归和分层混乱。

### 5.3 cron 的执行语义

cron 到点后的流程应是：

`tick -> build run request -> enqueue -> worker execute -> update state/audit`

这表示：

- scheduler 只负责“什么时候应该有一条请求入队”
- coordinator 决定“什么时候真的执行”
- assistant 忙时 cron 不跳过，而是排队等待当前 turn 结束

### 5.4 synthetic session

cron 不应直接复用真人用户 session。

v1 应为每个 job 分配稳定的 synthetic `user_id`：

- 输入：`assistant_id + job_id`
- 输出：固定负数 `int64`

效果：

- 每个 job 有自己的长期上下文
- 每个 job 可以稳定复用 native CLI session id
- 自动任务不会污染真人聊天线程

## 6. 目录与数据模型

在 `bot/assistant_home.py` 的 `.assistant/` 目录初始化里增加：

- `.assistant/automation/jobs/`
- `.assistant/state/cron/`
- `.assistant/audit/cron/`

职责如下：

- `.assistant/automation/jobs/`
  - 保存 job YAML
- `.assistant/state/cron/`
  - 保存每个 job 的最新运行状态
- `.assistant/audit/cron/`
  - 保存每次运行的 JSONL 审计记录

### 6.1 job 配置

路径：

`<assistant_workdir>/.assistant/automation/jobs/<job_id>.yaml`

示例：

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
    请检查当前仓库状态，输出简短日报，必要时更新 .assistant/memory/working。
execution:
  timeout_seconds: 1800
```

v1 约束：

- `schedule.type` 只支持 `daily` / `interval`
- `misfire_policy` 只支持 `skip` / `once`
- 不开放优先级配置

### 6.2 state

路径：

`<assistant_workdir>/.assistant/state/cron/<job_id>.json`

最小字段建议：

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

### 6.3 audit

路径：

`<assistant_workdir>/.assistant/audit/cron/<job_id>.jsonl`

每行表示一次 run：

```json
{
  "run_id": "",
  "job_id": "",
  "trigger_source": "schedule|manual|startup_misfire",
  "scheduled_at": "",
  "enqueued_at": "",
  "started_at": "",
  "finished_at": "",
  "status": "queued|running|success|error|cancelled",
  "elapsed_seconds": 12.3,
  "queue_wait_seconds": 0.8,
  "timed_out": false,
  "prompt_excerpt": "",
  "output_excerpt": "",
  "error": ""
}
```

## 7. 队列与补跑语义

### 7.1 统一串行

同一 assistant 任一时刻只允许一个执行单元运行。

来源包括：

- Web chat
- cron schedule
- manual run

顺序规则是：

- 单 worker
- FIFO
- 当前执行结束后再取下一个

因此“等待对话结束”的可执行定义是：

- 等待当前这一次 assistant turn 完成
- 而不是等待用户长时间静默

### 7.2 同一 job 的积压策略

v1 固定采用“单 pending”语义：

- job 正在运行时，新 tick 不重复排多个副本
- job 已在队列中等待时，也不重复排多个副本
- 同一 job 只保留一个 pending run
- 重复命中时增加 `coalesced_count`

### 7.3 misfire

触发来源支持：

- `schedule`
- `manual`
- `startup_misfire`

`misfire_policy` v1 只支持：

- `skip`
- `once`

语义：

- `skip`：错过即跳过
- `once`：启动恢复后补一条 run request 入队

## 8. 模块拆分

建议新增这些模块：

- `bot/assistant_runtime.py`
  - assistant 统一队列与 worker
- `bot/assistant_cron_types.py`
  - cron 数据结构、枚举、校验
- `bot/assistant_cron_store.py`
  - job/state/audit 读写
- `bot/assistant_cron.py`
  - 调度循环与 enqueue 逻辑
- `bot/assistant_cron_api.py`
  - 给 Web admin 层复用的服务函数

现有接入点：

- `bot/assistant_home.py`
  - 增加 cron 目录初始化
- `bot/manager.py`
  - 持有 coordinator 与 cron service
- `bot/main.py`
  - 启动和关闭后台服务
- `bot/web/api_service.py`
  - assistant 模式 Web chat 改为通过 coordinator 入队
- `bot/web/server.py`
  - 增加 assistant cron admin 路由

## 9. Web / API 设计

cron 属于 host-managed assistant 能力，应走 admin assistant 路由：

- `GET /api/admin/bots/{alias}/assistant/cron/jobs`
- `POST /api/admin/bots/{alias}/assistant/cron/jobs`
- `PATCH /api/admin/bots/{alias}/assistant/cron/jobs/{job_id}`
- `DELETE /api/admin/bots/{alias}/assistant/cron/jobs/{job_id}`
- `POST /api/admin/bots/{alias}/assistant/cron/jobs/{job_id}/run`
- `GET /api/admin/bots/{alias}/assistant/cron/jobs/{job_id}/runs`

返回约定：

- job 列表返回 `next_run_at`、`last_status`、`pending`、`coalesced_count`
- `run-now` 返回 `run_id` 和 `status`
- run history 返回最近 N 次摘要，不返回整段输出

前端 v1 放在 `Settings` 页的 assistant `Automation` 模块里。

## 10. 测试要求

至少覆盖：

- `.assistant` cron 目录初始化
- job YAML 读写与最小校验
- state / audit 落盘
- synthetic user id 稳定性
- coordinator FIFO 语义
- Web chat 与 cron 共用同一串行器
- startup misfire 的 `skip` / `once`
- 同一 job 单 pending 与 `coalesced_count`
- assistant 不存在时 cron service 不启动
- admin API 的 CRUD / run-now / runs

前端至少覆盖：

- assistant `Settings` 展示 `Automation` 模块
- manual run 走新 API
- 非 assistant bot 不展示 `Automation`

## 11. 实施顺序

推荐顺序：

1. 抽出 assistant 低层执行器
2. 实现 `AssistantRuntimeCoordinator`
3. 让 assistant 模式 Web chat 全量走 coordinator
4. 实现 cron types / store / service
5. 接 manager / main 生命周期
6. 增加 admin API
7. 增加 Settings Automation UI

这个顺序比“先做 scheduler 再补锁”更稳，因为当前真正缺的是 assistant 全局串行语义，不是时间计算本身。

## 12. 最终建议

当前仓库版 `Assistant Cron v1` 应明确为：

- Web-only assistant automation
- 单 assistant、单进程、单 worker
- Web chat / cron / manual run 共用 `AssistantRuntimeCoordinator`
- coordinator 调用 assistant 低层执行器，不回调公开 Web 入口
- job、state、audit 落在 `.assistant/automation/`、`.assistant/state/cron/`、`.assistant/audit/cron/`
- schedule 只支持 `daily` / `interval`
- 失败主要通过 state / audit / admin UI / 日志暴露

这份文档可以作为当前分支的实现依据。
