import json
import subprocess
import sys
from pathlib import Path

from bot.cluster_mcp_client import load_mcp_bridge_config
from bot.cluster_setup import (
    CLUSTER_MCP_SERVER_NAME,
    build_cli_install_command,
    build_cli_remove_command,
    prepare_cluster_mcp_launcher,
)


def test_prepare_cluster_mcp_launcher_writes_files(tmp_path: Path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    python_exe = tmp_path / "python.exe"
    python_exe.write_text("", encoding="utf-8")

    result = prepare_cluster_mcp_launcher(
        home_dir=home,
        repo_root=repo,
        python_executable=python_exe,
        bridge_url="http://127.0.0.1:8765",
    )

    assert result.server_name == CLUSTER_MCP_SERVER_NAME
    assert result.config_path.exists()
    assert result.token_path.exists()
    assert result.launcher_path.exists()
    assert "cluster_mcp_stdio.py" in result.launcher_path.read_text(encoding="utf-8")


def test_build_codex_install_command_windows_path():
    command = build_cli_install_command(
        cli_type="codex",
        cli_path="codex",
        launcher_path=Path(r"C:\Users\demo\.tcb\bin\tcb-cluster-mcp.cmd"),
    )
    assert command == [
        "codex",
        "mcp",
        "add",
        "tcb-cluster",
        "--",
        r"C:\Users\demo\.tcb\bin\tcb-cluster-mcp.cmd",
    ]


def test_build_claude_install_command_user_scope():
    command = build_cli_install_command(
        cli_type="claude",
        cli_path="claude",
        launcher_path=Path(r"C:\Users\demo\.tcb\bin\tcb-cluster-mcp.cmd"),
    )
    assert command == [
        "claude",
        "mcp",
        "add",
        "--scope",
        "user",
        "tcb-cluster",
        "--",
        r"C:\Users\demo\.tcb\bin\tcb-cluster-mcp.cmd",
    ]


def test_build_remove_commands():
    assert build_cli_remove_command("codex", "codex") == ["codex", "mcp", "remove", "tcb-cluster"]
    assert build_cli_remove_command("claude", "claude") == ["claude", "mcp", "remove", "tcb-cluster"]


def test_load_mcp_bridge_config_reads_token(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("secret-token", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"bridge_url": "http://127.0.0.1:8765", "token_file": str(token)}),
        encoding="utf-8",
    )

    loaded = load_mcp_bridge_config(config)

    assert loaded.bridge_url == "http://127.0.0.1:8765"
    assert loaded.token == "secret-token"


def test_cluster_mcp_stdio_script_self_test_runs_as_file(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("secret-token", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"bridge_url": "http://127.0.0.1:8765", "token_file": str(token)}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "bot" / "cluster_mcp_stdio.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--config", str(config), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True
