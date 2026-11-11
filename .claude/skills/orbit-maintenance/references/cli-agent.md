# CLI and Cluster

## Entry points and state

- `bot/sessions.py` stores sessions by `(bot_id, shared_user_id, agent_id)`; Web users are normalized through `bot/chat_identity.py:chat_session_user_id()`.
- `UserSession` tracks the working directory, processing state, active subprocess, conversation id, and the session bindings for Codex, Claude, Antigravity and DeepSeek.
- Session snapshots are persisted by default to `sessions/session_store.sqlite3` in the app data directory; `session_store.json` serves legacy data migration, the explicit JSON backend, and the fallback after SQLite initialization fails. Backend selection is in `bot/session_store.py`.
- Chat history is stored by the SQLite store in `bot/web/chat_store.py`; a conversation stores the provider session ID and metadata, a turn stores `context_usage`, and the runtime overlay stays in memory.
- The Claude CLI `context_usage` is estimated by `bot/web/cli_context_usage.py` from the most recent assistant usage in the transcript; the window prefers `result.modelUsage[model].contextWindow`, recorded in memory per Claude session and model when the turn ends (lost on host restart). When it is not reported, the fallback is by model family: 1M for Fable/Mythos, Opus/Sonnet 4.6+ and Haiku 5+, 200K for earlier models, and 256K for unrecognized models.

## CLI chain

- Web/shared chat: `bot/web/api_service.py`.
- CLI commands and parameters: `bot/cli.py`, `bot/cli_params.py`.
- CLI types are `claude`, `codex`, `codex_server`, `antigravity` and `deepseek`; the default commands of the last three are `codex`, `agy` and `dsh` respectively.
- `codex_server` reuses the stdio JSON-RPC process of `codex app-server` through `bot/codex_server/client.py` and `runtime.py`; the Web entry still goes through the shared CLI SSE/persistence chain. Its parameters are stored separately from `codex`, and its history data shares the `codex` provider.
- Antigravity uses `agy -p ... --output-format stream-json` and maintains `antigravity_conversation_id`; both the local CLI cluster and the remote workspace MCP have entry points, and remote Antigravity clusters are rejected in `_effective_cli_params()`.
- DeepSeek Harness uses the local headless JSON CLI and supports local clusters; for the detailed protocol, patch and support boundaries see [deepseek-harness.md](deepseek-harness.md).

## Behavior that must be preserved

- CLI keeps SSE `meta/status/trace/done`, with the incremental body preview in `status.preview_text`.
- CLI writes the streaming preview and trace through `StreamingPersistenceBuffer`, and `complete_turn()` performs the final persistence.
- The CLI transcript displays tool calls, execution results and context usage.
- The top level of CLI SSE `meta/status/trace/done` retains `turn_id` and `assistant_message_id`.
- Ordinary chat is routed by the explicit `agent_id` with isolated sessions; once the Bot-level cluster is enabled, the main agent forms the team and delegates child-agent tasks dynamically through the `tcb-cluster` MCP, and `@agent_id` does not carry the cluster dispatch protocol.

## Shared cluster MCP chain

- Codex (including `codex_server`), Claude, Antigravity and DeepSeek Harness use the same cluster runtime, bridge API and tool contract.
- For Codex and Claude, `bot/web/api_service.py` dynamically injects the `bot/cluster/mcp_stdio.py` launcher in cluster turns; the admin page can also generate the corresponding `mcp add/get/remove` commands. Injection for `codex_server` only modifies its own parameter block.
- Antigravity manages the `tcb-cluster` entry of the workspace `.agents/mcp_config.json` through `bot/cluster/setup.py`, and records the management state in `.tcb-cluster-mcp-state.json` in the same directory; it keeps other servers, reports a conflict when the user already has an entry or modifies it later, and when the cluster is disabled it only cleans up entries that the host manages and that have not been changed.
- DeepSeek appends `--patch` in cluster turns, and `@deepseek-ai/dsh-mcp-client` calls the project's `mcp_stdio.py --config ...`. The admin page prepares that patch, and the install, verify and remove command lists are empty; no registration is written to the user's global Harness configuration.
- The shared MCP exposes `configure_team`, `cluster_status`, `list_agents`, `new_agent_session`, `ask_agent`, `cancel_agent_task`, `poll_agent_tasks` and `wait_agent_messages`.
- `bot/data/prompts/cluster_mode.md` is prepended to the user message on the first turn of the underlying agent session or when the cluster state/write policy changes; consecutive enabled turns use `cluster_turn.md` instead, as a reminder to keep using the current `run_id`, and consecutive disabled turns do not repeat the prompt. MCP tool descriptions only describe the specific tool and its parameters.
- `run_id` is derived stably from the main conversation's `conversation_id + cluster_team_revision`; the same main conversation and team yield the same ID across ordinary turns and host restarts, and no database ID field is added.
- The team revision is incremented and `run_id` rotated only when `configure_team` actually adds, removes, modifies or reassigns a role. A request with no change returns `changed=false` and the original ID; the end of an ordinary turn, exceptions, stops, toggling the cluster switch and host restarts never rotate it.
- After `configure_team` succeeds, the main agent must check `changed`: with `changed=true`, all subsequent tools in the same turn immediately use the new `run_id` from the response; with `changed=false`, they keep using the original ID.
- `extend` only takes free slots and does not touch existing assignments, and it is allowed while child tasks are running; `ClusterRuntime.rekey_run()` keeps the same runtime object with its tasks and message cursors, the Web API moves `_ClusterRunControl` to the new `run_id` in step, and the old ID remains an internal alias so in-flight child tasks can keep reporting. The old ID is readable; `ask_agent`, `cancel_agent_task` and `new_agent_session` reject the old ID and return `cluster_run_changed` with the current ID, and `configure_team` returns `cluster_team_changed` with the current ID. `replace` may reassign busy slots and still has to wait for the main conversation's child tasks to finish (`cluster_team_busy`).
- Every tool call must pass the current `run_id` explicitly; the stdio MCP adapter does not cache or automatically switch the ID, it only passes this call's tool parameter to the bridge through the `X-TCB-Cluster-Run-Id` header, and it does not rely on the `TCB_CLUSTER_RUN_ID` environment variable.
- Cluster tasks, progress messages and background tasks remain in memory and are not persisted across host restarts.
- The notification that wakes the main conversation after a child task ends is in English; it only lists the task_id and asks the main agent to read the result with `poll_agent_tasks(task_ids=...)`, without inlining the child agent's output. Whether to notify depends only on whether the main agent has already read the result, with no time window: a result counts as read (`result_observed`) once `poll_agent_tasks` returns the task in a terminal state or `wait_agent_messages` returns its `final` message. An unread child task triggers a notification whether it ends during a main-agent turn or after the turn; one that ends during the turn is held back and delivered by `_finish_cluster_parent_turn()` once the main conversation is idle, and one that was read before delivery is not notified. The bridge does not distinguish callers; as with `adopt_unfinished_tasks()` and the managed cursor of `wait_agent_messages`, reads through these two tools are all treated as reads by the main agent.
- Notifications only cover the most recent user request: `_start_cluster_run_if_requested()` increments the main conversation's request generation by `session._execution_id` (all attempts of an endless-mode run share one generation), and internal continuation turns do not increment it; a child task of an older request is moved into the current request only if the latest request queries it with `poll_agent_tasks` while it is still unfinished. The main agent state is kept per main conversation in `ClusterRuntime` and remains valid after `configure_team` rotates `run_id`.
- The CLI stdio launcher or the DeepSeek patch passes `--config` to `mcp_stdio.py` to read the cluster bridge configuration file.
- `profile.cluster.enabled` is the current Bot-level cluster switch; the legacy `cluster` field in the request body is only a compatibility input and does not decide whether a cluster run starts.

## Execution boundaries of the cluster orchestration configuration

- Dynamic tasks use the role names and responsibilities from the main conversation's team; the legacy `system_prompt` of a physical slot is suppressed on this chain.
- The Bot-level `max_parallel_agents`, `default_timeout_seconds` and `write_policy` reach the runtime; every CLI (including DeepSeek) shares the low, medium, high and professional tiers of the `model_tiers` and `reasoning_efforts` configuration. The professional tier is for special work, and the main Agent selects it only when the user explicitly asks for the professional tier. A child task overrides the model and reasoning effort from the configuration snapshot taken when it was queued; an empty tier inherits the main Agent configuration, and the main Bot is not modified.
- On the admin page, all execution backends share the cluster configuration panel. CLI model and reasoning-effort options come from each backend's parameter schema.
- `conflict_policy` and the physical-slot fields `enabled`, `allow_cluster`, `allow_write`, `session_policy` and `timeout_seconds` are currently only parsed, saved or echoed back; they do not drive dynamic task execution.
- `ask_agent.allow_write` is currently only validated against the Bot `write_policy` and recorded; it is not a permission boundary of the file system or the CLI sandbox.
- When `ask_agent.timeout_seconds` is not passed, the Bot `default_timeout_seconds` is used; the timeout is a soft deadline that only marks `deadline_exceeded` in the task state and does not forcibly terminate the child agent. The main agent can call `cancel_agent_task(task_id)` to stop exactly one queued or running child task without affecting other tasks in the same run.

## Verification

- CLI/provider: `tests/test_cli_streaming.py`, `tests/test_codex_server_runtime.py`, `tests/test_codex_server_config.py`; for targeted DeepSeek checks see its reference.
- Session/history: `tests/test_sessions.py`, `tests/test_session_store.py`, `tests/test_chat_history_service.py`, `tests/test_chat_store_revision.py`.
- Cluster: `tests/test_cluster_setup.py`, `tests/test_cluster_mcp_schema.py`, `tests/test_cluster_mcp_client.py`, `tests/test_cluster_auto_run.py`, `tests/test_cluster_new_agent_session.py`, `tests/test_cluster_team_config.py`, `tests/test_cluster_model_tiers.py`, `tests/test_cluster_cancel.py`, `tests/test_cluster_parent_wakeup.py`.
