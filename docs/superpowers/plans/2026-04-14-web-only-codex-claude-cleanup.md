# Web-Only Codex Claude Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Telegram runtime, `kimi`, and retired assistant compatibility while preserving Web, `codex`/`claude`, and the current CLI-backed `cli` / `assistant` bots.

**Architecture:** First contract the provider surface to `codex` and `claude` only across config, storage, API, and frontend types. Then extract the remaining Web helper code out of Telegram handler modules, convert the core runtime to a tokenless Web-only profile manager, delete Telegram and voice code, and finish by removing the last old assistant/history assumptions plus docs and startup-script cleanup.

**Tech Stack:** Python, aiohttp, pytest, React, Vite, Vitest, Playwright

---

## File Structure

- Create: `bot/platform/output.py`
- Create: `bot/platform/terminal.py`
- Modify: `bot/platform/scripts.py`
- Modify: `bot/config.py`
- Modify: `bot/cli.py`
- Modify: `bot/cli_params.py`
- Modify: `bot/models.py`
- Modify: `bot/sessions.py`
- Modify: `bot/session_store.py`
- Modify: `bot/assistant_state.py`
- Modify: `bot/manager.py`
- Modify: `bot/main.py`
- Modify: `bot/web/api_service.py`
- Modify: `bot/web/server.py`
- Modify: `front/src/services/types.ts`
- Modify: `front/src/services/realWebBotClient.ts`
- Modify: `front/src/screens/BotListScreen.tsx`
- Modify: `front/src/screens/SettingsScreen.tsx`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `start.ps1`
- Modify: `start.sh`
- Delete: `bot/handlers/__init__.py`
- Delete: `bot/handlers/admin.py`
- Delete: `bot/handlers/basic.py`
- Delete: `bot/handlers/chat.py`
- Delete: `bot/handlers/file.py`
- Delete: `bot/handlers/file_browser.py`
- Delete: `bot/handlers/kimi_web.py`
- Delete: `bot/handlers/shell.py`
- Delete: `bot/handlers/tui_server.py`
- Delete: `bot/handlers/voice.py`
- Delete: `bot/context_helpers.py`
- Delete: `bot/whisper_service.py`

### Task 1: Contract Backend Provider Boundary To `codex` And `claude`

**Files:**
- Modify: `bot/config.py`
- Modify: `bot/cli.py`
- Modify: `bot/cli_params.py`
- Modify: `bot/models.py`
- Modify: `bot/sessions.py`
- Modify: `bot/session_store.py`
- Modify: `bot/assistant_state.py`
- Modify: `bot/web/api_service.py`
- Modify: `tests/test_manager.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_sessions.py`
- Modify: `tests/test_web_api.py`

- [ ] **Step 1: Write the failing backend boundary tests**

```python
# tests/test_manager.py
def test_load_profiles_rejects_kimi_cli_type(self, temp_dir: Path):
    storage = temp_dir / "bots.json"
    storage.write_text(
        json.dumps(
            {"bots": [{"alias": "kimi1", "cli_type": "kimi", "cli_path": "kimi", "working_dir": str(temp_dir)}]}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="kimi"):
        MultiBotManager(BotProfile(alias="main"), str(storage))


# tests/test_models.py
def test_creation(self, temp_dir: Path):
    s = UserSession(bot_id=1, bot_alias="main", user_id=100, working_dir=str(temp_dir))
    assert s.codex_session_id is None
    assert s.claude_session_id is None
    assert s.claude_session_initialized is False
    assert not hasattr(s, "kimi_session_id")


# tests/test_sessions.py
def test_session_restored_from_store(self, temp_dir: Path):
    from unittest.mock import patch
    from bot.session_store import save_session

    with patch("bot.session_store.STORE_FILE", temp_dir / ".session_store.json"):
        save_session(bot_id=1, user_id=100, codex_session_id="thread_restored_123", claude_session_id="claude_restored_789")
        with sessions_lock:
            sessions.clear()

        other_dir = temp_dir / "other"
        other_dir.mkdir()
        s = get_session(1, "main", 100, str(other_dir))

        assert s.codex_session_id == "thread_restored_123"
        assert s.claude_session_id == "claude_restored_789"
        assert s.claude_session_initialized is True
        assert not hasattr(s, "kimi_session_id")


# tests/test_web_api.py
def test_build_session_snapshot_omits_removed_kimi_session_id(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.codex_session_id = "thread-1"
    session.claude_session_id = "claude-1"
    session.claude_session_initialized = True

    snapshot = build_session_snapshot(web_manager.main_profile, session)

    assert snapshot["session_ids"] == {
        "codex_session_id": "thread-1",
        "claude_session_id": "claude-1",
        "claude_session_initialized": True,
    }
```

- [ ] **Step 2: Run the focused backend tests to verify RED**

Run: `python -m pytest tests/test_manager.py tests/test_models.py tests/test_sessions.py tests/test_web_api.py -q`
Expected:
- FAIL because `validate_cli_type()` still accepts `kimi`
- FAIL because `UserSession`, `session_store`, and `build_session_snapshot()` still expose `kimi_session_id`

- [ ] **Step 3: Remove `kimi` from the backend provider model**

```python
# bot/config.py
SUPPORTED_CLI_TYPES = {"claude", "codex"}
```

```python
# bot/models.py
@dataclass
class BotProfile:
    alias: str
    cli_type: str = CLI_TYPE
    cli_path: str = CLI_PATH
    working_dir: str = WORKING_DIR
    enabled: bool = True
    bot_mode: str = "cli"
    avatar_name: str = "bot-default.png"
    cli_params: CliParamsConfig = field(default_factory=CliParamsConfig)


@dataclass
class UserSession:
    bot_id: int
    bot_alias: str
    user_id: int
    working_dir: str
    browse_dir: Optional[str] = None
    history: List[dict] = field(default_factory=list)
    codex_session_id: Optional[str] = None
    claude_session_id: Optional[str] = None
    claude_session_initialized: bool = False
```

```python
# bot/session_store.py
def save_session(
    bot_id: int,
    user_id: int,
    codex_session_id: Optional[str] = None,
    claude_session_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    browse_dir: Optional[str] = None,
    history: Optional[list[dict]] = None,
    web_turn_overlays: Optional[list[dict]] = None,
    message_count: Optional[int] = None,
    last_activity: Optional[str] = None,
    running_user_text: Optional[str] = None,
    running_preview_text: Optional[str] = None,
    running_started_at: Optional[str] = None,
    running_updated_at: Optional[str] = None,
):
    session_data: dict = {}
    if codex_session_id:
        session_data["codex_session_id"] = codex_session_id
    if claude_session_id:
        session_data["claude_session_id"] = claude_session_id
```

```python
# bot/assistant_state.py
save_assistant_runtime_state(
    home,
    user_id,
    {
        "working_dir": current.working_dir,
        "browse_dir": current.browse_dir or "",
        "codex_session_id": current.codex_session_id,
        "claude_session_id": current.claude_session_id,
        "claude_session_initialized": current.claude_session_initialized,
        "message_count": current.message_count,
        "managed_prompt_hash_seen": current.managed_prompt_hash_seen,
        "last_activity": current.last_activity.isoformat(),
        "running_user_text": current.running_user_text,
        "running_preview_text": current.running_preview_text,
        "running_started_at": current.running_started_at,
        "running_updated_at": current.running_updated_at,
        "web_turn_overlays": [dict(item) for item in current.web_turn_overlays[-20:]],
    },
)
```

```python
# bot/web/api_service.py
def _build_session_ids(session: UserSession) -> dict[str, Any]:
    return {
        "codex_session_id": session.codex_session_id,
        "claude_session_id": session.claude_session_id,
        "claude_session_initialized": session.claude_session_initialized,
    }
```

```python
# bot/cli_params.py
DEFAULT_PARAMS_MAP = {
    "claude": DEFAULT_CLAUDE_PARAMS,
    "codex": DEFAULT_CODEX_PARAMS,
}
SUPPORTED_CLI_TYPES = set(DEFAULT_PARAMS_MAP.keys())
```

- [ ] **Step 4: Run the focused backend tests to verify GREEN**

Run: `python -m pytest tests/test_manager.py tests/test_models.py tests/test_sessions.py tests/test_web_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit the backend provider-boundary contraction**

```bash
git add bot/config.py bot/cli.py bot/cli_params.py bot/models.py bot/sessions.py bot/session_store.py bot/assistant_state.py bot/web/api_service.py tests/test_manager.py tests/test_models.py tests/test_sessions.py tests/test_web_api.py
git commit -m "refactor: drop kimi from backend runtime"
```

### Task 2: Remove `kimi` From Frontend, Assets, And User-Facing Config Surface

**Files:**
- Modify: `front/src/services/types.ts`
- Modify: `front/src/services/realWebBotClient.ts`
- Modify: `front/src/screens/BotListScreen.tsx`
- Modify: `front/src/screens/SettingsScreen.tsx`
- Modify: `front/src/services/mockWebBotClient.ts`
- Modify: `front/src/mocks/bots.ts`
- Modify: `front/src/utils/avatar.ts`
- Modify: `front/src/test/app.test.tsx`
- Modify: `front/src/test/real-client.test.ts`
- Modify: `front/src/test/settings-screen.test.tsx`
- Modify: `.env.example`
- Modify: `README.md`
- Delete: `front/public/assets/avatars/kimi-teal.png`

- [ ] **Step 1: Write the failing UI and config-surface tests**

```tsx
// front/src/test/settings-screen.test.tsx
test("CLI type selector only shows codex and claude", async () => {
  render(<SettingsScreen client={client} />);

  const select = await screen.findByLabelText("CLI 类型");
  const options = within(select).getAllByRole("option").map((item) => item.textContent);

  expect(options).toEqual(["codex", "claude"]);
});


// front/src/test/app.test.tsx
test("create bot form no longer asks for telegram token", async () => {
  render(<App client={client} />);

  expect(screen.queryByLabelText("新 Bot Token")).not.toBeInTheDocument();
});
```

```python
# tests/test_start_scripts.py
def test_start_sh_is_web_only():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert 'export WEB_ENABLED="true"' in content
    assert "TELEGRAM_ENABLED" not in content
```

- [ ] **Step 2: Run the focused frontend/config tests to verify RED**

Run: `cd front && npm test -- src/test/app.test.tsx src/test/real-client.test.ts src/test/settings-screen.test.tsx`
Run: `python -m pytest tests/test_start_scripts.py -q`
Expected:
- FAIL because the UI still renders `kimi` and token fields
- FAIL because startup/config docs still mention Telegram toggles

- [ ] **Step 3: Remove `kimi` and token from the UI-facing surface**

```ts
// front/src/services/types.ts
export type CliType = "claude" | "codex";

export type CreateBotInput = {
  alias: string;
  botMode: "cli" | "assistant";
  cliType: CliType;
  cliPath: string;
  workingDir: string;
  avatarName: string;
};
```

```tsx
// front/src/screens/SettingsScreen.tsx
<select value={cliTypeDraft} onChange={(event) => setCliTypeDraft(event.target.value)}>
  <option value="codex">codex</option>
  <option value="claude">claude</option>
</select>
```

```tsx
// front/src/screens/BotListScreen.tsx
<select value={createCliType} onChange={(event) => setCreateCliType(event.target.value as CliType)}>
  <option value="codex">codex</option>
  <option value="claude">claude</option>
</select>
```

```ts
// front/src/utils/avatar.ts
export const AVATAR_OPTIONS = [
  { name: "claude-blue.png", url: "/assets/avatars/claude-blue.png" },
  { name: "codex-slate.png", url: "/assets/avatars/codex-slate.png" },
  { name: "bot-default.png", url: "/assets/avatars/bot-default.png" },
];
```

```env
# .env.example
# Main CLI type: codex / claude
CLI_TYPE=codex

# CLI executable path.
# If the command is already in PATH, keeping `codex` / `claude` is enough.
CLI_PATH=codex

WEB_ENABLED=true
```

```md
# README.md
- 一个支持 Windows 与 Ubuntu/Debian Linux 的 Web AI CLI Bridge。
- 支持 `codex` / `claude`
- 入口仅为 Web 页面，不再提供 Telegram 机器人入口
```

- [ ] **Step 4: Run the focused frontend/config tests to verify GREEN**

Run: `cd front && npm test -- src/test/app.test.tsx src/test/real-client.test.ts src/test/settings-screen.test.tsx`
Run: `python -m pytest tests/test_start_scripts.py -q`
Expected: PASS

- [ ] **Step 5: Commit the UI-facing provider cleanup**

```bash
git add front/src/services/types.ts front/src/services/realWebBotClient.ts front/src/screens/BotListScreen.tsx front/src/screens/SettingsScreen.tsx front/src/services/mockWebBotClient.ts front/src/mocks/bots.ts front/src/utils/avatar.ts front/src/test/app.test.tsx front/src/test/real-client.test.ts front/src/test/settings-screen.test.tsx .env.example README.md tests/test_start_scripts.py
git add -u front/public/assets/avatars/kimi-teal.png
git commit -m "refactor: remove kimi and telegram fields from ui"
```

### Task 3: Extract Script Metadata And ANSI Sanitizers Out Of Telegram Handlers

**Files:**
- Create: `bot/platform/output.py`
- Modify: `bot/platform/scripts.py`
- Modify: `bot/web/api_service.py`
- Modify: `tests/test_web_api.py`
- Modify: `tests/test_main_web.py`

- [ ] **Step 1: Write the failing import-boundary tests**

```python
# tests/test_web_api.py
def test_web_api_service_no_longer_imports_telegram_shell_or_admin_handlers():
    source = Path("bot/web/api_service.py").read_text(encoding="utf-8")

    assert "from bot.handlers.admin import" not in source
    assert "from bot.handlers.shell import" not in source


# tests/test_main_web.py
def test_web_server_no_longer_imports_tui_handler_module():
    source = Path("bot/web/server.py").read_text(encoding="utf-8")

    assert "from bot.handlers.tui_server import" not in source
```

- [ ] **Step 2: Run the focused import-boundary tests to verify RED**

Run: `python -m pytest tests/test_web_api.py tests/test_main_web.py -q`
Expected:
- FAIL because `bot/web/api_service.py` still imports `bot.handlers.admin` and `bot.handlers.shell`
- FAIL because `bot/web/server.py` still imports `bot.handlers.tui_server`

- [ ] **Step 3: Move shared helper code into `bot/platform/*`**

```python
# bot/platform/output.py
import re

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[@-_]")


def strip_ansi_escape(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")
```

```python
# bot/platform/scripts.py
def list_available_scripts() -> list[tuple[str, str, str, Path]]:
    if not SCRIPTS_DIR.exists():
        return []

    scripts = []
    for item in SCRIPTS_DIR.iterdir():
        if item.is_file() and item.suffix.lower() in allowed_script_extensions():
            scripts.append((item.stem, get_script_display_name(item), get_script_description(item), item))

    scripts.sort(key=lambda row: row[0])
    return scripts


def execute_script(script_path: Path) -> tuple[bool, str]:
    command, use_shell = build_script_command(script_path)
    result = subprocess.run(
        command,
        capture_output=True,
        text=False,
        timeout=SCRIPT_EXEC_TIMEOUT,
        shell=use_shell,
        env=build_git_proxy_env(),
    )
    return _format_script_result(result.returncode, result.stdout, result.stderr)
```

```python
# bot/web/api_service.py
from bot.platform.output import strip_ansi_escape
from bot.platform.scripts import execute_script, list_available_scripts, stream_execute_script
```

- [ ] **Step 4: Run the focused import-boundary tests to verify GREEN**

Run: `python -m pytest tests/test_web_api.py tests/test_main_web.py -q`
Expected: PASS

- [ ] **Step 5: Commit the script/output extraction**

```bash
git add bot/platform/output.py bot/platform/scripts.py bot/web/api_service.py tests/test_web_api.py tests/test_main_web.py
git commit -m "refactor: move web script helpers out of telegram handlers"
```

### Task 4: Extract Web Terminal Creation Into Platform Layer

**Files:**
- Create: `bot/platform/terminal.py`
- Modify: `bot/web/server.py`
- Modify: `tests/test_main_web.py`

- [ ] **Step 1: Write the failing terminal import-boundary test**

```python
# tests/test_main_web.py
def test_web_server_uses_platform_terminal_module():
    source = Path("bot/web/server.py").read_text(encoding="utf-8")

    assert "from bot.platform.terminal import create_shell_process" in source
    assert "from bot.handlers.tui_server import create_shell_process" not in source
```

- [ ] **Step 2: Run the focused terminal test to verify RED**

Run: `python -m pytest tests/test_main_web.py -q`
Expected: FAIL because `bot/web/server.py` still imports `bot.handlers.tui_server`

- [ ] **Step 3: Move `create_shell_process()` to `bot/platform/terminal.py`**

```python
# bot/platform/terminal.py
def create_shell_process(shell_type: str, cwd: str, use_pty: bool = True) -> PtyWrapper:
    if shell_type == "powershell":
        cmdline = "powershell.exe -NoLogo -NoExit" if sys.platform == "win32" else "pwsh -NoLogo -NoExit"
    elif shell_type == "cmd":
        cmdline = "cmd.exe"
    elif shell_type == "bash":
        cmdline = "bash"
    else:
        cmdline = shell_type

    if sys.platform == "win32" and use_pty and _WINPTY_AVAILABLE:
        process = PtyProcess.spawn(
            cmdline,
            cwd=cwd,
            dimensions=(40, 120),
            env={
                **os.environ,
                "FORCE_COLOR": "1",
                "TERM": "xterm-256color",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            },
        )
        return PtyWrapper(process, is_pty=True)

    if sys.platform == "win32":
        process = subprocess.Popen(
            cmdline.split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env={
                **os.environ,
                "FORCE_COLOR": "1",
                "TERM": "xterm-256color",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            },
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            bufsize=0,
        )
        return PtyWrapper(process, is_pty=False)

    if use_pty:
        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            cmdline.split(),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
            **build_subprocess_group_kwargs(),
        )
        os.close(slave_fd)
        return PtyWrapper(PosixPtyProcess(process, master_fd), is_pty=True)

    process = subprocess.Popen(
        cmdline.split(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env={**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"},
        bufsize=0,
        **build_subprocess_group_kwargs(),
    )
    return PtyWrapper(process, is_pty=False)
```

```python
# bot/web/server.py
from bot.platform.terminal import create_shell_process
```

- [ ] **Step 4: Run the focused terminal test to verify GREEN**

Run: `python -m pytest tests/test_main_web.py -q`
Expected: PASS

- [ ] **Step 5: Commit the terminal extraction**

```bash
git add bot/platform/terminal.py bot/web/server.py tests/test_main_web.py
git commit -m "refactor: move web terminal creation to platform layer"
```

### Task 5: Make Profiles And Manager Web-Only And Tokenless

**Files:**
- Modify: `bot/models.py`
- Modify: `bot/manager.py`
- Modify: `bot/web/api_service.py`
- Modify: `bot/web/server.py`
- Modify: `front/src/services/types.ts`
- Modify: `front/src/services/realWebBotClient.ts`
- Modify: `front/src/screens/BotListScreen.tsx`
- Modify: `tests/test_manager.py`
- Modify: `tests/test_web_api.py`
- Modify: `front/src/test/app.test.tsx`
- Modify: `front/src/test/real-client.test.ts`

- [ ] **Step 1: Write the failing tokenless-profile tests**

```python
# tests/test_manager.py
def test_bot_profile_to_dict_omits_token():
    profile = BotProfile(alias="team2", cli_type="claude", cli_path="claude")

    payload = profile.to_dict()

    assert "token" not in payload


@pytest.mark.asyncio
async def test_add_bot_no_longer_requires_token(self, temp_dir: Path):
    storage = temp_dir / "bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main"), str(storage))

    with patch("bot.manager.resolve_cli_executable", return_value="codex"):
        created = await manager.add_bot("team2", "codex", "codex", str(temp_dir), "cli")

    assert created.alias == "team2"
```

```tsx
// front/src/test/real-client.test.ts
test("createBot sends no token field", async () => {
  await client.createBot({
    alias: "team2",
    botMode: "cli",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\demo",
    avatarName: "codex-slate.png",
  });

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/admin/bots"),
    expect.objectContaining({
      body: JSON.stringify({
        alias: "team2",
        bot_mode: "cli",
        cli_type: "codex",
        cli_path: "codex",
        working_dir: "C:\\workspace\\demo",
        avatar_name: "codex-slate.png",
      }),
    }),
  );
});
```

- [ ] **Step 2: Run the focused tokenless-profile tests to verify RED**

Run: `python -m pytest tests/test_manager.py tests/test_web_api.py -q`
Run: `cd front && npm test -- src/test/app.test.tsx src/test/real-client.test.ts`
Expected:
- FAIL because `BotProfile` still serializes `token`
- FAIL because `manager.add_bot()` and the Web client still expect token payloads

- [ ] **Step 3: Remove token from profile storage and Web API surfaces**

```python
# bot/models.py
@dataclass
class BotProfile:
    alias: str
    cli_type: str = CLI_TYPE
    cli_path: str = CLI_PATH
    working_dir: str = WORKING_DIR
    enabled: bool = True
    bot_mode: str = "cli"
    avatar_name: str = "bot-default.png"
    cli_params: CliParamsConfig = field(default_factory=CliParamsConfig)

    def to_dict(self) -> dict:
        result = {
            "alias": self.alias,
            "cli_type": self.cli_type,
            "cli_path": self.cli_path,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
            "bot_mode": self.bot_mode,
            "avatar_name": self.avatar_name,
        }
```

```python
# bot/manager.py
async def add_bot(
    self,
    alias: str,
    cli_type: Optional[str] = None,
    cli_path: Optional[str] = None,
    working_dir: Optional[str] = None,
    bot_mode: Optional[str] = None,
    avatar_name: Optional[str] = None,
) -> BotProfile:
    alias = alias.strip().lower()
    self._validate_alias(alias)
    cli_type = validate_cli_type(cli_type or CLI_TYPE)
    cli_path = (cli_path or CLI_PATH).strip()
    bot_mode = (bot_mode or "cli").strip().lower()
```

```python
# bot/web/server.py
data = await add_managed_bot(
    self.manager,
    alias=body.get("alias", ""),
    cli_type=body.get("cli_type"),
    cli_path=body.get("cli_path"),
    working_dir=body.get("working_dir"),
    bot_mode=body.get("bot_mode"),
    avatar_name=body.get("avatar_name"),
)
```

```ts
// front/src/services/realWebBotClient.ts
body: JSON.stringify({
  alias: input.alias,
  bot_mode: input.botMode,
  cli_type: input.cliType,
  cli_path: input.cliPath,
  working_dir: input.workingDir,
  avatar_name: input.avatarName,
}),
```

- [ ] **Step 4: Run the focused tokenless-profile tests to verify GREEN**

Run: `python -m pytest tests/test_manager.py tests/test_web_api.py -q`
Run: `cd front && npm test -- src/test/app.test.tsx src/test/real-client.test.ts`
Expected: PASS

- [ ] **Step 5: Commit the tokenless manager/profile surface**

```bash
git add bot/models.py bot/manager.py bot/web/api_service.py bot/web/server.py front/src/services/types.ts front/src/services/realWebBotClient.ts front/src/screens/BotListScreen.tsx tests/test_manager.py tests/test_web_api.py front/src/test/app.test.tsx front/src/test/real-client.test.ts
git commit -m "refactor: make bot profiles web-only and tokenless"
```

### Task 6: Remove Telegram Runtime And Delete Telegram/Voice Modules

**Files:**
- Modify: `bot/config.py`
- Modify: `bot/main.py`
- Modify: `bot/manager.py`
- Modify: `bot/web/server.py`
- Modify: `requirements.txt`
- Modify: `tests/test_main_web.py`
- Modify: `tests/test_manager.py`
- Modify: `tests/test_web_api.py`
- Delete: `bot/handlers/__init__.py`
- Delete: `bot/handlers/admin.py`
- Delete: `bot/handlers/basic.py`
- Delete: `bot/handlers/chat.py`
- Delete: `bot/handlers/file.py`
- Delete: `bot/handlers/file_browser.py`
- Delete: `bot/handlers/kimi_web.py`
- Delete: `bot/handlers/shell.py`
- Delete: `bot/handlers/tui_server.py`
- Delete: `bot/handlers/voice.py`
- Delete: `bot/context_helpers.py`
- Delete: `bot/whisper_service.py`
- Delete: `tests/test_context_helpers.py`
- Delete: `tests/test_handlers/test_voice.py`

- [ ] **Step 1: Write the failing runtime-boundary tests**

```python
# tests/test_main_web.py
def test_main_does_not_reference_telegram_env_anymore():
    source = Path("bot/main.py").read_text(encoding="utf-8")

    assert "TELEGRAM_ENABLED" not in source
    assert "TELEGRAM_BOT_TOKEN" not in source


# tests/test_manager.py
def test_manager_module_no_longer_imports_telegram():
    source = Path("bot/manager.py").read_text(encoding="utf-8")

    assert "from telegram" not in source
    assert "telegram.ext.Application" not in source
```

- [ ] **Step 2: Run the focused runtime-boundary tests to verify RED**

Run: `python -m pytest tests/test_main_web.py tests/test_manager.py tests/test_web_api.py -q`
Expected:
- FAIL because `bot/main.py`, `bot/manager.py`, and `bot/web/server.py` still import Telegram runtime objects

- [ ] **Step 3: Convert startup and manager lifecycle to Web-only**

```python
# bot/config.py
WEB_ENABLED = os.environ.get("WEB_ENABLED", "true").lower() == "true"
```

```python
# bot/main.py
async def run_all_bots():
    config.RESTART_REQUESTED = False
    config.RESTART_EVENT = asyncio.Event()

    main_profile = BotProfile(
        alias="main",
        cli_type=CLI_TYPE,
        cli_path=CLI_PATH,
        working_dir=WORKING_DIR,
        enabled=True,
    )

    manager = MultiBotManager(main_profile=main_profile, storage_file=MANAGED_BOTS_FILE)
    web_server = WebApiServer(manager) if config.WEB_ENABLED else None

    if web_server is None:
        raise RuntimeError("WEB_ENABLED 不能为 false")

    await web_server.start()
    _print_web_access_lines()
    try:
        await config.RESTART_EVENT.wait()
    finally:
        await web_server.stop(preserve_tunnel=config.RESTART_REQUESTED)
        await manager.shutdown_all()
```

```python
# bot/manager.py
class MultiBotManager:
    def __init__(self, main_profile: BotProfile, storage_file: str):
        self.main_profile = main_profile
        self.storage_file = Path(storage_file)
        self.managed_profiles: Dict[str, BotProfile] = {}
        self._lock = asyncio.Lock()
        self._load_profiles()
        self._apply_persisted_avatar_names()

    async def start_all(self):
        return None

    async def shutdown_all(self):
        return None

    async def start_bot(self, alias: str):
        async with self._lock:
            profile = self._get_profile_for_update(alias)
            profile.enabled = True
            self._save_profiles()

    async def stop_bot(self, alias: str):
        async with self._lock:
            profile = self._get_profile_for_update(alias)
            profile.enabled = False
            self._save_profiles()
```

```python
# bot/web/server.py
async def health(self, request: web.Request) -> web.Response:
    return _json(
        {
            "ok": True,
            "service": "telegram-cli-bridge-web",
            "web_enabled": True,
            "host": WEB_HOST,
            "port": WEB_PORT,
        }
    )
```

```text
# requirements.txt
python-dotenv>=1.0.0
aiohttp>=3.10.0
PyYAML>=6.0
psutil>=5.9.0
pytest>=7.0
pytest-asyncio>=0.21.0
```

- [ ] **Step 4: Run the focused runtime tests to verify GREEN**

Run: `python -m pytest tests/test_main_web.py tests/test_manager.py tests/test_web_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit the Web-only runtime conversion**

```bash
git add bot/config.py bot/main.py bot/manager.py bot/web/server.py requirements.txt tests/test_main_web.py tests/test_manager.py tests/test_web_api.py
git add -u bot/handlers bot/context_helpers.py bot/whisper_service.py tests/test_context_helpers.py tests/test_handlers/test_voice.py
git commit -m "refactor: remove telegram runtime"
```

### Task 7: Remove Legacy Assistant History Assumptions And Finish Startup/Docs Sweep

**Files:**
- Modify: `bot/assistant_state.py`
- Modify: `bot/web/api_service.py`
- Modify: `tests/test_assistant_state.py`
- Modify: `tests/test_assistant.py`
- Modify: `tests/test_web_api.py`
- Modify: `tests/test_start_scripts.py`
- Modify: `start.ps1`
- Modify: `start.sh`
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing assistant-legacy cleanup tests**

```python
# tests/test_assistant_state.py
def test_assistant_session_persist_writes_overlay_state_without_history(tmp_path):
    from bot.assistant_state import attach_assistant_persist_hook

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    session = UserSession(bot_id=1, bot_alias="assistant1", user_id=1001, working_dir=str(workdir))
    attach_assistant_persist_hook(session, home, 1001)

    session.browse_dir = str(workdir / "notes")
    session.running_user_text = "继续"
    session.persist()

    data = json.loads((home.root / "state" / "users" / "1001.json").read_text(encoding="utf-8"))
    assert "history" not in data
    assert data["browse_dir"] == str(workdir / "notes")
    assert data["running_user_text"] == "继续"


# tests/test_start_scripts.py
def test_start_ps1_starts_web_runtime_without_mode_switch():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("default", "web")' not in content
    assert 'Start-Process' in content
    assert 'python' in content
```

- [ ] **Step 2: Run the focused legacy-cleanup tests to verify RED**

Run: `python -m pytest tests/test_assistant_state.py tests/test_assistant.py tests/test_web_api.py tests/test_start_scripts.py -q`
Expected:
- FAIL because tests and startup scripts still reflect old Telegram/history assumptions

- [ ] **Step 3: Remove the remaining legacy assumptions**

```python
# bot/assistant_state.py
def attach_assistant_persist_hook(session, home: AssistantHome, user_id: int) -> None:
    def _persist(current) -> None:
        save_assistant_runtime_state(
            home,
            user_id,
            {
                "working_dir": current.working_dir,
                "browse_dir": current.browse_dir or "",
                "codex_session_id": current.codex_session_id,
                "claude_session_id": current.claude_session_id,
                "claude_session_initialized": current.claude_session_initialized,
                "message_count": current.message_count,
                "managed_prompt_hash_seen": current.managed_prompt_hash_seen,
                "last_activity": current.last_activity.isoformat(),
                "running_user_text": current.running_user_text,
                "running_preview_text": current.running_preview_text,
                "running_started_at": current.running_started_at,
                "running_updated_at": current.running_updated_at,
                "web_turn_overlays": [dict(item) for item in current.web_turn_overlays[-20:]],
            },
        )

    session.persist_hook = _persist
```

```powershell
# start.ps1
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
$env:WEB_ENABLED = "true"
$env:TELEGRAM_CLI_BRIDGE_SUPERVISOR = "1"

while ($true) {
    python -m bot
    if ($LASTEXITCODE -ne 75) {
        exit $LASTEXITCODE
    }
    Start-Sleep -Seconds 1
}
```

```bash
# start.sh
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export WEB_ENABLED="true"
export TELEGRAM_CLI_BRIDGE_SUPERVISOR=1

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "错误: 未找到 python3 或 python，请先安装 Python 并加入 PATH" >&2
  exit 127
fi

while true; do
  set +e
  "$PYTHON_BIN" -m bot
  exit_code=$?
  set -e
  if [[ "$exit_code" -ne 75 ]]; then
    exit "$exit_code"
  fi
  sleep 1
done
```

```md
# README.md
## 功能概览

- Web 管理界面
- 支持 `codex` / `claude`
- 支持 `cli` / `assistant`
- 支持文件浏览、上传、下载、查看
- Web 端支持 Git 概览与常见操作
- 支持一个主 profile + 多个托管 profile
```

- [ ] **Step 4: Run the focused legacy-cleanup tests plus final regression sweep**

Run: `python -m pytest tests/test_assistant_state.py tests/test_assistant.py tests/test_web_api.py tests/test_main_web.py tests/test_manager.py tests/test_sessions.py tests/test_start_scripts.py -q`
Run: `cd front && npm test`
Run: `cd front && npm run build`
Expected:
- PASS on backend tests
- PASS on frontend tests
- PASS on frontend build

- [ ] **Step 5: Commit the final cleanup sweep**

```bash
git add bot/assistant_state.py bot/web/api_service.py tests/test_assistant_state.py tests/test_assistant.py tests/test_web_api.py tests/test_start_scripts.py start.ps1 start.sh README.md .env.example
git commit -m "refactor: finish web-only cleanup"
```

## Self-Review Checklist

- Provider boundary coverage:
  - Task 1 removes `kimi` from backend runtime and persistence.
  - Task 2 removes `kimi` from frontend, assets, and docs.
- Shared-helper extraction coverage:
  - Task 3 removes `bot/web/api_service.py` imports from Telegram admin/shell handlers.
  - Task 4 removes `bot/web/server.py` import from `bot/handlers/tui_server.py`.
- Telegram removal coverage:
  - Task 6 removes Telegram runtime/config/dependency and deletes handler/context/voice files.
- Assistant cleanup coverage:
  - Task 7 removes old assistant history assumptions and keeps only `.assistant/` runtime state that still matters.
- Placeholder scan:
  - No `TODO`, `TBD`, or “implement later” markers remain.
- Type consistency:
  - `CliType` is consistently `codex | claude`.
  - Session persistence consistently uses only `codex_session_id`, `claude_session_id`, and `claude_session_initialized`.
