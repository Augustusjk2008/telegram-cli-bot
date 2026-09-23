"""Profile-scoped capabilities for agents using the host's existing SSH bridge."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bot.runtime_paths import get_app_data_root

SERVER_NAME = "tcb-remote"
REMOTE_CONFIG_ENV = "TCB_REMOTE_MCP_CONFIG"
MAX_RESPONSE_BYTES = 512_000
_lock = threading.RLock()
_bindings: dict[str, tuple[Any, str]] = {}
_profile_tokens: dict[str, str] = {}


def remote_workspace_fingerprint(profile: Any) -> str:
    remote = getattr(profile, "remote_workspace", None)
    if not remote:
        return ""
    return hashlib.sha256(json.dumps(remote, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _profile_key(profile: Any) -> str:
    return str(profile.alias)


def revoke_remote_chat(profile: Any) -> None:
    with _lock:
        token = _profile_tokens.pop(_profile_key(profile), "")
        _bindings.pop(token, None)


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
    return (
        f"Remote SSH workspace: host={host}, root={root}.\n"
        "This local working directory is only an agent control directory; it contains no project source or tests. "
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

    @property
    def env(self) -> dict[str, str]:
        return {REMOTE_CONFIG_ENV: str(self.config_path)}

    def cli_args(self, cli_type: str) -> list[str]:
        args = [str(Path(__file__).with_name("mcp_stdio.py")), "--config", str(self.config_path)]
        server = {"command": sys.executable, "args": args}
        if cli_type == "codex":
            return ["-c", f"mcp_servers.{SERVER_NAME}.command={json.dumps(sys.executable)}",
                    "-c", f"mcp_servers.{SERVER_NAME}.args={json.dumps(args)}"]
        if cli_type == "claude":
            return ["--mcp-config", json.dumps({"mcpServers": {SERVER_NAME: server}})]
        if cli_type == "pi":
            return ["--no-builtin-tools", "--extension", str(Path(__file__).with_name("pi_extension.ts"))]
        raise ValueError("Remote chat supports codex, claude or pi")


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
    with _lock:
        if not base_url:
            from bot.cluster.setup import get_cluster_mcp_config_path
            discovery_path = config_path if config_path.exists() else get_cluster_mcp_config_path()
            base_url = str(json.loads(discovery_path.read_text(encoding="utf-8"))["bridge_url"])
        base_url = validate_bridge_url(base_url)
        token = _profile_tokens.get(key, "")
        binding = _bindings.get(token)
        if binding is None or binding[1] != fingerprint:
            revoke_remote_chat(profile)
            token = secrets.token_urlsafe(32)
            _profile_tokens[key] = token
        _bindings[token] = (profile, fingerprint)
        _private_write(config_path, json.dumps({
            "bridge_url": base_url, "token": token, "tools": remote_tools(),
        }, ensure_ascii=False))
    return RemoteChatConfig(config_path=config_path, prompt=prompt, fingerprint=fingerprint)
