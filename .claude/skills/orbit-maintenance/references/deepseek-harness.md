# DeepSeek Harness CLI

## Configuration and support scope

- The CLI type is `deepseek` and the default command is `dsh`; both the main Bot and child Bots can select it. The configuration entry points are `bot/config.py`, `bot/manager.py` and `bot/cli_params.py`.
- `execution_mode=cli` on a local workspace is currently supported, including Bot-level TCB cluster orchestration. Remote workspaces and Git commit-message generation are rejected before launch; keep the frontend and backend boundaries consistent when changing the entry points.
- The provider, model and `reasoning_effort` can be selected on the chat page; an empty value or `none` inherits the Harness configuration, and the reasoning effort supports `off/low/high/max`. Both the npm build and the official Desktop build apply the selection through a temporary per-call patch and keep the rest of the configuration; the user's Harness configuration is not modified. Desktop temporarily bridges the `agent-default-model`, `credentials`, `llm-pi-ai` and `llm-deepseek` entries. Switching the provider clears the DeepSeek session binding of the current Web user and agent, while switching the model within the same provider keeps the session. The host `extra_args` only accepts `--patch <file path>` or `--patch=<file path>`; protocol parameters, the session id and the task input are controlled by the host.
- `bot/deepseek_launch.mjs --describe-models` returns a controlled provider catalog containing only providers, models, reasoning efforts and defaults. Reading the catalog is limited in size and time; on failure the backend keeps the current selection and the static model candidates. Credential contents, API keys, actual environment variable values and the raw profile must never reach the API, stdout, stderr or history.
- The wrapper of the official Desktop build is usually at `resources\\runtime\\cli\\bin\\dsh.cmd` under the installation directory; it uses the runtime bundled with Desktop and does not require a system Node.js. Windows auto-discovery enables the Desktop install-registration fallback only for `dsh`; an explicit full path, PATH and the npm directory keep higher priority.
- Desktop cluster turns preflight `@deepseek-ai/dsh-mcp-client` through `--dump-config`; if the headless profile reports that `orbit-tcb-cluster-mcp` does not exist, Orbit returns a clear diagnostic before launch and pauses cluster tasks for that Desktop version. The currently verified Desktop `0.2.1-rc.3` is in this situation.
- `permission_mode` supports `read-only/workspace-write/danger-full-access`, defaults to `workspace-write`, and is passed to the Harness through `DSH_PERMISSION_MODE`. Web calls restrict `danger-full-access` without `allow_unsafe_cli` through `clamp_unsafe_cli_params()`; the cluster `allow_write` does not replace this layer of CLI permission configuration.
- Frontend CLI labels and default paths are managed by `front/src/utils/cliType.ts`; for the configuration entry points see `front/src/screens/botManagerModel.ts` and `SettingsScreen.tsx`. Switching to DeepSeek on the settings page saves the CLI type and path and keeps the Bot's cluster switch.

## Local cluster integration

- `bot/web/api_service.py:_cluster_mcp_injected_params()` calls `write_deepseek_mcp_patch()` and appends `--patch <path>` to the DeepSeek parameter block. `bot/cluster/setup.py` generates a patch containing `@deepseek-ai/dsh-mcp-client` that runs the project's `bot/cluster/mcp_stdio.py --config <bridge-config>` with the current Python, passes the workspace cwd, and sets `failOnStartupError=true`.
- The patch is managed by the host and lives in the cluster MCP configuration directory; the admin page prepares that file, and DeepSeek's MCP install, verify and remove command lists are all empty. The integration does not modify the user's global Harness configuration.
- Tools, the explicit `run_id` and the team rules follow the shared MCP contract in [cli-agent.md](cli-agent.md). The model tier of a CLI child task maps to DeepSeek's `model` and `reasoning_effort`.

## Execution protocol

- `bot/cli_params.py:_build_deepseek_args()` builds `dsh --profile headless [--patch <path>] --json [--session-id <id>] -`, and the user message is sent through stdin; Chinese and multi-line input are preserved.
- `bot/deepseek_cli.py` recognizes the npm dsh entry and the official Desktop wrapper and branches by entry type. For the npm build, `bot/deepseek_launch.mjs` uses Node to call the exported `runCli()` explicitly, which stays compatible with Node 22.17 lacking `import.meta.main`; for the Desktop build it calls the official wrapper directly, extracts the default model entry through `--dump-config` and then appends a temporary `--patch`, keeps the merged provider configuration, and cleans up the temporary files after the child process exits. In JSON mode the launcher reports the provider and model through `orbit_model` metadata for cost estimation and diagnostics; that metadata is skipped when the default model configuration cannot be read statically. A custom executable can keep its original invocation; when the entry cannot be recognized, only an explicit provider, model or reasoning-effort selection fails before launch.
- `bot/cli.py:DeepSeekJsonStreamParser` parses the stdout JSONL and stores `orbit_model.provider`; `bot/web/api_service.py` manages the process and turns. stderr is collected separately for failure diagnostics.
- On Windows the dsh process is started with breakaway and skips Orbit Job Object containment, so nested jobs do not interfere with the Harness's own process isolation; keep this branch when changing the unified CLI process lifecycle.
- Success requires a valid `session.sessionId`, `status.phase=turn_end` with `reason.kind=completed`, a `final` event and process exit code 0. Invalid JSON, a missing end event, run events emitted after final, or output over the limit must all keep the failed state.
- `text` provides the body preview and `final.text` replaces the final body. `thinking`, tool calls and tool results go into the trace; keep `callId` pairing and step de-duplication.
- Usage from `status.phase=step_end` is de-duplicated and accumulated by `(turn, step)`, summing only the fields that every step has; a step with missing usage or invalid counts makes the complete usage unavailable. `bot/web/cli_context_usage.py` can also read the `contextPressure` projection under `DSH_HOME` (default `~/.dsh`) by the current session id; `_build_deepseek_context_usage()` merges the session's context occupancy with this turn's usage, and shows this turn's usage when the projection is missing. A cost estimate with `scope=turn` is attached and persisted at the end of every turn; ordinary Harness input already excludes cache, and reasoning is already included in output; on failure or interruption, reported usage that can be priced is marked as a partial estimate. No cost is shown when the model is unknown or the usage is incomplete. The default CSV configures fixed CNY peak unit prices for Flash and Pro and does not automatically apply off-peak discounts.

## Sessions, history and frontend events

- Sessions keep the `(bot_id, shared_user_id, agent_id)` isolation; `deepseek_session_id` is stored by `bot/models.py`, `bot/sessions.py` and `bot/session_store.py`. Only the ID returned by the Harness is used to continue a chat, and the first call of a new session omits `--session-id`.
- History, trace and usage are persisted by the project's `ChatStore`; `bot/web/chat_history_service.py` restores the binding from the provider session ID of the selected conversation. DeepSeek history recovery does not scan external CLI session directories.
- The frontend CLI transcript displays the trace and keeps the legacy SSE `meta/status/trace/done` with the top-level `turn_id` and `assistant_message_id`; the incremental body is in `status.preview_text`.
- Failures, stops and output over the limit should keep the body received so far, complete the turn once and release the processing state; a failure must never replay the user's task automatically.

## Verification

For protocol, streaming execution, session recovery and trace changes, run:

```bash
python -m pytest tests/test_deepseek_exec.py tests/test_deepseek_history_adapter.py tests/test_cli_streaming.py tests/test_cli_context_usage.py -k deepseek -q
```

For cluster integration, configuration or persistence changes, run as needed:

```bash
python -m pytest tests/test_cluster_setup.py tests/test_manager.py tests/test_env_service.py tests/test_sessions.py tests/test_session_store.py -k deepseek -q
```

For frontend entry changes, select the relevant cases in `front/src/test/settings-screen.test.tsx`, `bot-manager-delete.test.tsx` and `real-client.test.ts`; when layout is involved, run Playwright checks against an already started service.
