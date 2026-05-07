from __future__ import annotations

import json
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

CLUSTER_MCP_SERVER_NAME = "tcb-cluster"


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
    bin_dir = home_dir / ".tcb" / "bin"
    mcp_dir = home_dir / ".tcb" / "cluster-mcp"
    launcher_path = bin_dir / ("tcb-cluster-mcp.cmd" if sys.platform.startswith("win") else "tcb-cluster-mcp.sh")
    config_path = mcp_dir / "config.json"
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


def normalize_cli_kind(cli_type: str) -> Literal["codex", "claude"]:
    kind = str(cli_type or "").strip().lower()
    if kind not in {"codex", "claude"}:
        raise ValueError("cluster MCP 仅支持 codex / claude")
    return kind  # type: ignore[return-value]


def build_cli_install_command(*, cli_type: str, cli_path: str, launcher_path: Path) -> list[str]:
    kind = normalize_cli_kind(cli_type)
    executable = str(cli_path or kind)
    if kind == "codex":
        return [executable, "mcp", "add", CLUSTER_MCP_SERVER_NAME, "--", str(launcher_path)]
    return [executable, "mcp", "add", "--scope", "user", CLUSTER_MCP_SERVER_NAME, "--", str(launcher_path)]


def build_cli_verify_command(cli_type: str, cli_path: str) -> list[str]:
    kind = normalize_cli_kind(cli_type)
    return [str(cli_path or kind), "mcp", "get", CLUSTER_MCP_SERVER_NAME]


def build_cli_remove_command(cli_type: str, cli_path: str) -> list[str]:
    kind = normalize_cli_kind(cli_type)
    return [str(cli_path or kind), "mcp", "remove", CLUSTER_MCP_SERVER_NAME]
