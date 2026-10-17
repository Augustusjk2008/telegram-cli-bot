"""Profile-scoped capabilities for agents using the host's existing SSH bridge."""
from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bot.runtime_paths import get_app_data_root

REMOTE_MCP_SERVER_NAME = "tcb-remote"
# Keep the old name available for callers that used the remote bridge name.
SERVER_NAME = REMOTE_MCP_SERVER_NAME
REMOTE_CONFIG_ENV = "TCB_REMOTE_MCP_CONFIG"
REMOTE_MCP_STATE_FILENAME = ".tcb-remote-mcp-state.json"
REMOTE_MCP_LOCK_FILENAME = "mcp_config.json.lock"
REMOTE_MCP_MANAGED_MARKER = "orbit-safe-claw"
MAX_RESPONSE_BYTES = 512_000
_lock = threading.RLock()
_bindings: dict[str, tuple[Any, str]] = {}
_profile_tokens: dict[str, str] = {}
_workspace_locks: dict[str, threading.RLock] = {}
_workspace_locks_guard = threading.Lock()


class RemoteChatPreparationError(ValueError):
    """A remote chat configuration could not be prepared safely."""

    def __init__(self, code: str, message: str, *, status: int = 409, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.data = data or {}


def remote_workspace_fingerprint(profile: Any) -> str:
    remote = getattr(profile, "remote_workspace", None)
    if not remote:
        return ""
    return hashlib.sha256(json.dumps(remote, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _profile_key(profile: Any) -> str:
    return str(profile.alias)


def _workspace_mcp_config_path(working_dir: Path | str) -> Path:
    return Path(working_dir).expanduser().resolve() / ".agents" / "mcp_config.json"


def _workspace_mcp_state_path(working_dir: Path | str) -> Path:
    return _workspace_mcp_config_path(working_dir).with_name(REMOTE_MCP_STATE_FILENAME)


def _workspace_mcp_lock_path(config_path: Path) -> Path:
    return config_path.with_name(REMOTE_MCP_LOCK_FILENAME)


def get_remote_mcp_config_path(working_dir: Path | str) -> Path:
    """Return the workspace-scoped Antigravity MCP configuration path."""
    return _workspace_mcp_config_path(working_dir)


def get_remote_mcp_state_path(working_dir: Path | str) -> Path:
    """Return the ownership state path for the generated remote MCP entry."""
    return _workspace_mcp_state_path(working_dir)


def get_remote_mcp_lock_path(working_dir: Path | str) -> Path:
    """Return the cross-process lock path for the workspace MCP configuration."""
    return _workspace_mcp_lock_path(_workspace_mcp_config_path(working_dir))


# Descriptive aliases used by API/status callers that refer to the workspace
# scope rather than the remote bridge capability.
get_workspace_mcp_config_path = get_remote_mcp_config_path
get_workspace_mcp_state_path = get_remote_mcp_state_path
get_workspace_mcp_lock_path = get_remote_mcp_lock_path


def _ensure_lock_byte(handle: Any) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _try_workspace_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, 13, 36}:
                raise BlockingIOError from exc
            raise
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_workspace_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _workspace_mcp_lock(config_path: Path, *, timeout_seconds: float = 10.0):
    lock_path = _workspace_mcp_lock_path(config_path)
    key = str(lock_path.absolute()).lower()
    with _workspace_locks_guard:
        local_lock = _workspace_locks.setdefault(key, threading.RLock())
    with local_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            _ensure_lock_byte(handle)
            deadline = time.monotonic() + max(0.1, float(timeout_seconds))
            while True:
                try:
                    _try_workspace_lock(handle)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise RemoteChatPreparationError(
                            "remote_mcp_config_busy",
                            f"无法取得 Antigravity MCP 配置锁: {lock_path}",
                            data={"config_path": str(config_path)},
                        )
                    time.sleep(0.05)
            try:
                yield
            finally:
                _release_workspace_lock(handle)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_workspace_mcp_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteChatPreparationError(
            "remote_mcp_config_broken",
            f"Antigravity MCP 配置无效: {path}",
            data={"config_path": str(path)},
        ) from exc
    if not isinstance(value, dict):
        raise RemoteChatPreparationError(
            "remote_mcp_config_broken",
            f"Antigravity MCP 配置必须是 JSON 对象: {path}",
            data={"config_path": str(path)},
        )
    servers = value.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise RemoteChatPreparationError(
            "remote_mcp_config_broken",
            "Antigravity MCP 配置的 mcpServers 必须是对象",
            data={"config_path": str(path)},
        )
    return value


def _load_workspace_mcp_state(path: Path) -> tuple[dict[str, Any] | None, bool]:
    if not path.exists():
        return None, False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, True
    return (value, False) if isinstance(value, dict) else (None, True)


def _managed_workspace_entry(entry: Any, state: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    return bool(state) and entry == state.get("managed_entry")


def _workspace_mcp_entry(private_config_path: Path, working_dir: Path) -> dict[str, Any]:
    return {
        "command": sys.executable,
        "args": [str(Path(__file__).with_name("mcp_stdio.py").resolve()), "--config", str(private_config_path)],
        "cwd": str(working_dir),
    }


def _remote_mcp_tools() -> tuple[str, ...]:
    return tuple(item["name"] for item in remote_tools())


def _remote_mcp_status_payload(
    *,
    state: str,
    message: str,
    config_path: Path,
    allowed_tools: tuple[str, ...],
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    status_line_path = Path(__file__).resolve().parents[2] / "bot" / "antigravity_statusline.py"
    status = {
        "state": state,
        "server_name": REMOTE_MCP_SERVER_NAME,
        "message": message,
        "config_path": str(config_path),
        "scope": "workspace",
        "allowed_tools": list(allowed_tools),
        "diagnostics": list(diagnostics or []),
        "status_line_command": [sys.executable, str(status_line_path)],
        "status_line_snippet": json.dumps(
            {"statusLine": {"type": "command", "command": f'"{sys.executable}" "{status_line_path}"'}},
            ensure_ascii=False,
        ),
        "setup_instructions": "Antigravity 会从当前本地控制目录的 .agents/mcp_config.json 自动发现 tcb-remote；权限策略保持 Ask。",
        "ask_policy": "ask",
    }
    return status


def inspect_remote_mcp_config(profile: Any) -> dict[str, Any]:
    """Inspect the generated workspace entry without mutating local files.

    The returned status is safe for the Web API: it contains the workspace path,
    tool names and actionable diagnostics, while omitting bridge URLs, tokens and
    SSH host key material.
    """
    remote = getattr(profile, "remote_workspace", None)
    if not remote:
        return {}
    working_dir = Path(getattr(profile, "working_dir", ".")).expanduser().resolve()
    config_path = _workspace_mcp_config_path(working_dir)
    state_path = _workspace_mcp_state_path(working_dir)
    tools = _remote_mcp_tools()
    try:
        config = _load_workspace_mcp_json(config_path)
    except RemoteChatPreparationError as exc:
        return _remote_mcp_status_payload(
            state="broken",
            message=str(exc),
            config_path=config_path,
            allowed_tools=tools,
            diagnostics=[{
                "code": exc.code,
                "kind": "config",
                "message": str(exc),
                "action": "修复或删除损坏的 .agents/mcp_config.json 后重试",
            }],
        )

    state, state_broken = _load_workspace_mcp_state(state_path)
    if state_broken or (state and (
        state.get("server_name") != REMOTE_MCP_SERVER_NAME
        or state.get("managed_by") != REMOTE_MCP_MANAGED_MARKER
        or state.get("owner_key") != _profile_key(profile)
        or not isinstance(state.get("managed_entry"), dict)
    )):
        message = "tcb-remote ownership state is invalid"
        return _remote_mcp_status_payload(
            state="broken",
            message=message,
            config_path=config_path,
            allowed_tools=tools,
            diagnostics=[{
                "code": "remote_mcp_config_broken",
                "kind": "config",
                "message": message,
                "action": f"检查或删除 {state_path} 后重试",
            }],
        )

    servers = config.get("mcpServers") if isinstance(config.get("mcpServers"), dict) else {}
    current_entry = servers.get(REMOTE_MCP_SERVER_NAME)
    fingerprint = remote_workspace_fingerprint(profile)
    private_config_path = get_app_data_root() / "remote-chat" / hashlib.sha256(
        f"{_profile_key(profile)}:{fingerprint}".encode()
    ).hexdigest() / "config.json"
    expected_entry = _workspace_mcp_entry(private_config_path, working_dir)
    if current_entry is None:
        state_name = "stale" if state else "missing"
        message = "工作区 tcb-remote MCP 尚未配置" if state_name == "missing" else "工作区 tcb-remote MCP 配置已失效"
        diagnostics = [] if state_name == "missing" else [{
            "code": "remote_mcp_config_stale",
            "kind": "config",
            "message": message,
            "action": "重新发送一条远程消息以恢复工作区 MCP 配置",
        }]
    elif not state:
        state_name = "conflict"
        message = "工作区已有用户管理的 tcb-remote 配置"
        diagnostics = [{
            "code": "remote_mcp_config_conflict",
            "kind": "config",
            "message": message,
            "action": "保留用户配置或更换本地控制目录",
        }]
    elif current_entry != state.get("managed_entry"):
        state_name = "conflict"
        message = "用户已修改 tcb-remote 配置，已保留当前内容"
        diagnostics = [{
            "code": "remote_mcp_config_conflict",
            "kind": "config",
            "message": message,
            "action": "恢复项目生成的配置或更换本地控制目录",
        }]
    elif current_entry != expected_entry:
        state_name = "stale"
        message = "工作区 tcb-remote MCP 配置需要更新"
        diagnostics = [{
            "code": "remote_mcp_config_stale",
            "kind": "config",
            "message": message,
            "action": "重新发送一条远程消息以更新工作区 MCP 配置",
        }]
    else:
        state_name = "installed"
        message = "Antigravity 工作区 tcb-remote MCP 已配置"
        diagnostics = []

    if state_name in {"installed", "stale"}:
        private_error = ""
        try:
            private_config = json.loads(private_config_path.read_text(encoding="utf-8"))
            if not isinstance(private_config, dict):
                private_error = "远程 bridge 私有配置格式无效"
            elif not str(private_config.get("token") or "").strip():
                private_error = "远程 bridge 认证配置缺失"
            else:
                validate_bridge_url(str(private_config.get("bridge_url") or ""))
        except FileNotFoundError:
            private_error = "远程 bridge 私有配置缺失"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            private_error = "远程 bridge 私有配置不可用"
        if private_error:
            state_name = "broken"
            message = private_error
            diagnostics = [{
                "code": "remote_bridge_unavailable" if "bridge" in private_error else "remote_auth_invalid",
                "kind": "auth" if "认证" in private_error else "bridge",
                "message": message,
                "action": "确认 Web 服务仍在运行并重新发送远程消息",
            }]

    result = _remote_mcp_status_payload(
        state=state_name,
        message=message,
        config_path=config_path,
        allowed_tools=tools,
        diagnostics=diagnostics,
    )
    result["mcp_setup_snippet"] = json.dumps(
        {"mcpServers": {REMOTE_MCP_SERVER_NAME: expected_entry}},
        ensure_ascii=False,
        indent=2,
    )
    return result


def _remove_workspace_mcp_entry(working_dir: Path | str, *, owner_key: str = "") -> None:
    config_path = _workspace_mcp_config_path(working_dir)
    state_path = _workspace_mcp_state_path(working_dir)
    try:
        with _workspace_mcp_lock(config_path):
            state, state_broken = _load_workspace_mcp_state(state_path)
            if state_broken or not state or state.get("owner_key") != owner_key:
                return
            config = _load_workspace_mcp_json(config_path)
            servers = config.get("mcpServers")
            if not isinstance(servers, dict) or servers.get(REMOTE_MCP_SERVER_NAME) != state.get("managed_entry"):
                return
            servers.pop(REMOTE_MCP_SERVER_NAME, None)
            _write_json_atomic(config_path, config)
            state_path.unlink(missing_ok=True)
    except (OSError, RemoteChatPreparationError):
        # Revocation must fail closed and never remove a user-owned entry.
        return


def revoke_remote_chat(profile: Any) -> None:
    with _lock:
        token = _profile_tokens.pop(_profile_key(profile), "")
        _bindings.pop(token, None)
    _remove_workspace_mcp_entry(getattr(profile, "working_dir", ""), owner_key=_profile_key(profile))


def resolve_remote_chat_token(token: str) -> Any | None:
    """Return a detached scoped profile, or None for an unknown/revoked capability.

    The route must also look up the current profile and reject removed/archived or
    changed targets. Call revoke_remote_chat when removing a profile.
    """
    with _lock:
        binding = _bindings.get(str(token or ""))
        if binding is None:
            return None
        profile, fingerprint = binding
        if remote_workspace_fingerprint(profile) != fingerprint or getattr(profile, "archived", False):
            return None
        result = copy.copy(profile)
        result.remote_workspace = copy.deepcopy(profile.remote_workspace)
        return result


def _integer(default: int, maximum: int, minimum: int = 1) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum, "default": default}


def remote_tools() -> list[dict[str, Any]]:
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    definitions = [
        ("exec", "Run remote shell commands in one ordered batch; use rg and focused tests. Output is bounded.", ["commands"], {
            "commands": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "minLength": 1, "maxLength": 16000}},
            "cwd": {**path, "default": "."}, "timeout_seconds": _integer(60, 300),
            "max_output_chars": _integer(12000, 64000),
        }),
        ("read", "Read a bounded UTF-8 remote file range. offset is a 1-based line number.", ["path"], {
            "path": path, "offset": _integer(1, 10_000_000), "limit": _integer(200, 2000),
            "max_chars": _integer(12000, 64000),
        }),
        ("write", "Write UTF-8 content to a remote file.", ["path", "content"], {
            "path": path, "content": {"type": "string", "maxLength": 1_000_000},
        }),
        ("edit", "Replace exactly one occurrence of old_text in a remote file; fail if absent or ambiguous.", ["path", "old_text", "new_text"], {
            "path": path, "old_text": {"type": "string", "minLength": 1, "maxLength": 1_000_000},
            "new_text": {"type": "string", "maxLength": 1_000_000},
        }),
        ("list", "List one remote directory with bounded entries.", [], {
            "path": {**path, "default": "."}, "max_entries": _integer(200, 1000),
        }),
    ]
    return [{"name": name, "description": description, "inputSchema": {
        "type": "object", "required": required, "properties": properties, "additionalProperties": False,
    }} for name, description, required, properties in definitions]


def validate_tool_arguments(tool: str, arguments: Any) -> dict[str, Any]:
    """Validate and fill defaults; the server must apply this before SSH dispatch."""
    definition = next((item for item in remote_tools() if item["name"] == tool), None)
    if definition is None:
        raise ValueError("Unknown remote tool")
    schema = definition["inputSchema"]
    if not isinstance(arguments, dict) or set(arguments) - schema["properties"].keys():
        raise ValueError("Invalid remote tool arguments")
    if any(key not in arguments for key in schema["required"]):
        raise ValueError("Missing required remote tool argument")

    def validate(value: Any, rule: dict[str, Any]) -> None:
        kind = rule["type"]
        if kind == "string":
            valid = isinstance(value, str) and rule.get("minLength", 0) <= len(value) <= rule["maxLength"]
        elif kind == "integer":
            valid = type(value) is int and rule["minimum"] <= value <= rule["maximum"]
        else:
            valid = isinstance(value, list) and rule["minItems"] <= len(value) <= rule["maxItems"]
            if valid:
                for item in value:
                    validate(item, rule["items"])
        if not valid:
            raise ValueError("Remote tool argument exceeds its schema bounds")

    result = dict(arguments)
    for key, rule in schema["properties"].items():
        if key not in result and "default" in rule:
            result[key] = rule["default"]
        if key in result:
            validate(result[key], rule)
    return result


def remote_chat_prompt(profile: Any) -> str:
    remote = profile.remote_workspace
    host = json.dumps(str(remote["host"]), ensure_ascii=False)
    root = json.dumps(str(remote["root"]), ensure_ascii=False)
    shell = (
        "Remote OS: Windows; commands run in Windows PowerShell (powershell.exe), including the Pi bash alias. "
        "Use PowerShell syntax compatible with 5.1, not Bash or PowerShell 7 operators. "
        "File tool paths may be relative or drive-qualified (C:/... or /C:/...); shell paths use C:/... . "
        "Windows file APIs reject UNC/device paths and junctions/symlinks. "
        "Use UTF-8 for text files; Git, rg and project build tools must be available on the remote PATH.\n"
        if remote.get("platform") == "windows" else "Remote OS: POSIX; commands run in /bin/sh.\n"
    )
    return (
        f"Remote SSH workspace: host={host}, root={root}.\n{shell}"
        "This local working directory is only an agent control directory; it contains no project source or tests. "
        "Uploaded chat attachments are stored locally under attachments/ in this control directory. "
        "An 'Attachment path:' in the user message is a local absolute path: read or process it with local tools "
        "(Pi: local_read/local_bash). Keep attachment processing outputs alongside the input attachment. "
        "Perform ALL project reads, edits, searches, commands and tests on the remote workspace using "
        "tcb-remote MCP exec/read/write/edit/list (Pi: remote_exec/remote_read/remote_write/remote_edit/remote_list; "
        "read/write/edit/bash/ls are also routed remotely). Paths are remote, relative to the remote root. "
        "Before changes, read the remote repository's AGENTS.md, CLAUDE.md and applicable nested instructions. "
        "Batch related commands with exec.commands; use bounded read ranges and rg to limit output. "
        "Use edit with exact old_text/new_text; ambiguous matches fail. If the bridge fails, report the error; "
        "do not fall back to local files, local tests or a separate SSH client. "
        "The CLI's built-in tools still run locally: this routing guidance is not a filesystem sandbox.\n"
    )


def ensure_remote_chat_instructions(profile: Any) -> str:
    prompt = remote_chat_prompt(profile)
    directory = Path(profile.working_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = directory / name
        content = "# Remote workspace\n\n" + prompt
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    return prompt


def _private_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def validate_bridge_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Remote agent bridge must use the existing loopback web server")
    return base_url.rstrip("/")


@dataclass(frozen=True)
class RemoteChatConfig:
    config_path: Path
    prompt: str
    fingerprint: str
    workspace_mcp_config_path: Path
    workspace_mcp_state_path: Path
    workspace_mcp_status: str = "installed"
    workspace_mcp_tools: tuple[str, ...] = ()

    @property
    def env(self) -> dict[str, str]:
        return {REMOTE_CONFIG_ENV: str(self.config_path)}

    @property
    def workspace_mcp_path(self) -> Path:
        return self.workspace_mcp_config_path

    @property
    def server_name(self) -> str:
        return REMOTE_MCP_SERVER_NAME

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return self.workspace_mcp_tools

    def cli_args(self, cli_type: str) -> list[str]:
        args = [str(Path(__file__).with_name("mcp_stdio.py")), "--config", str(self.config_path)]
        server = {"command": sys.executable, "args": args}
        if cli_type in {"codex", "codex_server"}:
            return ["-c", f"mcp_servers.{SERVER_NAME}.command={json.dumps(sys.executable)}",
                    "-c", f"mcp_servers.{SERVER_NAME}.args={json.dumps(args)}"]
        if cli_type == "claude":
            return ["--mcp-config", json.dumps({"mcpServers": {SERVER_NAME: server}})]
        if cli_type == "pi":
            return ["--no-builtin-tools", "--extension", str(Path(__file__).with_name("pi_extension.ts"))]
        if cli_type == "antigravity":
            # Antigravity discovers workspace-scoped MCP servers from cwd.
            return []
        raise ValueError("Remote chat supports codex, codex_server, claude or pi")


def prepare_remote_chat(profile: Any, base_url: str = "") -> RemoteChatConfig:
    """Register/refresh a profile capability and prepare CLI/Pi bridge configuration.

    Pass the web server's actual loopback base URL from the host. Pi may omit it
    after host preparation; the cluster bridge config is a discovery fallback.
    """
    fingerprint = remote_workspace_fingerprint(profile)
    if not fingerprint:
        raise ValueError("A remote workspace profile is required")
    prompt = ensure_remote_chat_instructions(profile)
    key = _profile_key(profile)
    directory_key = hashlib.sha256(f"{key}:{fingerprint}".encode()).hexdigest()
    config_path = get_app_data_root() / "remote-chat" / directory_key / "config.json"
    working_dir = Path(profile.working_dir).expanduser().resolve()
    workspace_config_path = _workspace_mcp_config_path(working_dir)
    workspace_state_path = _workspace_mcp_state_path(working_dir)
    install_workspace_mcp = str(getattr(profile, "cli_type", "")).strip().lower() == "antigravity"

    def resolve_base_url() -> str:
        nonlocal base_url
        if not base_url:
            discovery_path = config_path if config_path.exists() else None
            if discovery_path is None:
                from bot.cluster.setup import get_cluster_mcp_config_path
                discovery_path = get_cluster_mcp_config_path()
            try:
                private_config = json.loads(discovery_path.read_text(encoding="utf-8"))
                base_url = str(private_config["bridge_url"])
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                raise RemoteChatPreparationError(
                    "remote_bridge_unavailable",
                    "找不到可用的本地远程工作区 bridge 配置",
                    status=502,
                    data={"config_path": str(config_path)},
                ) from exc
        try:
            return validate_bridge_url(base_url)
        except ValueError as exc:
            raise RemoteChatPreparationError(
                "remote_bridge_invalid",
                str(exc),
                status=502,
                data={"config_path": str(config_path)},
            ) from exc

    base_url = resolve_base_url()

    def write_private_config() -> None:
        with _lock:
            token = _profile_tokens.get(key, "")
            binding = _bindings.get(token)
            if binding is None or binding[1] != fingerprint:
                if token:
                    _bindings.pop(token, None)
                token = secrets.token_urlsafe(32)
                _profile_tokens[key] = token
            _bindings[token] = (profile, fingerprint)
            _private_write(config_path, json.dumps({
                "bridge_url": base_url, "token": token, "tools": remote_tools(),
            }, ensure_ascii=False))

    if not install_workspace_mcp:
        write_private_config()
        return RemoteChatConfig(
            config_path=config_path,
            prompt=prompt,
            fingerprint=fingerprint,
            workspace_mcp_config_path=workspace_config_path,
            workspace_mcp_state_path=workspace_state_path,
            workspace_mcp_status="missing",
            workspace_mcp_tools=_remote_mcp_tools(),
        )

    with _workspace_mcp_lock(workspace_config_path):
        config = _load_workspace_mcp_json(workspace_config_path)
        state, state_broken = _load_workspace_mcp_state(workspace_state_path)
        if state_broken or (state and (
            state.get("server_name") != REMOTE_MCP_SERVER_NAME
            or state.get("managed_by") != REMOTE_MCP_MANAGED_MARKER
            or not isinstance(state.get("managed_entry"), dict)
        )):
            raise RemoteChatPreparationError(
                "remote_mcp_config_broken",
                f"Antigravity MCP ownership state is invalid: {workspace_state_path}",
                data={"config_path": str(workspace_config_path), "state_path": str(workspace_state_path)},
            )
        if state and state.get("owner_key") != key:
            raise RemoteChatPreparationError(
                "remote_mcp_config_conflict",
                "工作区已有其他智能体管理的 tcb-remote 配置，未覆盖",
                data={
                    "config_path": str(workspace_config_path),
                    "state_path": str(workspace_state_path),
                    "server_name": REMOTE_MCP_SERVER_NAME,
                    "allowed_tools": list(_remote_mcp_tools()),
                },
            )

        servers = config.get("mcpServers")
        if servers is None:
            servers = {}
            config["mcpServers"] = servers
        current_entry = servers.get(REMOTE_MCP_SERVER_NAME)
        if current_entry is not None and not _managed_workspace_entry(current_entry, state):
            raise RemoteChatPreparationError(
                "remote_mcp_config_conflict",
                "工作区已有用户管理的 tcb-remote 配置，未覆盖",
                data={
                    "config_path": str(workspace_config_path),
                    "state_path": str(workspace_state_path),
                    "server_name": REMOTE_MCP_SERVER_NAME,
                    "allowed_tools": list(_remote_mcp_tools()),
                },
            )

        write_private_config()

        desired_entry = _workspace_mcp_entry(config_path, working_dir)
        changed = current_entry != desired_entry
        if changed:
            servers[REMOTE_MCP_SERVER_NAME] = desired_entry
            _write_json_atomic(workspace_config_path, config)
        next_state = {
            "version": 1,
            "server_name": REMOTE_MCP_SERVER_NAME,
            "managed_by": REMOTE_MCP_MANAGED_MARKER,
            "owner_key": key,
            "managed_entry": desired_entry,
            "previous_entry": state.get("previous_entry") if state else None,
            "config_path": str(workspace_config_path),
        }
        if state != next_state:
            _write_json_atomic(workspace_state_path, next_state)
            changed = True

    return RemoteChatConfig(
        config_path=config_path,
        prompt=prompt,
        fingerprint=fingerprint,
        workspace_mcp_config_path=workspace_config_path,
        workspace_mcp_state_path=workspace_state_path,
        workspace_mcp_status="installed",
        workspace_mcp_tools=_remote_mcp_tools(),
    )
