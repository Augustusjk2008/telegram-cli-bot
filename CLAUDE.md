# Agent Guide

This file provides guidance to coding agents working in this repository.

## Session Constraint

- 当前 agent 工作目录固定为 `C:\Users\JiangKai\telegram_cli_bridge\refactoring`
- 任何时候不得主动关闭、重启、kill 当前 agent 自身，或通过停服务/重启服务等方式让当前 agent 退出
- 如需重启 `python -m bot`、Web 服务或其它宿主进程，必须先让用户自己执行，或得到用户明确指令

## Project Snapshot

Orbit Safe Claw is a Windows-first Python Web control surface that forwards user messages to local AI coding CLIs.

The Web UI also exposes local filesystem, Git, terminal/debug utilities, announcements, admin center operations, and plugin-rendered file views such as VCD waveform preview.

Current local CLI targets:

- `claude`
- `codex`

Current runtime bot modes:

- `cli`
- `assistant`

The repository supports one main bot plus multiple managed sub-bots loaded from `managed_bots.json`.

At most one `assistant` bot profile is allowed at a time.

## Commands

```bash
# Linux install / startup
bash install.sh
bash start.sh
# Linux startup as root
[ "$(id -u)" -eq 0 ] && CLI_BRIDGE_ALLOW_ROOT=1 bash start.sh || sudo env CLI_BRIDGE_ALLOW_ROOT=1 bash start.sh
# Linux background startup as root
sudo sh -c 'CLI_BRIDGE_ALLOW_ROOT=1 nohup bash ./start.sh >> logs/host.log 2>&1 < /dev/null & echo $! > .host.pid'

# Start the Web runtime
python -m bot

# Run the backend test suite
python -m pytest tests -q

# Run focused backend tests
python -m pytest tests/test_handlers/test_chat.py -q
python -m pytest tests/test_web_api.py -q
python -m pytest tests/test_assistant.py -q
python -m pytest tests/test_updater.py -q
python -m pytest tests/test_release_assets.py -q
python -m pytest tests/test_plugin_manifest.py tests/test_plugin_service.py tests/test_plugin_runtime.py tests/test_vivado_waveform_plugin.py -q

# Run frontend tests
cd front && npm test

# Run focused frontend plugin tests
cd front && npm test -- --run src/test/plugins-screen.test.tsx src/test/plugin-view-surface.test.tsx src/test/desktop-workbench.test.tsx

# Build the frontend
cd front && npm run build

# Optional frontend type check
cd front && npm run lint

# Build and publish a release
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree

# Build and publish with a custom GitHub Release body from Markdown
pwsh -ExecutionPolicy Bypass -File .release-local/publish-release.ps1 -Version <version> -RunChecks -AutoConfirmDirtyWorktree -ReleaseNotesFile .\docs\release-notes\v<version>.md
```

Do not assume the committed `venv/` is usable on every machine. Prefer the active Python environment unless you have verified the local virtualenv.

## Runtime Shape

### Entry Point

- `bot/__main__.py` imports `bot/main.py:main()`
- `main()` runs `asyncio.run(run_all_bots())` inside a restart loop
- `/restart` sets `config.RESTART_REQUESTED` and `config.RESTART_EVENT`, then re-execs the process

### Multi-Bot Manager

`bot/manager.py:MultiBotManager` is the central profile manager.

- Main bot comes from `.env`
- Managed bots come from local `managed_bots.json`
- `managed_bots.example.json` is the public example file; do not commit the real `managed_bots.json`
- Current runtime is Web-only; no per-bot Telegram application lifecycle remains

### Active Bot Modes

Two modes are active in the current runtime:

- `cli`: forwards messages to local CLI tools
- `assistant`: routes messages to the API-backed assistant flow with memory tools

Legacy `webcli` code still exists in the repository, but manager validation now rejects new `webcli` bots and downgrades legacy saved `webcli` profiles to `cli`. Treat `webcli` as legacy compatibility code, not a current production mode.

## Core Modules

### Sessions

`bot/sessions.py` stores sessions by `(bot_id, user_id, agent_id)`.

Each `UserSession` in `bot/models.py` tracks:

- current working directory
- conversation history in memory
- processing state and active subprocess
- per-CLI session ids for `codex` and `claude`
- active conversation id

Only CLI session ids are persisted to `.session_store.json`. Full chat history remains in memory.

### CLI Chat Flow

- Web / shared CLI chat path: `bot/web/api_service.py`
- Command construction and CLI parameter handling: `bot/cli.py`, `bot/cli_params.py`
- Supported CLI types: `claude`, `codex`

Important behavior:

- user text starting with `//` is rewritten to `/...` before sending to the CLI
- Codex runs with JSON output and is parsed by `parse_codex_json_output()`
- long Web chat replies are streamed and finalized through the Web API layer
- CLI bots can define child agents; non-cluster chat scopes one active agent at a time, while cluster mode dispatches child agents through `@agent_id` mentions

### Web API And Frontend

The repository also contains a Web control surface:

- backend API server: `bot/web/server.py`, `bot/web/api_service.py`, `bot/web/git_service.py`
- frontend app: `front/`

The frontend currently includes screens for:

- chat
- assistant ops
- files
- git
- terminal
- debug
- plugins
- admin center
- settings

Current Web capabilities include:

- streaming Web chat for `cli` and `assistant` bot modes
- CLI child-agent management, non-cluster active-agent switching, cluster templates / JSON config, and cluster MCP / model-tier settings
- assistant ops for proposals, patch generation / apply, memory, diagnostics, audit, and Automation queue / cron / runs
- Markdown rendering for completed assistant chat replies, with raw-text fallback on render failure
- file browsing and file preview
- plugin file views, including session-backed heavy views and VCD waveform rendering
- Git overview, diff, stage/unstage, stage-all, commit, fetch/pull/push, stash/pop, using a flatter desktop-style panel layout
- CLI parameter editing
- terminal, debug, and system script panels
- admin center user permissions, invite codes, announcements, and update controls
- announcement timeline dialog; announcement title/summary/items may render sanitized inline HTML with a small style whitelist
- main-bot update status, manual check, update download controls, and faster offline package listing
- tunnel status management
- admin script execution and service restart hooks

### Plugin System

Plugin code lives outside the repo by default under `Path.home() / ".tcb" / "plugins"`. The example Vivado waveform plugin is kept under `examples/plugins/vivado-waveform` and is copied/synced into the user plugin directory for local use.

Key backend modules:

- manifest loading: `bot/plugins/manifest.py`
- registry and file handler matching: `bot/plugins/registry.py`
- runtime process management: `bot/plugins/runtime.py`
- service orchestration, session cache, hot reload, and plugin config writes: `bot/plugins/service.py`
- Web API routes: `bot/web/api_service.py`, `bot/web/server.py`

`plugin.json` schema version 1 supports:

- `enabled`: disables file handler matching and plugin execution while still showing the plugin in the catalog
- `config`: plugin-owned mutable config persisted back into `plugin.json`
- `views[].viewMode`: `snapshot` or `session`
- `views[].dataProfile`: `light` or `heavy`

Updating a plugin through the Web API writes `plugin.json`, clears plugin view sessions, and shuts down plugin runtime processes so the next access reloads from disk. Refreshing the plugin page also rescans manifests and restarts plugin runtimes.

Installing a plugin from the Web UI allows overwrite by default. Uninstall actions live on plugin cards; there is no separate install-management panel.

The Vivado waveform plugin uses a Python JSON-RPC stdio backend. It builds a VCD index once per source fingerprint, returns a summary plus initial window, and serves visible time/signal windows on demand. `config.lodEnabled` controls dense-segment LOD compression. LOD may compress dense changes into `"kind": "dense"` activity segments, but must not hide signal activity.

## Install And Update

- Windows install entrypoints: `install.bat`, `install.ps1`
- Linux install entrypoint: `install.sh`
- Windows startup entrypoints: `start.bat`, `start.ps1`
- Linux startup entrypoint: `start.sh`
- Automatic update only checks GitHub Releases
- `docs/` 必须保持在 git 外；release note 也不要 force-add 或提交
- GitHub Release body comes from `.release-local/publish-release.ps1 -ReleaseNotesFile <markdown-file>`; omit it to use `gh release create --generate-notes`
- Downloaded updates are applied on the next startup via `python -m bot.updater apply-pending --repo-root <repo>`

## Conventions

- User-facing strings are Chinese
- Brand/logo assets live under `front/public/assets/app-logo*.svg`; login page, favicon, mobile shell, and workbench header should stay aligned
- Config is loaded from environment variables in `bot/config.py`
- `.env` loading uses `python-dotenv`
- The repository has backend tests and frontend tests, but no backend linter or backend type checker configured

## CodeGraph 使用约定

- 宿主项目较大；找代码、跨模块修改、重构、调用链分析、影响面分析前，优先使用 CodeGraph 定位入口、调用链和影响面。
- 优先流程：`codegraph_status` 确认索引健康，`codegraph_context` / `codegraph_search` 找相关代码，`codegraph_callers` / `codegraph_callees` / `codegraph_trace` / `codegraph_impact` 查调用链和影响面，再用 `rg` / 直接读文件核对细节。
- 已知文件的小修、配置改动、文案改动、单文件 bug 不强制使用 CodeGraph。
- CodeGraph 只作为结构导航层，不替代源码阅读、测试、日志和 `git diff`。
- 若 CodeGraph 未安装、未初始化或 MCP 不可用，说明原因后退回 `rg` / 读文件，不要卡住任务。

## Testing Notes

- 避免同一事实在组件/页面/壳层测试里重复断言同个文案或 UI 过渡态；发现类似重复覆盖时，默认顺手收敛测试，只保留最合适的一层。

Backend tests use:

- `pytest`
- `pytest-asyncio`
- `unittest.mock`

Useful fixtures from `tests/conftest.py`:

- `mock_update`
- `mock_context`
- `clean_sessions`

Frontend tests use:

- `vitest`
- Testing Library
- Playwright for browser-level layout checks

Useful frontend test files include:

- `front/src/test/chat-screen.test.tsx`
- `front/src/test/chat-composer.test.tsx`
- `front/src/test/desktop-bot-manager-screen.test.tsx`
- `front/src/test/files-screen.test.tsx`
- `front/src/test/git-screen.test.tsx`
- `front/src/test/app.test.tsx`
- `front/src/test/mobile-layout.spec.ts`
