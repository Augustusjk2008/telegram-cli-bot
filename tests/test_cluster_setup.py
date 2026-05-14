import json
import subprocess
import sys
from pathlib import Path

from bot.cluster.mcp_client import load_mcp_bridge_config
from bot.cluster import mcp_stdio as cluster_mcp_stdio
from bot.cluster.setup import (
    CLUSTER_MCP_SERVER_NAME,
    build_cli_install_command,
    build_cli_remove_command,
    build_cli_verify_command,
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
    launcher_text = result.launcher_path.read_text(encoding="utf-8")
    assert "bot" in launcher_text
    assert "cluster" in launcher_text
    assert "mcp_stdio.py" in launcher_text
    assert "PYTHONUTF8=1" in launcher_text
    assert "PYTHONIOENCODING=utf-8" in launcher_text


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


def test_cluster_setup_builds_kimi_mcp_commands(tmp_path: Path):
    launcher = tmp_path / "tcb-cluster-mcp.cmd"

    assert build_cli_install_command(cli_type="kimi", cli_path="kimi", launcher_path=launcher) == [
        "kimi",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "tcb-cluster",
        "--",
        str(launcher),
    ]
    assert build_cli_verify_command("kimi", "kimi") == ["kimi", "mcp", "test", "tcb-cluster"]
    assert build_cli_remove_command("kimi", "kimi") == ["kimi", "mcp", "remove", "tcb-cluster"]


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
    script = Path(__file__).resolve().parents[1] / "bot" / "cluster" / "mcp_stdio.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--config", str(config), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True


def test_cluster_mcp_stdio_advertises_tools_without_active_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TCB_CLUSTER_ACTIVE", raising=False)
    config = tmp_path / "config.json"

    response = cluster_mcp_stdio.handle_request(config, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    tool_names = {tool["name"] for tool in response["result"]["tools"]}
    assert {"cluster_status", "list_agents", "ask_agent", "poll_agent_tasks", "wait_agent_messages"}.issubset(tool_names)
    tools = response["result"]["tools"]
    poll_tool = next(tool for tool in tools if tool["name"] == "poll_agent_tasks")
    assert "include_messages" in poll_tool["inputSchema"]["properties"]
    assert "message_limit" in poll_tool["inputSchema"]["properties"]
    assert "progress" in poll_tool["description"]
    assert "final" in poll_tool["description"]
    wait_tool = next(tool for tool in tools if tool["name"] == "wait_agent_messages")
    assert "wait_seconds" in wait_tool["inputSchema"]["properties"]
    assert "after_sequence" in wait_tool["inputSchema"]["properties"]
    assert "progress" in wait_tool["description"]
    assert "final" in wait_tool["description"]


def test_cluster_mcp_stdio_uses_run_id_argument(tmp_path: Path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("secret-token", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"bridge_url": "http://127.0.0.1:8765", "token_file": str(token)}),
        encoding="utf-8",
    )
    captured = {}

    def fake_post(_config, tool_name, payload, *, run_id):
        captured["tool_name"] = tool_name
        captured["payload"] = payload
        captured["run_id"] = run_id
        return {"ok": True}

    monkeypatch.setattr(cluster_mcp_stdio, "post_mcp_tool", fake_post)
    response = cluster_mcp_stdio.handle_request(
        config,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "ask_agent",
                "arguments": {"agent_id": "tester", "message": "跑测试", "run_id": "clr_test"},
            },
        },
    )

    assert response["result"]["content"][0]["type"] == "text"
    assert captured == {
        "tool_name": "ask_agent",
        "payload": {"agent_id": "tester", "message": "跑测试"},
        "run_id": "clr_test",
    }


def test_cluster_mcp_stdio_returns_tool_error_instead_of_crashing(tmp_path: Path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("secret-token", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"bridge_url": "http://127.0.0.1:8765", "token_file": str(token)}),
        encoding="utf-8",
    )

    def fake_post(*_args, **_kwargs):
        raise RuntimeError("bridge disconnected")

    monkeypatch.setattr(cluster_mcp_stdio, "post_mcp_tool", fake_post)
    response = cluster_mcp_stdio.handle_request(
        config,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "ask_agent",
                "arguments": {"agent_id": "tester", "message": "跑测试", "run_id": "clr_test"},
            },
        },
    )

    assert response["result"]["isError"] is True
    assert "bridge disconnected" in response["result"]["content"][0]["text"]


def test_cluster_mcp_stdio_forwards_poll_agent_tasks(tmp_path: Path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("secret-token", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"bridge_url": "http://127.0.0.1:8765", "token_file": str(token)}),
        encoding="utf-8",
    )
    captured = {}

    def fake_post(_config, tool_name, payload, *, run_id):
        captured["tool_name"] = tool_name
        captured["payload"] = payload
        captured["run_id"] = run_id
        return {"ok": True}

    monkeypatch.setattr(cluster_mcp_stdio, "post_mcp_tool", fake_post)
    cluster_mcp_stdio.handle_request(
        config,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "poll_agent_tasks",
                "arguments": {
                    "run_id": "clr_test",
                    "task_ids": ["clt_one"],
                    "include_output": True,
                    "wait_seconds": 2,
                },
            },
        },
    )

    assert captured == {
        "tool_name": "poll_agent_tasks",
        "payload": {"task_ids": ["clt_one"], "include_output": True, "wait_seconds": 2},
        "run_id": "clr_test",
    }


def test_cluster_mcp_stdio_forwards_wait_agent_messages(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_post(_config, tool_name, payload, *, run_id):
        captured["tool_name"] = tool_name
        captured["payload"] = payload
        captured["run_id"] = run_id
        return {"ok": True, "data": {"timed_out": False, "messages": []}}

    token = tmp_path / "token"
    token.write_text("secret", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"bridge_url": "http://127.0.0.1:8765", "token_file": str(token)}), encoding="utf-8")
    monkeypatch.setattr(cluster_mcp_stdio, "post_mcp_tool", fake_post)

    response = cluster_mcp_stdio.handle_request(
        config,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "wait_agent_messages",
                "arguments": {"run_id": "clr_1", "after_sequence": 2, "wait_seconds": 5},
            },
        },
    )

    assert response is not None
    assert captured["tool_name"] == "wait_agent_messages"
    assert captured["run_id"] == "clr_1"
    assert captured["payload"] == {"after_sequence": 2, "wait_seconds": 5}
