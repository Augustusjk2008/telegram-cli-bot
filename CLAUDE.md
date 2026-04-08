# CLAUDE.md

This file provides guidance to coding agents working in this repository.

## Project Snapshot

Telegram CLI Bridge is a Windows-first Python Telegram bot that forwards user messages to local AI coding CLIs:

- `kimi`
- `claude`
- `codex`

The repository supports one main bot plus multiple managed sub-bots loaded from `managed_bots.json`.

## Commands

```bash
# Start the bot
python -m bot

# Run the full test suite
python -m pytest tests -q

# Run a focused test file
python -m pytest tests/test_handlers/test_chat.py -q
python -m pytest tests/test_network_traffic.py -q
```

Do not assume the committed `venv/` is usable on every machine. Prefer the active Python environment unless you have verified the local virtualenv.

## Runtime Shape

### Entry Point

- `bot/__main__.py` imports `bot/main.py:main()`
- `main()` runs `asyncio.run(run_all_bots())` inside a restart loop
- `/restart` uses `config.RESTART_REQUESTED` and `config.RESTART_EVENT`, then re-execs the process

### Multi-Bot Manager

`bot/manager.py:MultiBotManager` is the central orchestrator.

- Main bot comes from `.env`
- Managed bots come from `managed_bots.json`
- Each bot has its own `telegram.ext.Application`
- A watchdog restarts polling when an application's updater stops unexpectedly

### Active Bot Modes

Two modes are active in the Telegram runtime:

- `cli`: default mode, forwards messages to local CLI tools
- `assistant`: direct API-backed assistant mode with memory tools

There is still legacy `webcli` / `bot/web/*` code in the tree, but the current Telegram handler registration falls back `webcli` to normal CLI mode. Treat it as legacy, not as a current production path.

## Core Modules

### Sessions

`bot/sessions.py` stores sessions by `(bot_id, user_id)`.

Each `UserSession` in `bot/models.py` tracks:

- current working directory
- conversation history
- processing state and active subprocess
- per-CLI session ids (`codex`, `kimi`, `claude`)

Only session ids are persisted, in `.session_store.json`. Full chat history is in memory only.

### CLI Chat Flow

- Telegram CLI chat path: `bot/handlers/chat.py`
- Command construction and response parsing: `bot/cli.py`, `bot/cli_params.py`
- Supported CLI types: `kimi`, `claude`, `codex`

Important behavior:

- user text starting with `//` is rewritten to `/...` before sending to the CLI
- Codex runs with JSON output and is parsed by `parse_codex_json_output()`
- long Telegram replies are chunked with `split_text_into_chunks()`

### Handlers

`bot/handlers/__init__.py` wires handlers based on `bot_mode`.

Current CLI-mode command surface includes:

- `/start`, `/reset`, `/cd`, `/pwd`, `/files`, `/ls`, `/history`
- `/exec`, `/rm`
- `/upload`, `/download`, `/cat`, `/head`
- main bot only: `/restart`, `/bot_*`, `/system`, `/bot_params*`

### Voice

`bot/handlers/voice.py` and `bot/whisper_service.py` provide optional voice transcription.

Requirements:

- `openai-whisper`
- `pydub`
- FFmpeg

If those dependencies are missing, the voice handler is skipped and the rest of the bot still works.

## Conventions

- User-facing strings are Chinese
- Config is loaded from environment variables in `bot/config.py`
- Telegram output primarily uses HTML parse mode
- The repository has tests, but no linter or type checker configured

## Testing Notes

Tests use `pytest`, `pytest-asyncio`, and `unittest.mock`.

Useful fixtures from `tests/conftest.py`:

- `mock_update`
- `mock_context`
- `clean_sessions`

As of the current local review, the suite is mostly green but not fully clean; see `REVIEW.md` for the latest confirmed failures and live bug notes.
