# CLI 与 Cluster

## 入口和状态

- `bot/sessions.py` 按 `(bot_id, shared_user_id, agent_id)` 保存 session；Web 用户通过 `bot/chat_identity.py:chat_session_user_id()` 归一化。
- `UserSession` 跟踪工作目录、processing state、active subprocess、conversation id，以及 Codex、Claude、Antigravity、DeepSeek 的会话绑定。
- 会话快照默认持久化到应用数据目录的 `sessions/session_store.sqlite3`；`session_store.json` 同时用于旧数据迁移、显式 JSON 后端和 SQLite 初始化失败后的回退。后端选择见 `bot/session_store.py`。
- chat history 由 `bot/web/chat_store.py` 的 SQLite store 保存；conversation 保存 provider session ID 和 metadata，turn 保存 `context_usage`，运行态 overlay 留在内存。
- Claude CLI 的 `context_usage` 由 `bot/web/cli_context_usage.py` 按 transcript 最近 assistant usage 估算；窗口优先采用 `result.modelUsage[model].contextWindow`，turn 结束时按 Claude session 与模型记入内存（宿主重启后丢失）。未报告时按模型族回退：Fable/Mythos、Opus/Sonnet 4.6+、Haiku 5+ 为 1M，更早型号 200K，无法识别的模型 256K。

## CLI 链路

- Web/shared chat：`bot/web/api_service.py`。
- CLI 命令和参数：`bot/cli.py`、`bot/cli_params.py`。
- CLI 类型包括 `claude`、`codex`、`codex_server`、`antigravity`、`deepseek`；后三者默认命令分别为 `codex`、`agy`、`dsh`。
- `codex_server` 通过 `bot/codex_server/client.py`、`runtime.py` 复用 `codex app-server` 的 stdio JSON-RPC 进程；Web 入口仍进入共享 CLI SSE/持久化链。它与 `codex` 分开保存参数，历史数据 provider 共用 `codex`。
- Antigravity 使用 `agy -p ... --output-format stream-json`，维护 `antigravity_conversation_id`；本地 CLI 集群和远程工作区 MCP 均有入口，远程 Antigravity 集群在 `_effective_cli_params()` 中拒绝。
- DeepSeek Harness 使用本地 headless JSON CLI，支持本地集群；详细协议、patch 和支持边界见 [deepseek-harness.md](deepseek-harness.md)。

## 必须保持的行为

- CLI 保持 SSE `meta/status/trace/done`，增量正文预览放在 `status.preview_text`。
- CLI 通过 `StreamingPersistenceBuffer` 写入流式预览和 trace，并由 `complete_turn()` 完成最终持久化。
- CLI transcript 展示工具调用、执行结果和上下文用量。
- CLI SSE `meta/status/trace/done` 顶层保留 `turn_id`、`assistant_message_id`。
- 普通聊天按显式 `agent_id` 路由并隔离 session；启用 Bot 级 cluster 后，主 agent 通过 `tcb-cluster` MCP 动态编组和委派 child-agent 任务，`@agent_id` 不承担集群分发协议。

## Cluster 公共 MCP 链路

- Codex（含 `codex_server`）、Claude、Antigravity、DeepSeek Harness 使用同一套 cluster runtime、bridge API 与工具契约。
- Codex、Claude 在集群轮次中由 `bot/web/api_service.py` 动态注入 `bot/cluster/mcp_stdio.py` launcher；管理页也可生成对应的 `mcp add/get/remove` 命令。`codex_server` 的注入只修改自身参数块。
- Antigravity 通过 `bot/cluster/setup.py` 管理工作区 `.agents/mcp_config.json` 的 `tcb-cluster` 条目，并用同目录的 `.tcb-cluster-mcp-state.json` 记录管理状态；保留其他 server，遇到用户已有条目或后续修改时报告冲突，关闭集群时仅清理由宿主管理且未被改动的条目。
- DeepSeek 在集群轮次追加 `--patch`，由 `@deepseek-ai/dsh-mcp-client` 调用项目 `mcp_stdio.py --config ...`。管理页准备该 patch，安装、验证、移除命令列表为空；不向用户 Harness 全局配置写入注册项。
- 公共 MCP 暴露 `configure_team`、`cluster_status`、`list_agents`、`new_agent_session`、`ask_agent`、`cancel_agent_task`、`poll_agent_tasks`、`wait_agent_messages`。
- `bot/data/prompts/cluster_mode.md` 在底层 agent 会话首轮或集群状态/写入策略变化时拼到用户消息前；连续启用轮次改用 `cluster_turn.md` 提醒继续使用当前 `run_id`，连续关闭轮次不重复提示。MCP tool description 只描述具体工具和参数。
- `run_id` 由主会话 `conversation_id + cluster_team_revision` 稳定推导；同一主会话与编组在普通轮次和宿主重启后得到同一个 ID，不新增数据库 ID 字段。
- 只有 `configure_team` 实际新增、删除、修改或重新分配角色时才递增编组版本并轮换 `run_id`。无变化请求返回 `changed=false` 和原 ID；普通轮次结束、异常、停止、集群开关切换及宿主重启均不轮换。
- `configure_team` 成功后主 agent 必须查看 `changed`：`changed=true` 时同一轮所有后续工具立即使用响应中的新 `run_id`，`changed=false` 时继续使用原 ID。
- `extend` 只占用空闲槽位、不改动已有分配，子任务运行中也允许；`ClusterRuntime.rekey_run()` 保留同一个运行态对象及其任务、消息游标，Web API 同步把 `_ClusterRunControl` 迁到新 `run_id`，旧 ID 作为内部别名供在途子任务继续上报。旧 ID 可读；`ask_agent`、`cancel_agent_task`、`new_agent_session` 拒绝旧 ID 并返回 `cluster_run_changed` 及当前 ID，`configure_team` 返回 `cluster_team_changed` 及当前 ID。`replace` 可能重新分配忙碌槽位，仍需等主会话子任务结束（`cluster_team_busy`）。
- 每次工具调用必须显式传入当前 `run_id`；stdio MCP 适配层不缓存或自动切换 ID，只把本次工具参数通过 `X-TCB-Cluster-Run-Id` header 传给 bridge，也不依赖 `TCB_CLUSTER_RUN_ID` 环境变量。
- Cluster task、进度消息和后台任务仍是内存态，不跨宿主重启持久化。
- 子任务结束后唤醒主会话的通知为英文，只列 task_id 并要求主 agent 用 `poll_agent_tasks(task_ids=...)` 读取结果，不内联子 agent 输出。是否通知只看主 agent 是否已读到结果，不设时间窗口：`poll_agent_tasks` 返回终态任务或 `wait_agent_messages` 返回其 `final` 消息即记为已读（`result_observed`）。未读的子任务无论在主 agent 轮次中还是轮次结束后结束都会通知；轮次中结束的先挂起，由 `_finish_cluster_parent_turn()` 在主会话空闲后投递，投递前已读的不再通知。bridge 不区分调用方；与 `adopt_unfinished_tasks()` 和 `wait_agent_messages` 的托管游标相同，这两个工具的读取都按主 agent 读取处理。
- 通知只覆盖最近一次用户请求：`_start_cluster_run_if_requested()` 按 `session._execution_id` 递增主会话的请求代数（无尽模式各次尝试共用同一代），内部续接轮次不递增；旧请求的子任务只有在最新请求中被 `poll_agent_tasks` 查询且仍未结束时才转入当前请求。主 agent 状态按主会话保存在 `ClusterRuntime`，`configure_team` 轮换 `run_id` 后仍然有效。
- CLI stdio launcher 或 DeepSeek patch 向 `mcp_stdio.py` 传入 `--config`，读取 cluster bridge 配置文件。
- `profile.cluster.enabled` 是当前 Bot 级集群开关；请求体旧 `cluster` 字段仅为兼容输入，不决定是否启动 cluster run。

## Cluster 编排配置的执行边界

- 动态任务使用主会话编组里的角色名称和职责；物理槽位的旧 `system_prompt` 在这条链路中会被抑制。
- Bot 级 `max_parallel_agents`、`default_timeout_seconds` 和 `write_policy` 进入运行时；CLI（含 DeepSeek）共用低、中、高、专业四档 `model_tiers`、`reasoning_efforts` 配置。专业档用于特殊工作，主 Agent 只有在用户明确提出使用专业档时才选择它。子任务按入队时的配置快照覆盖模型和思考深度，空档位继承主 Agent 配置，不修改主 Bot。
- 管理页各执行后端共用集群配置面板。CLI 模型和思考深度选项来自各自参数 schema。
- `conflict_policy` 以及物理槽位的 `enabled`、`allow_cluster`、`allow_write`、`session_policy`、`timeout_seconds` 当前只被解析、保存或回显，不驱动动态任务执行。
- `ask_agent.allow_write` 当前只按 Bot `write_policy` 校验并记录，不是文件系统或 CLI sandbox 的权限边界。
- `ask_agent.timeout_seconds` 未传时使用 Bot `default_timeout_seconds`；超时是软期限，只在任务状态标记 `deadline_exceeded`，不会强制终止子 agent。主 agent 可通过 `cancel_agent_task(task_id)` 精确停止一个排队或运行中的子任务，不影响同一 run 的其他任务。

## 验证

- CLI/provider：`tests/test_cli_streaming.py`、`tests/test_codex_server_runtime.py`、`tests/test_codex_server_config.py`；DeepSeek 定向检查见对应参考。
- Session/history：`tests/test_sessions.py`、`tests/test_session_store.py`、`tests/test_chat_history_service.py`、`tests/test_chat_store_revision.py`。
- Cluster：`tests/test_cluster_setup.py`、`tests/test_cluster_mcp_schema.py`、`tests/test_cluster_mcp_client.py`、`tests/test_cluster_auto_run.py`、`tests/test_cluster_new_agent_session.py`、`tests/test_cluster_team_config.py`、`tests/test_cluster_model_tiers.py`、`tests/test_cluster_cancel.py`、`tests/test_cluster_parent_wakeup.py`。
