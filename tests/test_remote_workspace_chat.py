from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from bot.models import BotProfile
from bot.remote_workspace import chat, mcp_stdio


@pytest.fixture
def remote_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "get_app_data_root", lambda: tmp_path / "app")
    monkeypatch.setattr(chat, "_bindings", {})
    monkeypatch.setattr(chat, "_profile_tokens", {})
    profile = BotProfile(alias="remote", working_dir=str(tmp_path / "control"))
    profile.remote_workspace = {
        "connection_id": "ssh-1", "host": "build.example", "port": 22, "username": "builder",
        "root": "/work/project", "host_key_fingerprint": "SHA256:private-host-key",
        "key_filename": "/private/ssh/key",
    }
    return profile


def _token(prepared):
    return json.loads(prepared.config_path.read_text(encoding="utf-8"))["token"]


def test_capability_is_stable_scoped_revocable_and_never_retargets(remote_profile):
    first = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765/node/local")
    token = _token(first)
    same = chat.prepare_remote_chat(remote_profile)
    assert _token(same) == token
    other = replace(remote_profile, alias="other")
    other.remote_workspace = dict(remote_profile.remote_workspace)
    second = chat.prepare_remote_chat(other, "http://localhost:8765")
    assert _token(second) != token
    resolved = chat.resolve_remote_chat_token(token)
    assert resolved.alias == "remote"
    resolved.remote_workspace["root"] = "/unrelated"
    assert chat.resolve_remote_chat_token(token).remote_workspace["root"] == "/work/project"
    assert chat.resolve_remote_chat_token("unknown") is None

    remote_profile.remote_workspace["root"] = "/work/different"
    assert chat.resolve_remote_chat_token(token) is None
    changed = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    assert changed.config_path != first.config_path
    assert changed.cli_args("codex_server") != first.cli_args("codex_server")
    assert _token(changed) != token
    assert chat.resolve_remote_chat_token(token) is None
    chat.revoke_remote_chat(remote_profile)
    assert chat.resolve_remote_chat_token(_token(changed)) is None
    assert chat.resolve_remote_chat_token(_token(second)).alias == "other"


def test_instructions_and_cli_config_keep_secrets_out_of_prompt(remote_profile):
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    prompt = prepared.prompt
    assert "/work/project" in prompt and "build.example" in prompt
    for secret in (remote_profile.remote_workspace["key_filename"], remote_profile.remote_workspace["host_key_fingerprint"], _token(prepared)):
        assert secret not in prompt
        assert secret not in " ".join(prepared.cli_args("codex"))
        assert secret not in " ".join(prepared.cli_args("codex_server"))
        assert secret not in " ".join(prepared.cli_args("claude"))
    control = Path(remote_profile.working_dir)
    assert (control / "AGENTS.md").read_text(encoding="utf-8").endswith(prompt)
    assert (control / "CLAUDE.md").read_text(encoding="utf-8").endswith(prompt)
    assert control not in prepared.config_path.parents
    config = json.loads(prepared.cli_args("claude")[1])
    server = config["mcpServers"]["tcb-remote"]
    assert server["command"] == sys.executable
    assert server["args"][-1] == str(prepared.config_path)
    assert prepared.env == {"TCB_REMOTE_MCP_CONFIG": str(prepared.config_path)}
    assert prepared.cli_args("codex_server") == prepared.cli_args("codex")


def test_remote_chat_prepares_antigravity_workspace_mcp_and_is_idempotent(remote_profile):
    remote_profile.cli_type = "antigravity"
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    workspace_path = prepared.workspace_mcp_config_path
    state_path = prepared.workspace_mcp_state_path
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    entry = workspace["mcpServers"][chat.REMOTE_MCP_SERVER_NAME]

    assert prepared.cli_args("antigravity") == []
    assert entry == {
        "command": sys.executable,
        "args": [str(Path(chat.__file__).with_name("mcp_stdio.py").resolve()), "--config", str(prepared.config_path)],
        "cwd": str(Path(remote_profile.working_dir).resolve()),
    }
    assert state_path.exists()
    serialized = workspace_path.read_text(encoding="utf-8")
    assert _token(prepared) not in serialized
    assert remote_profile.remote_workspace["host_key_fingerprint"] not in serialized
    assert remote_profile.remote_workspace["key_filename"] not in serialized

    before = workspace_path.read_bytes()
    same = chat.prepare_remote_chat(remote_profile)
    assert same.workspace_mcp_config_path == workspace_path
    assert workspace_path.read_bytes() == before


def test_remote_chat_workspace_mcp_preserves_user_servers_and_conflicts(remote_profile):
    remote_profile.cli_type = "antigravity"
    config_path = Path(remote_profile.working_dir) / ".agents" / "mcp_config.json"
    config_path.parent.mkdir(parents=True)
    original = {
        "ui": {"theme": "dark"},
        "mcpServers": {"user-server": {"command": "user-tool", "args": ["--keep"]}},
    }
    config_path.write_text(json.dumps(original), encoding="utf-8")
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    configured = json.loads(config_path.read_text(encoding="utf-8"))
    assert configured["ui"] == original["ui"]
    assert configured["mcpServers"]["user-server"] == original["mcpServers"]["user-server"]

    user_owned = {"mcpServers": {chat.REMOTE_MCP_SERVER_NAME: {"command": "user-owned"}}}
    config_path.write_text(json.dumps(user_owned), encoding="utf-8")
    with pytest.raises(chat.RemoteChatPreparationError, match="tcb-remote") as error:
        chat.prepare_remote_chat(remote_profile)
    assert error.value.code == "remote_mcp_config_conflict"
    assert json.loads(config_path.read_text(encoding="utf-8")) == user_owned
    assert prepared.config_path.exists()


def test_remote_chat_workspace_mcp_revoke_removes_only_owned_entry(remote_profile):
    remote_profile.cli_type = "antigravity"
    config_path = Path(remote_profile.working_dir) / ".agents" / "mcp_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"mcpServers": {"user-server": {"command": "keep"}}}), encoding="utf-8")
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")

    chat.revoke_remote_chat(remote_profile)

    restored = json.loads(config_path.read_text(encoding="utf-8"))
    assert restored == {"mcpServers": {"user-server": {"command": "keep"}}}
    assert not prepared.workspace_mcp_state_path.exists()


def test_remote_chat_workspace_mcp_reports_broken_and_stale_states(remote_profile, monkeypatch):
    remote_profile.cli_type = "antigravity"
    config_path = Path(remote_profile.working_dir) / ".agents" / "mcp_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{broken", encoding="utf-8")
    broken = chat.inspect_remote_mcp_config(remote_profile)
    assert broken["state"] == "broken"
    assert broken["diagnostics"][0]["kind"] == "config"

    config_path.unlink()
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    monkeypatch.setattr(chat.sys, "executable", "other-python")
    stale = chat.inspect_remote_mcp_config(remote_profile)
    assert stale["state"] == "stale"
    assert stale["config_path"] == str(prepared.workspace_mcp_config_path)


@pytest.mark.parametrize("tool,args", [
    ("exec", {"commands": []}),
    ("exec", {"commands": ["pwd"], "max_output_chars": 64001}),
    ("read", {"path": "a", "limit": True}), ("read", {"path": "a", "host": "another"}),
    ("edit", {"path": "a", "old_text": "", "new_text": "b"}),
    ("other", {}),
])
def test_tool_bounds_and_target_override_are_rejected(tool, args):
    with pytest.raises(ValueError):
        chat.validate_tool_arguments(tool, args)


def test_mcp_uses_shared_endpoint_scoped_header_and_reports_bridge_errors(remote_profile, monkeypatch):
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765/node/local")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"ok":true,"data":{"stdout":"ok"}}'
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(mcp_stdio.urllib.request, "build_opener", lambda *args: opener)
    packet = {"id": 3, "method": "tools/call", "params": {"name": "exec", "arguments": {"commands": ["pwd", "git status --short"]}}}
    reply = mcp_stdio.handle_request(prepared.config_path, packet)
    assert json.loads(reply["result"]["content"][0]["text"]) == {"stdout": "ok"}
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8765/node/local/api/remote/agent-tools"
    assert request.get_header("X-tcb-remote-token") == _token(prepared)
    assert json.loads(request.data) == {"tool": "exec", "arguments": {
        "commands": ["pwd", "git status --short"], "cwd": ".", "timeout_seconds": 60, "max_output_chars": 12000,
    }}
    opener.reset_mock()
    opener.open.side_effect = HTTPError(request.full_url, 503, "failed", {}, None)
    failed = mcp_stdio.handle_request(prepared.config_path, packet)
    assert failed["result"]["isError"] is True
    assert opener.open.call_count == 1
    assert _token(prepared) not in str(failed)
    import io
    opener.open.side_effect = HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(
        b'{"ok":false,"error":{"code":"remote_auth_required","message":"SSH sign-in required"}}'
    ))
    failed = mcp_stdio.handle_request(prepared.config_path, packet)
    assert "remote_auth_required: SSH sign-in required" in failed["result"]["content"][0]["text"]


def test_stdio_initializes_lists_tools_and_recovers_from_malformed_json(tmp_path):
    packets = ["not-json", json.dumps({"id": 1, "method": "initialize"}),
               json.dumps({"method": "notifications/initialized"}), json.dumps({"id": 2, "method": "tools/list"})]
    result = subprocess.run([sys.executable, mcp_stdio.__file__, "--config", str(tmp_path / "unused.json")],
                            input="\n".join(packets) + "\n", text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == 3
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["result"]["serverInfo"]["name"] == "tcb-remote"
    assert {tool["name"] for tool in replies[2]["result"]["tools"]} == {"exec", "read", "write", "edit", "list"}


def test_stdio_preserves_utf8_paths_and_content_under_windows_encoding():
    calls = [
        {"name": "exec", "arguments": {"cwd": "/home/user803/文档/software-docs", "commands": ["pwd"]}},
        {"name": "write", "arguments": {"path": "说明.md", "content": "中文内容\n完成 ✅"}},
    ]
    packets = [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": call}
               for index, call in enumerate(calls, start=1)]
    bootstrap = (
        "from bot.remote_workspace import mcp_stdio\n"
        "mcp_stdio.post_remote_tool = lambda config, tool, arguments: {'name': tool, 'arguments': arguments}\n"
        "raise SystemExit(mcp_stdio.main(['--config', 'unused.json']))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", bootstrap],
        input=("\n".join(json.dumps(packet, ensure_ascii=False) for packet in packets) + "\n").encode("utf-8"),
        env={**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"},
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
    assert [json.loads(reply["result"]["content"][0]["text"]) for reply in replies] == calls
