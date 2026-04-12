# Agent Guide

This file provides guidance to coding agents working in this repository.

## Project Snapshot

Telegram CLI Bridge is a Windows-first Python Telegram bot that forwards user messages to local AI coding CLIs and exposes a Web management UI.

Current local CLI targets:

- `kimi`
- `claude`
- `codex`

Current runtime bot modes:

- `cli`
- `assistant`

The repository supports one main bot plus multiple managed sub-bots loaded from `managed_bots.json`.

## Commands

```bash
# Start the Telegram bot
python -m bot

# Run the backend test suite
python -m pytest tests -q

# Run focused backend tests
python -m pytest tests/test_handlers/test_chat.py -q
python -m pytest tests/test_web_api.py -q
python -m pytest tests/test_assistant.py -q

# Run frontend tests
cd front && npm test

# Build the frontend
cd front && npm run build

# Optional frontend type check
cd front && npm run lint
```

Do not assume the committed `venv/` is usable on every machine. Prefer the active Python environment unless you have verified the local virtualenv.

## Runtime Shape

### Entry Point

- `bot/__main__.py` imports `bot/main.py:main()`
- `main()` runs `asyncio.run(run_all_bots())` inside a restart loop
- `/restart` sets `config.RESTART_REQUESTED` and `config.RESTART_EVENT`, then re-execs the process

### Multi-Bot Manager

`bot/manager.py:MultiBotManager` is the central orchestrator.

- Main bot comes from `.env`
- Managed bots come from `managed_bots.json`
- Each bot owns its own `telegram.ext.Application`
- A watchdog restarts polling when an application's updater stops unexpectedly

### Active Bot Modes

Two modes are active in the current runtime:

- `cli`: forwards messages to local CLI tools
- `assistant`: routes messages to the API-backed assistant flow with memory tools

Legacy `webcli` code still exists in the repository, but manager validation now rejects new `webcli` bots and downgrades legacy saved `webcli` profiles to `cli`. Treat `webcli` as legacy compatibility code, not a current production mode.

## Core Modules

### Sessions

`bot/sessions.py` stores sessions by `(bot_id, user_id)`.

Each `UserSession` in `bot/models.py` tracks:

- current working directory
- conversation history in memory
- processing state and active subprocess
- per-CLI session ids for `codex`, `kimi`, and `claude`

Only CLI session ids are persisted to `.session_store.json`. Full chat history remains in memory.

### CLI Chat Flow

- Telegram CLI chat path: `bot/handlers/chat.py`
- Command construction and CLI parameter handling: `bot/cli.py`, `bot/cli_params.py`
- Supported CLI types: `kimi`, `claude`, `codex`

Important behavior:

- user text starting with `//` is rewritten to `/...` before sending to the CLI
- Codex runs with JSON output and is parsed by `parse_codex_json_output()`
- long Telegram replies are chunked with `split_text_into_chunks()`
- Telegram output primarily uses HTML parse mode with fallback helpers for unsafe markup

### Handler Registration

`bot/handlers/__init__.py` wires handlers based on `bot_mode`.

Current CLI-mode command surface includes:

- `/start`, `/reset`, `/kill`, `/cd`, `/pwd`, `/files`, `/ls`, `/history`
- `/exec`, `/rm`
- `/upload`, `/download`, `/cat`, `/head`
- `/codex_status`

Main-bot-only admin surface includes:

- `/restart`
- `/bot_help`, `/bot_list`, `/bot_add`, `/bot_remove`, `/bot_start`, `/bot_stop`
- `/bot_set_cli`, `/bot_set_workdir`, `/bot_kill`
- `/system`
- `/bot_params`, `/bot_params_set`, `/bot_params_reset`, `/bot_params_help`

Assistant-mode command surface includes:

- `/start`, `/reset`, `/files`, `/history`
- `/memory`, `/memory_add`, `/memory_search`, `/memory_delete`, `/memory_clear`
- `/tool_stats`

### Voice

`bot/handlers/voice.py` and `bot/whisper_service.py` provide optional voice transcription.

Required optional dependencies:

- `openai-whisper`
- `pydub`
- FFmpeg

If those dependencies are missing, the voice handler is skipped and the rest of the bot still runs.

### Web API And Frontend

The repository also contains a Web control surface:

- backend API server: `bot/web/server.py`, `bot/web/api_service.py`, `bot/web/git_service.py`
- frontend app: `front/`

The frontend currently includes screens for:

- chat
- files
- git
- settings

Current Web capabilities include:

- streaming Web chat for `cli` and `assistant` bot modes
- Markdown rendering for completed assistant chat replies, with raw-text fallback on render failure
- file browsing and file preview
- Git overview, diff, stage/unstage, stage-all, commit, fetch/pull/push, stash/pop
- CLI parameter editing
- tunnel status management
- admin script execution and service restart hooks

## Conventions

- User-facing strings are Chinese
- Config is loaded from environment variables in `bot/config.py`
- `.env` loading uses `python-dotenv`
- The repository has backend tests and frontend tests, but no backend linter or backend type checker configured

## Testing Notes

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
- `front/src/test/files-screen.test.tsx`
- `front/src/test/git-screen.test.tsx`
- `front/src/test/app.test.tsx`
- `front/src/test/mobile-layout.spec.ts`
