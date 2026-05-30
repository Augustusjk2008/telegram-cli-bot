# Agent Guide

This file guides coding agents in this repository.

## Session Constraint

- 当前 agent 工作目录固定为 `C:\Users\JiangKai\telegram_cli_bridge\refactoring`
- 不得主动关闭、重启、kill 当前 agent 自身，或通过停服务/重启服务等方式让当前 agent 退出
- 如需重启 `python -m bot`、Web 服务或其它宿主进程，先让用户执行，或取得明确指令

## Project Snapshot

Orbit Safe Claw is a Windows-first Python Web control surface that forwards user messages to local AI coding CLIs.

- CLI targets: `claude`, `codex`, `kimi`
- runtime bot modes: `cli`, `assistant`
- main bot comes from `.env`; managed sub-bots come from local `managed_bots.json`
- at most one `assistant` bot profile is allowed
- Web UI covers chat, assistant ops, files, Git, terminal/debug utilities, plugins, settings, admin center, announcements, updates, and tunnel status

## Commands

```bash
# Install / startup
bash install.sh
bash start.sh
python -m bot

# Backend tests
python -m pytest tests -q
python -m pytest tests/test_cli.py tests/test_manager.py tests/test_sessions.py -q
python -m pytest tests/test_web_api.py tests/test_assistant.py tests/test_updater.py tests/test_release_assets.py -q
python -m pytest tests/test_plugin_manifest.py tests/test_plugin_service.py tests/test_plugin_runtime.py tests/test_vivado_waveform_plugin.py -q

# Frontend tests / build
cd front && npm test
cd front && npm test -- --run src/test/plugins-screen.test.tsx src/test/plugin-view-surface.test.tsx src/test/desktop-workbench.test.tsx
cd front && npm run build
cd front && npm run lint

# Release
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree -ReleaseNotesFile .\docs\release-notes\v<version>.md
```

Do not assume committed `venv/` is usable. Prefer the active Python environment unless verified.

## Runtime Shape

### Entry Point

- `bot/__main__.py` imports `bot/main.py:main()`
- `main()` runs `asyncio.run(run_all_bots())` inside a restart loop
- `/restart` sets `config.RESTART_REQUESTED` and `config.RESTART_EVENT`, then re-execs the process

### Multi-Bot Manager

`bot/manager.py:MultiBotManager` manages profiles.

- `managed_bots.example.json` is the public example; do not commit real `managed_bots.json`
- runtime is Web-only; no per-bot Telegram application lifecycle remains
- legacy `webcli` code exists only for compatibility; manager rejects new `webcli` bots and downgrades legacy saved profiles to `cli`

## Core Areas

### Sessions And Chat History

`bot/sessions.py` stores sessions by `(bot_id, shared_user_id, agent_id)`. Web users are normalized through `bot/chat_identity.py:chat_session_user_id()`.

`UserSession` tracks current working directory, processing state, active subprocess, active conversation id, and native CLI session ids for `codex`, `claude`, `kimi`.

- native CLI session ids persist to `.session_store.json`
- chat history persists through `bot/web/chat_store.py`
- running state and overlays remain in memory

### CLI Chat Flow

- Web/shared chat path: `bot/web/api_service.py`
- command construction and CLI parameters: `bot/cli.py`, `bot/cli_params.py`
- supported CLI types: `claude`, `codex`, `kimi`

Important behavior:

- user text starting with `//` is rewritten to `/...`
- Codex uses JSON output parsed by `parse_codex_json_output()`
- Kimi uses streaming JSON parsed by `parse_kimi_stream_json_output()`
- long Web replies are streamed and finalized in the Web API layer
- CLI bots can define child agents; non-cluster chat scopes one active agent, cluster mode dispatches child agents through `@agent_id` mentions

### Web API And Frontend

- backend API: `bot/web/server.py`, `bot/web/api_service.py`, `bot/web/git_service.py`
- frontend app: `front/`
- frontend screens include chat, files, Git, terminal, debug, plugins, settings, assistant ops, admin center
- completed assistant replies render Markdown with raw-text fallback
- plugin file views include session-backed heavy views and VCD waveform rendering
- Git UI supports overview, diff, stage/unstage, commit, fetch/pull/push, stash/pop

## Plugin System

Plugin code lives under `Path.home() / ".tcb" / "plugins"` by default. The example Vivado waveform plugin lives in `examples/plugins/vivado-waveform` and is copied/synced into the user plugin directory for local use.

Key modules:

- manifest loading: `bot/plugins/manifest.py`
- registry and file matching: `bot/plugins/registry.py`
- runtime process management: `bot/plugins/runtime.py`
- orchestration/session cache/hot reload/config writes: `bot/plugins/service.py`
- Web routes: `bot/web/api_service.py`, `bot/web/server.py`

`plugin.json` supports schema versions 1 and 2.

- v1: `enabled`, mutable `config`, `views[].viewMode` (`snapshot`/`session`), `views[].dataProfile` (`light`/`heavy`)
- v2 adds runtime permissions, `configSchema`, and `catalogActions`

Updating a plugin through Web API writes `plugin.json`, clears plugin view sessions, and shuts down plugin runtimes so next access reloads from disk. Refreshing the plugin page also rescans manifests and restarts plugin runtimes.

Vivado waveform plugin uses a Python JSON-RPC stdio backend. It builds a VCD index by source fingerprint, returns summary plus initial window, and serves visible time/signal windows on demand. `config.lodEnabled` controls dense-segment LOD; dense compression must not hide activity.

## Install And Update

- Windows install: `install.bat`, `install.ps1`
- Linux install: `install.sh`
- Windows startup: `start.bat`, `start.ps1`
- Linux startup: `start.sh`
- automatic update only checks GitHub Releases
- `docs/` 必须保持在 git 外；release note 也不要 force-add 或提交
- GitHub Release body comes from `.release-local/publish-release.ps1 -ReleaseNotesFile <markdown-file>`; omit it to use `gh release create --generate-notes`
- downloaded updates apply on next startup via `python -m bot.updater apply-pending --repo-root <repo>`

## Conventions

- User-facing strings are Chinese
- Brand/logo assets live under `front/public/assets/app-logo*.svg`; login page, favicon, mobile shell, and workbench header should stay aligned
- config loads from environment variables in `bot/config.py`; `.env` uses `python-dotenv`
- backend tests and frontend tests exist; no backend linter/type checker is configured

## CodeGraph

- Before cross-module changes, architecture analysis, refactors, call-chain or impact analysis, use available CodeGraph MCP tools such as `codegraph_context`, `codegraph_search`, `codegraph_trace`, `codegraph_node`
- CodeGraph is navigation only; verify details with source reads, `rg`, tests, logs, and `git diff`
- Known-file small edits, config changes, copy changes, and single-file bugs do not require CodeGraph
- If CodeGraph is unavailable, say so briefly and fall back to `rg` / source reads

## Testing Notes

- Avoid repeating the same assertion across component/page/shell tests; keep the most appropriate layer
- Backend tests use `pytest`, `pytest-asyncio`, `unittest.mock`
- Useful fixtures: `mock_update`, `mock_context`, `clean_sessions` from `tests/conftest.py`
- Frontend tests use Vitest, Testing Library, and Playwright for browser-level layout checks
- Useful frontend tests: `front/src/test/chat-screen.test.tsx`, `desktop-bot-manager-screen.test.tsx`, `files-screen.test.tsx`, `git-screen.test.tsx`, `app.test.tsx`, `mobile-layout.spec.ts`
