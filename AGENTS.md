# Agent Guide

> **Sync rule:** `AGENTS.md` and `CLAUDE.md` must stay identical. When you edit one, apply the same change to the other in the same task.

Orbit Safe Claw is a Windows-first Python web console for local Codex (`codex exec` or `codex app-server`), Claude, Antigravity (`agy`), DeepSeek Harness (`dsh`) and the Pi native agent. An optional single Telegram gateway shares the Web sessions. The following rules apply to the entire repository.

## Sessions and Security Boundaries

- Do not proactively shut down, restart, or kill the current agent itself, or cause the current agent to exit by stopping services, restarting services, or similar means.
- If you need to restart `python -m bot`, the web service, or other host processes, have the user do it first, or obtain explicit instructions.
- The agent must not start any development or preview services, including `npm run dev`, Vite dev server, `vite preview`, temporary HTTP servers, etc., nor keep listening ports in the background; when development services are needed, the user should start them themselves.
- Preserve the user's existing changes; do not use destructive Git commands to overwrite work that does not belong to the current task.

## Common Commands

```bash
# Install / Start
bash install.sh
bash start.sh
python -m bot

# Backend
python -m pytest tests -q

# Frontend
cd front && npm run test:gate
cd front && npm run build
cd front && npm run lint
```

Do not assume that `venv/` in the repository is usable on all machines. Prefer the currently activated Python environment unless the local venv has been verified.

Use Node.js 22.13+ for the locked frontend dependencies and installer checks.

- Source launchers `start.bat`, `start.ps1` and `start.sh` use the existing `front/dist` assets; after frontend changes, run `cd front && npm run build` explicitly before restarting the host. Admin Center can request a backend restart, while an AI agent must not trigger that restart proactively.

### Local Browser Tests

Use the installed Google Chrome with the project's Playwright; Windows selects Chrome automatically. From `front/`, reuse a user-started application:

```powershell
$env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:8765"
npm run e2e:smoke
```

The smoke test covers login-page input, tab switching, desktop/mobile layout and screenshots. Run feature tests with `npm run e2e -- src/test/<feature>.spec.ts`, keeping `PLAYWRIGHT_BASE_URL` set.

## Repository Boundaries

- `bot/` contains the backend, Web API, bot manager, native agent, and plugin implementations; `front/` is the React/Vite frontend; `tests/` is the backend pytest.
- Do not commit or force-add `.env`, the real `managed_bots.json`, `docs/` runtime materials and release notes, or data under the user directory `.tcb/`.
- `managed_bots.example.json` is for public examples only. Web Bot profiles share one optional Telegram gateway; there is no per-profile Telegram application lifecycle. Gateway configuration uses `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS` and `TELEGRAM_BROADCAST_COMPLETIONS`.
- Brand/logo consistently uses `front/public/assets/app-logo*.svg`; login, favicon, mobile shell, and workbench header remain consistent.
- Configuration is loaded from environment variables in `bot/config.py`; `.env` uses `python-dotenv`.
- Resolve runtime locations through `bot/runtime_paths.py`: the storage locator takes precedence after migration, while `TCB_DATA_DIR` only overrides the application data root before migration. Plugins and chat history follow the storage root; do not assume every runtime file is under `TCB_DATA_DIR`.
- Fixed public forwarding must retain the `/node/<node ID>/` path prefix and support WebSocket; for configuration and minimal `frps`/`frpc` examples, see `README.md`.

## Core Invariants

- Web sessions are isolated by `(bot_id, shared_user_id, agent_id)`; Web user IDs are normalized via `chat_session_user_id()`.
- When user text starts with `//`, rewrite it to `/...`; Codex CLI uses JSON output.
- CLI types are `codex`, `codex_server`, `claude`, `antigravity` and `deepseek`. `codex_server` uses `codex app-server --stdio` under `execution_mode=cli`, with its own parameter namespace. DeepSeek supports local CLI execution and cluster MCP; remote workspaces, native execution and Git commit-message generation remain unsupported.
- `execution_mode=native_agent` uses AG-UI; regular CLI keeps legacy SSE `meta/status/trace/done`, with incremental body preview placed in `status.preview_text`.
- The top level of CLI SSE `meta/status/trace/done` must retain `turn_id` and `assistant_message_id` to stably bind the current turn.
- Regular CLI traces and native processes uniformly enter `NativeAgentTranscript`; CLI uses `mode="cli"` and must not display native permission operations.
- Local cluster orchestration supports all five CLI types and native Pi. Bot-level `max_parallel_agents` is normalized to 1–20. All backends share model and reasoning tiers; per-task overrides use the queued configuration snapshot without changing the main Bot configuration. Antigravity uses workspace MCP configuration, DeepSeek uses a per-turn Harness patch, and Pi uses an extension over the shared bridge. Remote Antigravity cluster orchestration is rejected before launch.
- Cluster `run_id` is stable for the main conversation and team revision. Every MCP call passes it explicitly; after `configure_team` returns `changed=true`, subsequent calls use its returned ID. Ordinary turns and host restarts do not rotate it; in-memory tasks do not survive host restarts.
- Endless mode groups automatic `Continue` attempts by `endless_group_id`. Retryable incomplete or error results wait for `ENDLESS_CONTINUE_DELAY_SECONDS` (default 120 seconds), persist `error` and `continue` events in ChatStore, and reuse one durable turn for the whole run. Legacy grouped turns are consolidated in the database; history loading returns the turn directly. Session state exposes whether endless mode is active and its attempt count; stopping or cancelling the run must end the continuation loop.
- Telegram and Web share `(bot_id, shared_user_id, agent_id)` sessions. Telegram bindings also identify the conversation; delivery retries and broadcast expansion read persisted replies without replaying agent tasks. Keep the Telegram whitelist separate from Web user IDs and never expose the Bot token.
- The theme library is the shared set of packaged presets and is read-only for every account: creating, importing, updating or deleting themes and uploading theme assets return `theme_readonly`. Each signed-in account keeps its own selected theme, falling back to the default theme; the login page reads `/api/public/ui/themes` and stores its preview selection only in the browser. Guests cannot change the selection; selection changes check the library revision to avoid overwriting concurrent changes.
- The Pi runtime's `client.events()` may only be read by the single reader in `pi_session_runtime.py`.
- Pi session binding is determined by `cwd + model_id + pi_agent + reasoning_effort`, plus `system_prompt_hash`, `prompt_profile`, `child_agent_prompt_hash` and `remote_workspace_fingerprint` when present; any change to any item must invalidate the old session and the workspace-history rollback chain.
- Pi binding invalidation is implemented in the runtime and service: clear persisted bindings in ChatStore and PiSessionStore, invalidate the conversation's rollback chain, and prevent a closing runtime from restoring stale state. Keep the regression coverage in `tests/test_remote_workspace_chat.py`. Changes only to the models-file fingerprint or ordinary environment may rebuild the runtime while retaining the session/history.
- Web terminal sessions are isolated by `(user_id, owner_id)`; each new tab must use an independent `owner_id`, and closing a tab must terminate the corresponding shell; the legacy client's `rebuild` endpoint is retained as a compatibility alias for creating sessions.
- Updates use installation-scoped `UpdateStore` state and one durable preparation job. Downloading only prepares a job; applying requires its ID, current revision and an idle host. Exit `75` is an ordinary restart; `76` hands a confirmed job to the official launcher's frozen, standard-library executor. Preserve backups until health verification and retain recovery materials on uncertainty. Never apply updates or restart the current host as an automated validation step.
- Direct and supervised hosts share installation locks in the external control directory. Storage migration must preserve this lock identity; the host reports its current update-state location through an authenticated process handoff. Keep new work paused until the executor confirms the new or restored host.
- Update manifests own program files only. Preserve runtime paths, local modifications and Pi settings/models; the two bundled Pi extensions require old-hash ownership checks. Program rollback cannot imply data rollback. Verify new migration compatibility before application. `scripts/update_package.py` checks payload identity/integrity; the legal-file verifier checks required notices only.

When modifying CLI execution, the native agent/Pi/cluster, remote workspace/terminal/Git bridge, plugins, or the installation/release chain, use the repository-level `orbit-maintenance` skill, and read only the references corresponding to the affected subsystems. Current source, pinned dependencies and tests determine implementation status; keep these instructions, skill references and both root READMEs consistent when their documented contracts change.

## Verification

- Use minimal sufficient testing: add tests for stable contracts, high-risk logic, important boundaries, security/data integrity issues and real bug regressions. Ordinary copy, styles and mechanical edits do not need new tests; documentation changes need source, command and link checks.
- Before completion, run tests, builds, or smoke checks matching the changes, and report the actual results; if unable to run them, explain why.
- The backend uses `pytest`, `pytest-asyncio`, and `unittest.mock`; no backend linter/type checker is currently configured.
- The frontend uses Vitest, Testing Library, and Playwright; when layout is involved, run browser-level checks.
- Avoid duplicating assertions of the same fact across the component, page, and shell layers; keep only the most appropriate layer.