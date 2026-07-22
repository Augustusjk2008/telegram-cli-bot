# Native agent、Pi 与 Cluster

## 入口和状态

- `bot/sessions.py` 按 `(bot_id, shared_user_id, agent_id)` 保存 session；Web 用户通过 `bot/chat_identity.py:chat_session_user_id()` 归一化。
- `UserSession` 跟踪工作目录、processing state、active subprocess、conversation id，以及 Codex、Claude、native agent session id。
- 原生 session id 持久化到 `.session_store.json`；chat history 由 `bot/web/chat_store.py` 保存。
- 原生 conversation 还保存 `native_session_id`、`native_session_meta` 和 turn 级 `context_usage`；运行态 overlay 留在内存。

## CLI 与原生链路

- Web/shared chat：`bot/web/api_service.py`。
- CLI 命令和参数：`bot/cli.py`、`bot/cli_params.py`。
- 原生入口：`bot/native_agent/service.py`、`turn_state.py`、`ag_ui_mapper.py`。
- Pi 主链：`pi_rpc_client.py`、`pi_events.py`、`pi_session_runtime.py`、`pi_session_store.py`、`pi_workspace_history.py`、`pi_rpc_preflight.py`。
- 本地 Pi 资料位于 `docs/reference/pi/INDEX.md`；只有确认最新版时才查远端。

## 必须保持的行为

- `execution_mode=native_agent` 使用 AG-UI；普通 CLI 保持 `delta/status/trace/done`。
- 长 Web 回复由 Web API streaming/finalize。
- Pi runtime 只能由 `pi_session_runtime.py` 的单 reader 消费 `client.events()`。
- Web rollback 使用本地 `ShadowGitHistory`，不依赖 Pi `workspace_history` RPC。
- Pi session 指纹固定为 `cwd + model_id + pi_agent + reasoning_effort`；任一项变化必须失效旧 session 和 rollback 链。
- 普通 CLI trace 只进入 `ChatTracePanel`；原生来源进入 `NativeAgentTranscript`。
- CLI SSE `meta/status/trace/done` 顶层保留 `turn_id`、`assistant_message_id`。
- 非 cluster chat 只绑定一个 active agent；cluster mode 通过 `@agent_id` 分发 child agents。

## Pi 扩展和环境

- `workspace-history.ts` 来自 `pi-workspace-history@0.2.2`，提供 Pi 侧 `/checkpoint`、`/undo`、`/redo`；Web rollback 仍以 `ShadowGitHistory` 为准。
- `bot/cluster/pi_extension/tcb-cluster.ts` 注册 `cluster_status`、`list_agents`、`ask_agent`、`poll_agent_tasks`、`wait_agent_messages`。
- cluster runtime 依赖 `TCB_CLUSTER_MCP_CONFIG` 和 `TCB_CLUSTER_RUN_ID`，由 Web cluster/native 链路注入。
- Pi 扩展默认位于 `~/.pi/agent/extensions`；设置 `PI_AGENT_SETTINGS` 时使用同目录的 `extensions`；设置 `NATIVE_AGENT_PI_HOME` 时使用该 HOME 下的 `.pi/agent/extensions`。
- `.env` 至少配置 `NATIVE_AGENT_ENABLED=true`、`NATIVE_AGENT_PI_COMMAND=pi`。
- Pi 设置写 `~/.pi/agent/settings.json` 和 `models.json`；Windows 的 `shellPath` 应指向 Git Bash。

非绿色版依赖 Node.js 22+、Git 和 bash。安装固定版本：

```bash
npm install -g @earendil-works/pi-coding-agent@0.74.2 pi-workspace-history@0.2.2
```

安装后把 `pi-workspace-history/.pi/extensions/workspace-history.ts` 和仓库的 `tcb-cluster.ts` 复制到实际 Pi extensions 目录，并运行 `pi --version`。

## 验证

- Pi RPC/runtime：`tests/test_pi_session_runtime.py`、`tests/test_pi_turn_stream.py`。
- Session/history：`tests/test_sessions.py`、`tests/test_session_store.py`、`tests/test_pi_workspace_history.py`。
- AG-UI/聚合：`tests/test_native_agent_ag_ui_mapper.py`、`tests/test_native_agent_aggregator.py`。
- Cluster：`tests/test_cluster_mcp_client.py`、`tests/test_cluster_model_tiers.py`、`tests/test_cluster_cancel.py`。
