from __future__ import annotations

import json
import errno
import os
import secrets
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from bot.runtime_paths import get_tcb_home_root

CLUSTER_MCP_SERVER_NAME = "tcb-cluster"
DEEPSEEK_MCP_PATCH_FILENAME = "dsh-cluster-mcp.patch.json"
CLUSTER_MCP_TOOL_NAMES = (
    "configure_team",
    "cluster_status",
    "list_agents",
    "new_agent_session",
    "ask_agent",
    "poll_agent_tasks",
    "wait_agent_messages",
)
ANTIGRAVITY_MCP_STATE_FILENAME = ".tcb-cluster-mcp-state.json"
ANTIGRAVITY_MCP_LOCK_FILENAME = "mcp_config.json.lock"
ANTIGRAVITY_MCP_MARKER = "orbit-safe-claw"
_ANTIGRAVITY_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_ANTIGRAVITY_LOCAL_LOCKS_GUARD = threading.Lock()


def build_pi_mcp_settings_snippet(launcher_path: Path) -> dict[str, Any]:
    return {
        "mcp": {
            CLUSTER_MCP_SERVER_NAME: {
                "type": "local",
                "command": [str(launcher_path)],
                "enabled": True,
            }
        }
    }


def get_antigravity_mcp_config_path(working_dir: Path | str) -> Path:
    return Path(working_dir).expanduser() / ".agents" / "mcp_config.json"


def get_antigravity_mcp_state_path(working_dir: Path | str) -> Path:
    return get_antigravity_mcp_config_path(working_dir).with_name(ANTIGRAVITY_MCP_STATE_FILENAME)


def build_antigravity_mcp_server_entry(
    launcher_path: Path,
    working_dir: Path | str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "command": str(launcher_path),
        "args": [],
        "env": {"TCB_CLUSTER_MCP_MANAGED": ANTIGRAVITY_MCP_MARKER},
    }
    if working_dir is not None:
        entry["cwd"] = str(Path(working_dir).expanduser())
    return entry


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

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise


def _release_workspace_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _antigravity_mcp_lock(config_path: Path, *, timeout_seconds: float = 10.0):
    lock_path = config_path.with_name(ANTIGRAVITY_MCP_LOCK_FILENAME)
    key = str(lock_path.absolute()).lower()
    with _ANTIGRAVITY_LOCAL_LOCKS_GUARD:
        local_lock = _ANTIGRAVITY_LOCAL_LOCKS.setdefault(key, threading.RLock())
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
                        raise TimeoutError(f"无法取得 Antigravity MCP 配置锁: {lock_path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                _release_workspace_lock(handle)


def _write_json_atomic(path: Path, payload: Any) -> None:
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
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _load_antigravity_mcp_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Antigravity MCP 配置无效: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Antigravity MCP 配置必须是 JSON 对象: {path}")
    servers = value.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise ValueError("Antigravity MCP 配置的 mcpServers 必须是对象")
    return value


def _load_antigravity_mcp_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _is_managed_antigravity_entry(value: Any, state: dict[str, Any] | None) -> bool:
    if not isinstance(value, dict):
        return False
    if state and value == state.get("managed_entry"):
        return True
    env = value.get("env")
    return isinstance(env, dict) and env.get("TCB_CLUSTER_MCP_MANAGED") == ANTIGRAVITY_MCP_MARKER


def ensure_antigravity_mcp_config(
    working_dir: Path | str,
    launcher_path: Path,
) -> dict[str, Any]:
    """Install the project-owned tcb-cluster entry into a workspace config.

    Existing servers are preserved.  A user-owned entry with the same server
    name is reported as a conflict and is never overwritten.
    """
    config_path = get_antigravity_mcp_config_path(working_dir)
    state_path = get_antigravity_mcp_state_path(working_dir)
    desired_entry = build_antigravity_mcp_server_entry(launcher_path, working_dir)
    with _antigravity_mcp_lock(config_path):
        config = _load_antigravity_mcp_json(config_path)
        servers = config.setdefault("mcpServers", {})
        state = _load_antigravity_mcp_state(state_path)
        current_entry = servers.get(CLUSTER_MCP_SERVER_NAME)
        if current_entry is not None and not _is_managed_antigravity_entry(current_entry, state):
            return {
                "config_path": str(config_path),
                "state_path": str(state_path),
                "server_name": CLUSTER_MCP_SERVER_NAME,
                "entry": current_entry,
                "managed": False,
                "installed": False,
                "changed": False,
                "conflict": True,
                "allowed_tools": list(CLUSTER_MCP_TOOL_NAMES),
                "message": "工作区已有用户管理的 tcb-cluster 配置，未覆盖",
            }

        previous_entry = state.get("previous_entry") if isinstance(state, dict) else None
        changed = current_entry != desired_entry
        if changed:
            servers[CLUSTER_MCP_SERVER_NAME] = desired_entry
            _write_json_atomic(config_path, config)
        next_state = {
            "version": 1,
            "server_name": CLUSTER_MCP_SERVER_NAME,
            "managed_entry": desired_entry,
            "previous_entry": previous_entry,
            "config_path": str(config_path),
        }
        if state != next_state:
            _write_json_atomic(state_path, next_state)
            changed = True
        return {
            "config_path": str(config_path),
            "state_path": str(state_path),
            "server_name": CLUSTER_MCP_SERVER_NAME,
            "entry": desired_entry,
            "managed": True,
            "installed": True,
            "changed": changed,
            "conflict": False,
            "allowed_tools": list(CLUSTER_MCP_TOOL_NAMES),
            "message": "Antigravity 工作区 MCP 已配置",
        }


def remove_antigravity_mcp_config(working_dir: Path | str) -> dict[str, Any]:
    config_path = get_antigravity_mcp_config_path(working_dir)
    state_path = get_antigravity_mcp_state_path(working_dir)
    with _antigravity_mcp_lock(config_path):
        state = _load_antigravity_mcp_state(state_path)
        if not state:
            return {
                "config_path": str(config_path),
                "state_path": str(state_path),
                "server_name": CLUSTER_MCP_SERVER_NAME,
                "changed": False,
                "managed": False,
                "conflict": False,
                "message": "没有本项目生成的 Antigravity MCP 配置",
            }
        config = _load_antigravity_mcp_json(config_path)
        servers = config.setdefault("mcpServers", {})
        current_entry = servers.get(CLUSTER_MCP_SERVER_NAME)
        if current_entry != state.get("managed_entry"):
            return {
                "config_path": str(config_path),
                "state_path": str(state_path),
                "server_name": CLUSTER_MCP_SERVER_NAME,
                "changed": False,
                "managed": False,
                "conflict": True,
                "message": "用户已修改 tcb-cluster 配置，保留当前内容",
            }
        previous_entry = state.get("previous_entry")
        if previous_entry is None:
            servers.pop(CLUSTER_MCP_SERVER_NAME, None)
        else:
            servers[CLUSTER_MCP_SERVER_NAME] = previous_entry
        _write_json_atomic(config_path, config)
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass
        return {
            "config_path": str(config_path),
            "state_path": str(state_path),
            "server_name": CLUSTER_MCP_SERVER_NAME,
            "changed": True,
            "managed": True,
            "conflict": False,
            "message": "已恢复用户原有 Antigravity MCP 配置",
        }


def inspect_antigravity_mcp_config(
    working_dir: Path | str,
    launcher_path: Path,
) -> dict[str, Any]:
    config_path = get_antigravity_mcp_config_path(working_dir)
    state_path = get_antigravity_mcp_state_path(working_dir)
    try:
        config = _load_antigravity_mcp_json(config_path)
    except ValueError as exc:
        return {
            "config_path": str(config_path),
            "state_path": str(state_path),
            "state": "broken",
            "message": str(exc),
            "allowed_tools": list(CLUSTER_MCP_TOOL_NAMES),
        }
    servers = config.get("mcpServers") if isinstance(config.get("mcpServers"), dict) else {}
    current_entry = servers.get(CLUSTER_MCP_SERVER_NAME)
    if current_entry is None:
        state = "mcp_missing"
        message = "工作区尚未配置 tcb-cluster"
    elif not _is_managed_antigravity_entry(current_entry, _load_antigravity_mcp_state(state_path)):
        state = "conflict"
        message = "工作区已有用户管理的 tcb-cluster 配置"
    elif current_entry != build_antigravity_mcp_server_entry(launcher_path, working_dir):
        state = "stale"
        message = "工作区 tcb-cluster 配置需要更新"
    else:
        state = "installed"
        message = "Antigravity 工作区 MCP 已配置"
    return {
        "config_path": str(config_path),
        "state_path": str(state_path),
        "state": state,
        "message": message,
        "entry": current_entry,
        "allowed_tools": list(CLUSTER_MCP_TOOL_NAMES),
    }


def get_cluster_mcp_config_path(*, home_dir: Path | None = None) -> Path:
    root = get_tcb_home_root() if home_dir is None or home_dir == Path.home() else home_dir / ".tcb"
    return root / "cluster-mcp" / "config.json"


def get_deepseek_mcp_patch_path(*, home_dir: Path | None = None) -> Path:
    return get_cluster_mcp_config_path(home_dir=home_dir).with_name(DEEPSEEK_MCP_PATCH_FILENAME)


def write_deepseek_mcp_patch(
    *,
    working_dir: Path | str | None = None,
    home_dir: Path | None = None,
    repo_root: Path | None = None,
    python_executable: Path | None = None,
) -> Path:
    config_path = get_cluster_mcp_config_path(home_dir=home_dir)
    patch_path = get_deepseek_mcp_patch_path(home_dir=home_dir)
    root = repo_root or Path(__file__).resolve().parents[2]
    executable = python_executable or Path(sys.executable)
    mcp_config: dict[str, Any] = {
        "serverName": CLUSTER_MCP_SERVER_NAME,
        "transport": "stdio",
        "command": str(executable),
        "args": [str(root / "bot" / "cluster" / "mcp_stdio.py"), "--config", str(config_path)],
        "failOnStartupError": True,
    }
    if working_dir is not None:
        mcp_config["cwd"] = str(Path(working_dir).expanduser().resolve())
    _write_json_atomic(
        patch_path,
        [{"id": "orbit-tcb-cluster-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": mcp_config}],
    )
    return patch_path


def get_pi_cluster_extension_source_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / "bot" / "cluster" / "pi_extension" / "tcb-cluster.ts"


def get_pi_cluster_extension_path(*, home_dir: Path | None = None) -> Path:
    if home_dir is None:
        settings_override = str(os.environ.get("PI_AGENT_SETTINGS") or "").strip()
        if settings_override:
            return Path(settings_override).expanduser().parent / "extensions" / "tcb-cluster.ts"
    root = home_dir or Path.home()
    return root / ".pi" / "agent" / "extensions" / "tcb-cluster.ts"


def write_pi_cluster_extension(*, home_dir: Path | None = None, repo_root: Path | None = None) -> Path:
    source = get_pi_cluster_extension_source_path(repo_root)
    destination = get_pi_cluster_extension_path(home_dir=home_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def build_pi_mcp_self_test_command(config_path: Path, *, python_executable: Path | None = None) -> list[str]:
    python_executable = python_executable or Path(sys.executable)
    script_path = Path(__file__).resolve().with_name("mcp_stdio.py")
    return [str(python_executable), str(script_path), "--config", str(config_path), "--self-test"]


@dataclass(frozen=True)
class ClusterMcpLauncher:
    server_name: str
    launcher_path: Path
    config_path: Path
    token_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "server_name": self.server_name,
            "launcher_path": str(self.launcher_path),
            "config_path": str(self.config_path),
            "token_path": str(self.token_path),
        }


def _is_windows_launcher(path: Path) -> bool:
    return path.suffix.lower() == ".cmd"


def _write_launcher(path: Path, *, python_executable: Path, repo_root: Path, config_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    script_path = repo_root / "bot" / "cluster" / "mcp_stdio.py"
    if _is_windows_launcher(path):
        content = "\n".join([
            "@echo off",
            "set PYTHONUTF8=1",
            "set PYTHONIOENCODING=utf-8",
            f'"{python_executable}" "{script_path}" --config "{config_path}" %*',
            "",
        ])
    else:
        content = "\n".join([
            "#!/usr/bin/env sh",
            "export PYTHONUTF8=1",
            "export PYTHONIOENCODING=utf-8",
            f'exec "{python_executable}" "{script_path}" --config "{config_path}" "$@"',
            "",
        ])
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o755)
    except OSError:
        pass


def prepare_cluster_mcp_launcher(
    *,
    home_dir: Path,
    repo_root: Path,
    bridge_url: str,
    python_executable: Path | None = None,
) -> ClusterMcpLauncher:
    python_executable = python_executable or Path(sys.executable)
    config_path = get_cluster_mcp_config_path(home_dir=home_dir)
    mcp_dir = config_path.parent
    bin_dir = mcp_dir.parent / "bin"
    launcher_path = bin_dir / ("tcb-cluster-mcp.cmd" if sys.platform.startswith("win") else "tcb-cluster-mcp.sh")
    token_path = mcp_dir / "token"

    mcp_dir.mkdir(parents=True, exist_ok=True)
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")

    config = {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "bridge_url": bridge_url.rstrip("/"),
        "token_file": str(token_path),
        "server_name": CLUSTER_MCP_SERVER_NAME,
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_launcher(launcher_path, python_executable=python_executable, repo_root=repo_root, config_path=config_path)
    return ClusterMcpLauncher(CLUSTER_MCP_SERVER_NAME, launcher_path, config_path, token_path)


def normalize_cli_kind(cli_type: str) -> Literal["codex", "codex_server", "claude", "antigravity", "deepseek", "pi"]:
    kind = str(cli_type or "").strip().lower()
    if kind not in {"codex", "codex_server", "claude", "antigravity", "deepseek", "pi"}:
        raise ValueError("cluster MCP 仅支持 codex / codex server / claude / antigravity / deepseek / pi")
    return kind  # type: ignore[return-value]


def build_cli_install_command(*, cli_type: str, cli_path: str, launcher_path: Path) -> list[str]:
    kind = normalize_cli_kind(cli_type)
    executable = str(cli_path or ("codex" if kind == "codex_server" else kind))
    if kind in {"antigravity", "deepseek", "pi"}:
        return []
    if kind in {"codex", "codex_server"}:
        return [executable, "mcp", "add", CLUSTER_MCP_SERVER_NAME, "--", str(launcher_path)]
    return [executable, "mcp", "add", "--scope", "user", CLUSTER_MCP_SERVER_NAME, "--", str(launcher_path)]


def build_cli_verify_command(cli_type: str, cli_path: str) -> list[str]:
    kind = normalize_cli_kind(cli_type)
    if kind == "deepseek":
        return []
    if kind == "pi":
        return [str(cli_path or kind), "-p", "--tools", f"{CLUSTER_MCP_SERVER_NAME}.cluster_status", "List MCP tools"]
    if kind == "antigravity":
        return [str(cli_path or kind), "mcp", "list"]
    return [str(cli_path or ("codex" if kind == "codex_server" else kind)), "mcp", "get", CLUSTER_MCP_SERVER_NAME]


def build_cli_remove_command(cli_type: str, cli_path: str) -> list[str]:
    kind = normalize_cli_kind(cli_type)
    if kind in {"antigravity", "deepseek", "pi"}:
        return []
    return [str(cli_path or ("codex" if kind == "codex_server" else kind)), "mcp", "remove", CLUSTER_MCP_SERVER_NAME]
