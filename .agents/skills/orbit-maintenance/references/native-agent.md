# Native agent、Pi 与 Cluster

## 入口和状态

- `bot/sessions.py` 按 `(bot_id, shared_user_id, agent_id)` 保存 session；Web 用户通过 `bot/chat_identity.py:chat_session_user_id()` 归一化。
- `UserSession` 跟踪工作目录、processing state、active subprocess、conversation id，以及 Codex、Claude、native agent session id。
- 原生 session id 默认持久化到应用数据目录的 `sessions/session_store.sqlite3`；旧 `session_store.json` 仅作迁移源。chat history 由 `bot/web/chat_store.py` 的 SQLite store 保存。
- 原生 conversation 还保存 `native_session_id`、`native_session_meta` 和 turn 级 `context_usage`；运行态 overlay 留在内存。

## CLI 与原生链路

- Web/shared chat：`bot/web/api_service.py`。
- CLI 命令和参数：`bot/cli.py`、`bot/cli_params.py`。
- 原生入口：`bot/native_agent/service.py`、`turn_state.py`、`ag_ui_mapper.py`。
- Pi 主链：`pi_rpc_client.py`、`pi_events.py`、`pi_session_runtime.py`、`pi_session_store.py`、`pi_workspace_history.py`、`pi_rpc_preflight.py`。
- `docs/reference/pi/` 仅作补充资料；当前实现事实以源码、锁定依赖和测试为准。

## 必须保持的行为

- `execution_mode=native_agent` 使用 AG-UI；普通 CLI 保持 legacy SSE `meta/status/trace/done`，增量正文预览放在 `status.preview_text`。
- 两条链路都通过 `StreamingPersistenceBuffer` 写入流式预览和 trace，并由 `complete_turn()` 完成最终持久化。
- Pi runtime 只能由 `pi_session_runtime.py` 的单 reader 消费 `client.events()`。
- Web rollback 使用本地 `ShadowGitHistory`，不依赖 Pi `workspace_history` RPC。
- 目标不变量：Pi session 指纹固定为 `cwd + model_id + pi_agent + reasoning_effort`；任一项变化必须失效旧 session 和 rollback 链。
- 当前实现尚未完全兑现该不变量：runtime 复用只比较 `runtime_key + owner_key + cwd + env`，native metadata 不匹配时也会保留原 session id；修改该链路时必须补齐失效逻辑和回归测试。
- 普通 CLI trace 与原生过程统一进入 `NativeAgentTranscript`；CLI 使用 `mode="cli"`，不得显示原生权限操作。
- CLI SSE `meta/status/trace/done` 顶层保留 `turn_id`、`assistant_message_id`。
- 普通聊天按显式 `agent_id` 路由并隔离 session；启用 Bot 级 cluster 后，主 agent 通过 `tcb-cluster` MCP 动态编组和委派 child-agent 任务，`@agent_id` 不承担集群分发协议。

## Cluster 公共 MCP 链路

- Codex、Claude 和 Pi 使用同一套 cluster runtime、bridge API 与工具契约。
- Codex、Claude 在集群轮次中由 `bot/web/api_service.py` 动态注入 `bot/cluster/mcp_stdio.py` launcher；管理页也可生成对应的 `mcp add/get/remove` 命令。
- Pi 不使用 stdio launcher 注册工具，而由 `bot/cluster/pi_extension/tcb-cluster.ts` 作为宿主适配层，直接调用同一 bridge API。
- 两种适配层都暴露 `configure_team`、`cluster_status`、`list_agents`、`new_agent_session`、`ask_agent`、`poll_agent_tasks`、`wait_agent_messages`。
- `bot/data/prompts/cluster_mode.md` 在底层 agent 会话首轮或集群状态/写入策略变化时拼到用户消息前；连续启用轮次改用 `cluster_turn.md` 只刷新当前 `run_id`，连续关闭轮次不重复提示。MCP tool description 只描述具体工具和参数。
- 每次工具调用必须显式传入当前 `run_id`；适配层通过 `X-TCB-Cluster-Run-Id` header 传给 bridge，不依赖 `TCB_CLUSTER_RUN_ID` 环境变量。
- Pi runtime 仅通过 `TCB_CLUSTER_MCP_CONFIG` 定位 bridge 配置；Codex、Claude 的 stdio launcher 从命令行 `--config` 读取同一配置文件。
- `profile.cluster.enabled` 是当前 Bot 级集群开关；请求体旧 `cluster` 字段仅为兼容输入，不决定是否启动 cluster run。

## Cluster orchestration v2 当前边界

- 动态任务使用主会话编组里的角色名称和职责；物理槽位的旧 `system_prompt` 在这条链路中会被抑制。
- Bot 级 `max_parallel_agents`、`default_timeout_seconds` 和 `write_policy` 进入运行时；`model_tiers`、`reasoning_efforts` 仅覆盖普通 CLI 子任务，Pi 原生子任务不使用这组 CLI 参数。
- `conflict_policy` 以及物理槽位的 `enabled`、`allow_cluster`、`allow_write`、`session_policy`、`timeout_seconds` 当前只被解析、保存或回显，不驱动动态任务执行。
- `ask_agent.allow_write` 当前只按 Bot `write_policy` 校验并记录，不是文件系统或 CLI sandbox 的权限边界。
- `ask_agent.timeout_seconds` 未传时使用 Bot `default_timeout_seconds`；超时是软期限，只在任务状态标记 `deadline_exceeded`，不会强制终止子 agent。

## Pi 扩展和环境

- `workspace-history.ts` 来自 `pi-workspace-history@0.2.2`；Web rollback 仍以本地 `ShadowGitHistory` 为准。
- Pi 实际扩展目录默认是 `~/.pi/agent/extensions`；设置 `PI_AGENT_SETTINGS` 时使用该设置文件同级的 `extensions`；设置 `NATIVE_AGENT_PI_HOME` 时，Pi 子进程从该 HOME 下的 `.pi/agent/extensions` 加载。
- 当前 Web 安装助手只按 `PI_AGENT_SETTINGS` 或宿主用户 HOME 选择 `tcb-cluster.ts` 目标目录，不读取 `NATIVE_AGENT_PI_HOME`；自定义 Pi HOME 时必须确认助手目标与实际加载目录一致。
- 启用原生 agent 需要 `NATIVE_AGENT_ENABLED=true`；`NATIVE_AGENT_PI_COMMAND` 默认是 `pi`，仅在 PATH 不可解析或使用自定义命令时配置。
- Pi 设置默认写 `~/.pi/agent/settings.json` 和同目录的 `models.json`，也支持相应环境变量覆盖；Windows 的 `shellPath` 建议指向 Git Bash。

非绿色版启用 Pi 原生 agent 时依赖 Node.js 22+、Git 和 bash。安装固定版本：

```bash
npm install -g @earendil-works/pi-coding-agent@0.74.2 pi-workspace-history@0.2.2
```

安装后从实际 npm package root 复制 `pi-workspace-history/.pi/extensions/workspace-history.ts`，并从仓库复制 `bot/cluster/pi_extension/tcb-cluster.ts` 到实际 Pi extensions 目录；然后运行 `pi --version`。

## 验证

- Pi RPC/runtime：`tests/test_pi_session_runtime.py`、`tests/test_pi_turn_stream.py`。
- Session/history：`tests/test_sessions.py`、`tests/test_session_store.py`、`tests/test_chat_history_service.py`、`tests/test_chat_store_revision.py`、`tests/test_pi_workspace_history.py`。
- AG-UI/聚合：`tests/test_native_agent_ag_ui_mapper.py`、`tests/test_native_agent_aggregator.py`。
- Cluster：`tests/test_cluster_mcp_schema.py`、`tests/test_cluster_mcp_client.py`、`tests/test_cluster_auto_run.py`、`tests/test_cluster_new_agent_session.py`、`tests/test_cluster_team_config.py`、`tests/test_cluster_model_tiers.py`、`tests/test_cluster_cancel.py`。
