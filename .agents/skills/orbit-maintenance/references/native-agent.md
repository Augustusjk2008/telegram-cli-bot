# CLI、原生 Agent、Pi 与 Cluster

## 入口和状态

- `bot/sessions.py` 按 `(bot_id, shared_user_id, agent_id)` 保存 session；Web 用户通过 `bot/chat_identity.py:chat_session_user_id()` 归一化。
- `UserSession` 跟踪工作目录、processing state、active subprocess、conversation id，以及 Codex、Claude、Antigravity、DeepSeek 和 native agent 的会话绑定。
- 会话快照默认持久化到应用数据目录的 `sessions/session_store.sqlite3`；`session_store.json` 同时用于旧数据迁移、显式 JSON 后端和 SQLite 初始化失败后的回退。后端选择见 `bot/session_store.py`。
- chat history 由 `bot/web/chat_store.py` 的 SQLite store 保存；conversation 保存 `native_session_id`、`native_session_meta`，turn 保存 `context_usage`，运行态 overlay 留在内存。
- Pi 另外通过 `pi_session_store.py` 保存 `native-agent/pi_sessions.json`，包括 session metadata、workspace history head、线性索引和 turn 记录；修改绑定时同时检查 ChatStore、PiSessionStore 和内存 runtime。

## CLI 与原生链路

- Web/shared chat：`bot/web/api_service.py`。
- CLI 命令和参数：`bot/cli.py`、`bot/cli_params.py`。
- CLI 类型包括 `claude`、`codex`、`codex_server`、`antigravity`、`deepseek`；后三者默认命令分别为 `codex`、`agy`、`dsh`。
- `codex_server` 通过 `bot/codex_server/client.py`、`runtime.py` 复用 `codex app-server` 的 stdio JSON-RPC 进程；Web 入口仍进入共享 CLI SSE/持久化链。它与 `codex` 分开保存参数，历史数据 provider 共用 `codex`。
- Antigravity 使用 `agy -p ... --output-format stream-json`，维护 `antigravity_conversation_id`；本地 CLI 集群和远程工作区 MCP 均有入口，远程 Antigravity 集群在 `_effective_cli_params()` 中拒绝。
- DeepSeek Harness 使用本地 headless JSON CLI，支持本地集群；详细协议、patch 和支持边界见 [deepseek-harness.md](deepseek-harness.md)。
- 原生入口：`bot/native_agent/service.py`、`turn_state.py`、`ag_ui_mapper.py`。
- Pi 主链：`pi_rpc_client.py`、`pi_events.py`、`pi_session_runtime.py`、`pi_session_store.py`、`pi_workspace_history.py`、`pi_rpc_preflight.py`。
- `docs/reference/pi/` 仅作补充资料；当前实现事实以源码、锁定依赖和测试为准。

## 必须保持的行为

- `execution_mode=native_agent` 使用 AG-UI；普通 CLI 保持 legacy SSE `meta/status/trace/done`，增量正文预览放在 `status.preview_text`。
- 两条链路都通过 `StreamingPersistenceBuffer` 写入流式预览和 trace，并由 `complete_turn()` 完成最终持久化。
- 普通 CLI trace 与原生过程统一进入 `NativeAgentTranscript`；CLI 使用 `mode="cli"`，不得显示原生权限操作。
- CLI SSE `meta/status/trace/done` 顶层保留 `turn_id`、`assistant_message_id`。
- 普通聊天按显式 `agent_id` 路由并隔离 session；启用 Bot 级 cluster 后，主 agent 通过 `tcb-cluster` MCP 动态编组和委派 child-agent 任务，`@agent_id` 不承担集群分发协议。

## Pi runtime、session 与 rollback

- `pi_session_runtime.py` 的单 reader 消费 `client.events()`，runtime 同时只允许一个活动事件消费者；后续 turn 继续使用该 reader。队列有界，压力下优先保留控制和终止事件，丢失 usage 事件会影响用量完整性。
- runtime 按 owner 串行启动，owner 包含 `(bot_id, user_id, agent_id)`，runtime key 再包含 conversation。空闲淘汰避开 processing、有待处理权限或活动消费者的 runtime；关闭前持久化仍有效的绑定。
- 必须保持的绑定不变量为 `cwd + model_id + pi_agent + reasoning_effort`；任一项变化都应失效旧 session 和 rollback 链。runtime 的 `binding_matches()` 已比较对应的 `cwd + model + agent_id + reasoning_effort`，并比较 `TCB_REMOTE_MCP_CONFIG`；不匹配时清除旧 session id、history head 和线性索引，再创建进程。
- `service.py:_resolve_pi_binding()` 在启动前比较 conversation 与 PiSessionStore 的 metadata，变化时清理两处绑定、失效 conversation 的 workspace history，并关闭已失效 runtime。metadata 还包含系统提示 hash、child-agent 提示 hash、solo profile 和远程工作区指纹；`_persist_runtime_before_close()` 跳过已失效绑定，防止旧状态回写。四项绑定及远程指纹变化的回归位于 `tests/test_remote_workspace_chat.py`。
- `config_fingerprint` 与上述会话绑定分开判断：当前由 models 文件的 mtime/size 加远程配置指纹构成，完整 env 也参与 runtime 复用比较。仅 models 文件指纹或普通 env 变化会重建 runtime，仍可能续接同一 session 和 history。修改配置热更新时需核对这个边界，四项绑定失效要求仍须保持。
- Web rollback 使用本地 `ShadowGitHistory`；远程 SSH 工作区关闭本地 history。rollback 入口再次核对 session metadata；Pi 的 `workspace_history` RPC 不参与 Web 回滚。

## Cluster 公共 MCP 链路

- Codex（含 `codex_server`）、Claude、Antigravity、DeepSeek Harness 和 Pi 使用同一套 cluster runtime、bridge API 与工具契约。
- Codex、Claude 在集群轮次中由 `bot/web/api_service.py` 动态注入 `bot/cluster/mcp_stdio.py` launcher；管理页也可生成对应的 `mcp add/get/remove` 命令。`codex_server` 的注入只修改自身参数块。
- Antigravity 通过 `bot/cluster/setup.py` 管理工作区 `.agents/mcp_config.json` 的 `tcb-cluster` 条目，并用同目录的 `.tcb-cluster-mcp-state.json` 记录管理状态；保留其他 server，遇到用户已有条目或后续修改时报告冲突，关闭集群时仅清理由宿主管理且未被改动的条目。
- DeepSeek 在集群轮次追加 `--patch`，由 `@deepseek-ai/dsh-mcp-client` 调用项目 `mcp_stdio.py --config ...`。管理页准备该 patch，安装、验证、移除命令列表为空；不向用户 Harness 全局配置写入注册项。
- Pi 不使用 stdio launcher 注册工具，而由 `bot/cluster/pi_extension/tcb-cluster.ts` 作为宿主适配层，直接调用同一 bridge API。
- 两种适配层都暴露 `configure_team`、`cluster_status`、`list_agents`、`new_agent_session`、`ask_agent`、`poll_agent_tasks`、`wait_agent_messages`。
- `bot/data/prompts/cluster_mode.md` 在底层 agent 会话首轮或集群状态/写入策略变化时拼到用户消息前；连续启用轮次改用 `cluster_turn.md` 提醒继续使用当前 `run_id`，连续关闭轮次不重复提示。MCP tool description 只描述具体工具和参数。
- `run_id` 由主会话 `conversation_id + cluster_team_revision` 稳定推导；同一主会话与编组在普通轮次和宿主重启后得到同一个 ID，不新增数据库 ID 字段。
- 只有 `configure_team` 实际新增、删除、修改或重新分配角色时才递增编组版本并轮换 `run_id`。无变化请求返回 `changed=false` 和原 ID；普通轮次结束、异常、停止、集群开关切换及宿主重启均不轮换。
- `configure_team` 成功后主 agent 必须查看 `changed`：`changed=true` 时同一轮所有后续工具立即使用响应中的新 `run_id`，`changed=false` 时继续使用原 ID。
- 每次工具调用必须显式传入当前 `run_id`；stdio MCP 和 Pi 适配层不缓存或自动切换 ID，只把本次工具参数通过 `X-TCB-Cluster-Run-Id` header 传给 bridge，也不依赖 `TCB_CLUSTER_RUN_ID` 环境变量。
- Cluster task、进度消息和后台任务仍是内存态，不跨宿主重启持久化。
- Pi runtime 通过 `TCB_CLUSTER_MCP_CONFIG` 定位 bridge 配置；其余 CLI 的 stdio launcher 或 DeepSeek patch 向 `mcp_stdio.py` 传入 `--config`，读取同一 bridge 配置文件。
- `profile.cluster.enabled` 是当前 Bot 级集群开关；请求体旧 `cluster` 字段仅为兼容输入，不决定是否启动 cluster run。

## Cluster 编排配置的执行边界

- 动态任务使用主会话编组里的角色名称和职责；物理槽位的旧 `system_prompt` 在这条链路中会被抑制。
- Bot 级 `max_parallel_agents`、`default_timeout_seconds` 和 `write_policy` 进入运行时；`model_tiers`、`reasoning_efforts` 仅覆盖普通 CLI 子任务，Pi 原生子任务不使用这组 CLI 参数。
- `conflict_policy` 以及物理槽位的 `enabled`、`allow_cluster`、`allow_write`、`session_policy`、`timeout_seconds` 当前只被解析、保存或回显，不驱动动态任务执行。
- `ask_agent.allow_write` 当前只按 Bot `write_policy` 校验并记录，不是文件系统或 CLI sandbox 的权限边界。
- `ask_agent.timeout_seconds` 未传时使用 Bot `default_timeout_seconds`；超时是软期限，只在任务状态标记 `deadline_exceeded`，不会强制终止子 agent。

## Pi 扩展和环境

- `workspace-history.ts` 来自 `pi-workspace-history@0.2.2`；Web rollback 仍以本地 `ShadowGitHistory` 为准。
- 项目默认将 Pi 扩展放在 `~/.pi/agent/extensions`。`pi_rpc_client.py` 将 `NATIVE_AGENT_PI_HOME` 映射到子进程的 `HOME` 和 `USERPROFILE`；使用自定义 HOME 时，扩展应放在该 HOME 下的 `.pi/agent/extensions`。
- Web 安装助手按 `PI_AGENT_SETTINGS` 同级的 `extensions` 或宿主用户 HOME 选择 `tcb-cluster.ts` 目标目录，不读取 `NATIVE_AGENT_PI_HOME`。设置文件覆盖与子进程 HOME 是两个入口，自定义路径时必须确认助手目标与 Pi 实际加载目录一致。
- 启用原生 agent 需要 `NATIVE_AGENT_ENABLED=true`；`NATIVE_AGENT_PI_COMMAND` 默认是 `pi`，仅在 PATH 不可解析或使用自定义命令时配置。
- Pi 设置路径由 `config_store.py` 解析：`PI_AGENT_SETTINGS` 优先于 `NATIVE_AGENT_PI_HOME`，默认写 `~/.pi/agent/settings.json`；`PI_AGENT_MODELS` 可单独覆盖 models 文件，否则使用 settings 同目录的 `models.json`。Windows 的 `shellPath` 建议指向 Git Bash。

非绿色版启用 Pi 原生 agent 时依赖 Node.js 22+、Git 和 bash。安装固定版本：

```bash
npm install -g @earendil-works/pi-coding-agent@0.74.2 pi-workspace-history@0.2.2
```

安装后从实际 npm package root 复制 `pi-workspace-history/.pi/extensions/workspace-history.ts`，并从仓库复制 `bot/cluster/pi_extension/tcb-cluster.ts` 到实际 Pi extensions 目录；然后运行 `pi --version`。

## 验证

- Pi RPC/runtime：`tests/test_pi_session_runtime.py`、`tests/test_pi_turn_stream.py`。
- Pi 绑定失效：`tests/test_remote_workspace_chat.py` 中的 `test_runtime_rejects_changed_binding_and_does_not_resume_old_session`、`test_service_invalidates_persisted_session_and_rollback_chain`；不要只检查 runtime 进程是否重建。
- CLI/provider：`tests/test_cli_streaming.py`、`tests/test_codex_server_runtime.py`、`tests/test_codex_server_config.py`；DeepSeek 定向检查见对应参考。
- Session/history：`tests/test_sessions.py`、`tests/test_session_store.py`、`tests/test_chat_history_service.py`、`tests/test_chat_store_revision.py`、`tests/test_pi_workspace_history.py`。
- AG-UI/聚合：`tests/test_native_agent_ag_ui_mapper.py`、`tests/test_native_agent_aggregator.py`。
- Cluster：`tests/test_cluster_setup.py`、`tests/test_cluster_mcp_schema.py`、`tests/test_cluster_mcp_client.py`、`tests/test_cluster_auto_run.py`、`tests/test_cluster_new_agent_session.py`、`tests/test_cluster_team_config.py`、`tests/test_cluster_model_tiers.py`、`tests/test_cluster_cancel.py`。
