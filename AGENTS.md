# Agent Guide

Orbit Safe Claw is a Windows-first Python web console that forwards user messages to the local `claude`, `codex`, or Pi native agent. The following rules apply to the entire repository.

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

## Repository Boundaries

- `bot/` contains the backend, Web API, bot manager, native agent, and plugin implementations; `front/` is the React/Vite frontend; `tests/` is the backend pytest.
- Do not commit or force-add `.env`, the real `managed_bots.json`, `docs/` runtime materials and release notes, or data under the user directory `.tcb/`.
- `managed_bots.example.json` is for public examples only; the current runtime is Web-only, and there is no per-bot Telegram application lifecycle.
- Brand/logo consistently uses `front/public/assets/app-logo*.svg`; login, favicon, mobile shell, and workbench header remain consistent.
- Configuration is loaded from environment variables in `bot/config.py`; `.env` uses `python-dotenv`.
- Fixed public forwarding must retain the `/node/<node ID>/` path prefix and support WebSocket; for configuration and minimal `frps`/`frpc` examples, see `README.md`.

## Core Invariants

- Web sessions are isolated by `(bot_id, shared_user_id, agent_id)`; Web user IDs are normalized via `chat_session_user_id()`.
- When user text starts with `//`, rewrite it to `/...`; Codex CLI uses JSON output.
- `execution_mode=native_agent` uses AG-UI; regular CLI keeps legacy SSE `meta/status/trace/done`, with incremental body preview placed in `status.preview_text`.
- The top level of CLI SSE `meta/status/trace/done` must retain `turn_id` and `assistant_message_id` to stably bind the current turn.
- Regular CLI traces and native processes uniformly enter `NativeAgentTranscript`; CLI uses `mode="cli"` and must not display native permission operations.
- The Pi runtime's `client.events()` may only be read by the single reader in `pi_session_runtime.py`.
- Pi session binding is determined by `cwd + model_id + pi_agent + reasoning_effort`; any change to any item must invalidate the old session and the workspace-history rollback chain.
- Known implementation gap: the current Pi runtime/session reuse path does not yet fully compare and invalidate the above fingerprint; when modifying this chain, the implementation and regression tests should be completed, and the current state must not be solidified into a weaker contract.
- Web terminal sessions are isolated by `(user_id, owner_id)`; each new tab must use an independent `owner_id`, and closing a tab must terminate the corresponding shell; the legacy client's `rebuild` endpoint is retained as a compatibility alias for creating sessions.

When modifying the native agent/Pi/cluster, Plugin, or installation/release chain, use the repository-level `orbit-maintenance` skill, and read only the reference corresponding to the current subsystem.

## CodeGraph

- For cross-module changes, architecture analysis, refactoring, call-chain or impact analysis, first use the available CodeGraph tools; only read source code for specific details that are not covered or are about to be modified.
- When CodeGraph is unavailable, use `rg` and source reading directly; after changes, verify with tests, logs, and `git diff`.
- After major changes, run `codegraph sync .` to refresh the index.

## Verification

- Before completion, run tests, builds, or smoke checks matching the changes, and report the actual results; if unable to run them, explain why.
- The backend uses `pytest`, `pytest-asyncio`, and `unittest.mock`; no backend linter/type checker is currently configured.
- The frontend uses Vitest, Testing Library, and Playwright; when layout is involved, run browser-level checks.
- Avoid duplicating assertions of the same fact across the component, page, and shell layers; keep only the most appropriate layer.