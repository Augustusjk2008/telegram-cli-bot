# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram CLI Bridge — a Telegram bot that bridges user messages to AI coding CLI tools (Kimi, Claude Code, Codex). Supports multiple bot instances managed from a single main bot. Written in Python, runs on Windows.

## Commands

```bash
# Run the bot
python -m bot

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_cli.py -v

# Run a single test by name
python -m pytest tests/test_cli.py::test_function_name -v

# Run handler tests
python -m pytest tests/test_handlers/ -v

# Install dependencies (use the venv)
pip install -r requirements.txt
```

There is no linter, type checker, or build step configured. No `pyproject.toml` or `setup.cfg`.

## Architecture

### Entry Point & Lifecycle

`bot/__main__.py` -> `bot/main.py:main()` — runs `asyncio.run(run_all_bots())` in a retry loop. Supports process-level restart via `os.execv` (triggered by `/restart` command). The restart signal flows through `config.RESTART_REQUESTED` / `config.RESTART_EVENT`.

### Multi-Bot System

`bot/manager.py:MultiBotManager` is the central orchestrator. It manages:
- One **main bot** (from `.env` config) with admin privileges
- Zero or more **managed sub-bots** (from `managed_bots.json`) without admin commands
- Each bot is a separate `telegram.ext.Application` instance with its own polling loop
- A watchdog task auto-restarts dead polling loops
- Supports three bot modes: `cli` (default), `assistant`, and `webcli` (Kimi Web)

The main bot vs sub-bot distinction is controlled by `bot_data["is_main"]` on each Application, which determines whether admin handler commands are registered (`register_handlers(app, include_admin=is_main)`).

### Session Model

Sessions are keyed by `(bot_id, user_id)` tuple in `bot/sessions.py`. Each `UserSession` (in `bot/models.py`) tracks:
- Working directory, conversation history, processing state
- CLI-specific session IDs (`codex_session_id`, `kimi_session_id`, `claude_session_id`) for conversation continuity
- A `subprocess.Popen` reference for the active CLI process
- Thread-safe via `threading.Lock` (subprocess runs in executor threads)

### CLI Abstraction Layer

`bot/cli.py` handles three CLI backends with a unified interface:
- **Kimi**: uses `--quiet -y --thinking -S <session_id> -p <prompt>`
- **Claude Code**: uses `-p --dangerously-skip-permissions --effort high` with `--session-id` / `-r` for session resume
- **Codex**: uses `exec` subcommand with `--json` output, `--dangerously-bypass-approvals-and-sandbox`

Key functions: `build_cli_command()` constructs args per CLI type, `resolve_cli_executable()` resolves paths (with Windows .cmd/.bat fallback and npm global dir search), `should_reset_*_session()` detects stale sessions from error output.

### Handler Structure

`bot/handlers/__init__.py:register_handlers()` wires all command and message handlers based on `bot_mode`:

**CLI Mode (default):**
- `basic.py` — `/start`, `/reset`, `/kill`, `/cd`, `/pwd`, `/ls`, `/history`
- `chat.py` — text message handler; spawns CLI subprocess, reads output non-streaming via `process.communicate()` in executor, sends chunked responses to Telegram
- `shell.py` — `/exec` for direct shell commands (with dangerous command blocklist)
- `file.py` — file upload/download via Telegram
- `voice.py` — voice/audio message handler; uses Whisper for speech-to-text, then forwards to `chat.py` (optional, requires `openai-whisper` + `pydub` + FFmpeg)
- `admin.py` — `/bot_add`, `/bot_remove`, `/bot_start`, `/bot_stop`, `/bot_list`, `/bot_set_cli`, `/bot_set_workdir`, `/restart` (main bot only)

**Assistant Mode:**
- `assistant.py` — AI assistant with direct API calls, memory management, tool usage
- Commands: `/memory`, `/memory_add`, `/memory_search`, `/memory_delete`, `/memory_clear`, `/tool_stats`

**Kimi Web Mode (webcli):**
- `kimi_web.py` — launches `kimi web` and exposes it via ngrok tunnel
- Commands: `/start` (启动 Kimi Web + ngrok), `/stop` (停止服务), `/status` (查看状态)
- Automatically parses Kimi's local URL from startup output and forwards it to public internet

### Voice Recognition (Optional Feature)

`bot/whisper_service.py` provides speech-to-text via OpenAI Whisper (local model). Enabled via `WHISPER_ENABLED=true` in `.env`. Requires:
- Python packages: `openai-whisper`, `pydub`
- System dependency: FFmpeg

Key features:
- Supports Telegram voice messages and audio files
- Converts .oga → .wav → text
- Configurable model size (tiny/base/small/medium/large)
- Graceful degradation: if dependencies missing, voice handler is skipped without affecting other features
- See `docs/VOICE_QUICKSTART.md` for setup instructions

### Context Helpers

`bot/context_helpers.py` extracts bot/session/profile info from Telegram's `Update`/`Context` objects. The `MultiBotManager` instance is stored at `context.application.bot_data["manager"]`.

## Key Conventions

- All user-facing strings are in Chinese
- Config is loaded from environment variables (via `.env` + `python-dotenv`) in `bot/config.py`
- The `//` prefix in user messages is converted to `/` to forward CLI-native subcommands
- Telegram message output uses HTML parse mode; `safe_edit_text()` auto-falls back to plain text on parse errors
- Long outputs are split into chunks via `split_text_into_chunks()` with code block boundary awareness
- CLI process timeout is configurable via `CLI_EXEC_TIMEOUT` env var (default 4000s)

## Testing

Tests use `pytest` + `pytest-asyncio` with `unittest.mock`. The `conftest.py` provides:
- `mock_update` / `mock_context` fixtures with pre-configured `application.bot_data` structure matching `MultiBotManager._start_profile()`
- `clean_sessions` autouse fixture that clears the global session store before/after each test
- `ALLOWED_USER_IDS` is typically patched to `[]` (allow all) or a specific list for auth tests
