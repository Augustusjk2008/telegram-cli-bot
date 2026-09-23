from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError

import pytest

from bot.models import BotProfile, UserSession
from bot.native_agent import service as native_service
from bot.native_agent.pi_rpc_client import PiRpcClient, PiRpcStartRequest
from bot.native_agent.pi_session_runtime import PiSessionRuntimeRegistry, PiSessionRuntimeRequest
from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, PiSessionTurnRecord
from bot.native_agent.service import NativeAgentService, _native_session_meta
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
    assert _token(changed) != token
    assert chat.resolve_remote_chat_token(token) is None
    chat.revoke_remote_chat(remote_profile)
    assert chat.resolve_remote_chat_token(_token(changed)) is None
    assert chat.resolve_remote_chat_token(_token(second)).alias == "other"


def test_instructions_and_cli_config_keep_secrets_out_of_prompt(remote_profile):
    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    prompt = prepared.prompt
    assert "/work/project" in prompt and "build.example" in prompt
    assert "AGENTS.md" in prompt and "CLAUDE.md" in prompt
    assert "no project source or tests" in prompt and "not a filesystem sandbox" in prompt
    for secret in (remote_profile.remote_workspace["key_filename"], remote_profile.remote_workspace["host_key_fingerprint"], _token(prepared)):
        assert secret not in prompt
        assert secret not in " ".join(prepared.cli_args("codex"))
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


@pytest.mark.parametrize("tool,args", [
    ("exec", {"commands": []}), ("exec", {"commands": ["pwd"] * 17}),
    ("exec", {"commands": ["pwd"], "timeout_seconds": 301}),
    ("exec", {"commands": ["pwd"], "max_output_chars": 64001}),
    ("read", {"path": "a", "offset": 0}), ("read", {"path": "a", "limit": True}),
    ("read", {"path": "a", "limit": 2001}), ("read", {"path": "a", "host": "another"}),
    ("edit", {"path": "a", "old_text": "", "new_text": "b"}),
    ("write", {"path": "a", "content": "x" * 1_000_001}),
    ("list", {"max_entries": 1001}), ("other", {}),
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


class FakeClient:
    def __init__(self):
        self.process = SimpleNamespace(poll=lambda: None)
        self.close_count = 0

    async def close(self):
        self.close_count += 1

    async def kill(self):
        await self.close()

    async def get_state(self):
        return {"sessionId": "fresh-session"}

    async def prompt(self, *args, **kwargs):
        pass

    async def events(self):
        yield {"type": "agent_end"}


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("cwd", "different-cwd"), ("model", "new-model"), ("agent_id", "new-agent"),
    ("reasoning_effort", "high"), ("env", {"TCB_REMOTE_MCP_CONFIG": "different-remote.json"}),
])
async def test_runtime_rejects_changed_binding_and_does_not_resume_old_session(tmp_path, monkeypatch, field, value):
    starts = []

    async def start(request):
        starts.append(request)
        return FakeClient()

    monkeypatch.setattr(PiRpcClient, "start", start)
    registry = PiSessionRuntimeRegistry()
    request = PiSessionRuntimeRequest(runtime_key="1:2:conv", owner_key="1:2", conversation_id="conv",
                                      cwd=str(tmp_path), command="pi", native_session_id="old-session")
    first = await registry.open_or_create(request)
    first.state.workspace_history_head = "old-head"
    first.state.linear_index = 7
    assert await registry.open_or_create(request) is first
    second = await registry.open_or_create(replace(request, **{field: value}))
    assert second is not first
    assert starts[-1].session_id == ""
    assert first.state.workspace_history_head == "" and first.state.linear_index == 0
    assert first.client.close_count == 1
    await registry.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("cwd", "different-cwd"), ("model_id", "new-model"), ("pi_agent", "new-agent"),
    ("reasoning_effort", "high"), ("remote_workspace_fingerprint", "different-remote"),
    ("remote_workspace_fingerprint", ""),
])
async def test_service_invalidates_persisted_session_and_rollback_chain(tmp_path, monkeypatch, field, value):
    service = NativeAgentService()
    service._pi_session_store = PiSessionStore(tmp_path / "pi-sessions.json")
    session = UserSession(bot_id=1, user_id=2, working_dir=str(tmp_path), bot_alias="remote")
    session.disable_persistence()
    old_meta = _native_session_meta(cwd=str(tmp_path), model_id="old-model", pi_agent="", reasoning_effort="")
    if field == "remote_workspace_fingerprint":
        old_meta[field] = "old-remote"
    desired = {**old_meta, field: value}
    if field == "remote_workspace_fingerprint" and not value:
        desired.pop(field)
    key = service._pi_record_key(session, 2, "conv")
    service._pi_session_store.upsert(PiSessionRecord(
        key=key, cwd=str(tmp_path), conversation_id="conv", pi_session_id="old-session", session_meta=old_meta,
        workspace_history_head="old-head", linear_index=7,
        turns=[PiSessionTurnRecord(turn_id="turn", linear_index=7, workspace_history_head="old-head")],
    ))
    monkeypatch.setattr(PiRpcClient, "start", AsyncMock(return_value=FakeClient()))
    first = await service._runtime_registry.open_or_create(PiSessionRuntimeRequest(
        runtime_key="1:2:conv", owner_key="1:2", conversation_id="conv", cwd=str(tmp_path), command="pi",
        model="old-model", native_session_id="old-session",
    ))
    first.state.workspace_history_head = "old-head"
    first.state.linear_index = 7
    history = SimpleNamespace(store=Mock())
    history.store.get_conversation_native_session.return_value = {"session_id": "old-session", "meta": old_meta}
    matched_id, _, invalidated = await service._resolve_pi_binding(
        session=session, user_id=2, conversation_id="conv", history_service=history, desired_meta=old_meta,
    )
    assert matched_id == "old-session" and not invalidated
    history.store.invalidate_conversation_workspace_history.assert_not_called()
    if field == "cwd":
        session.working_dir = str(tmp_path / value)
        desired["cwd"] = session.working_dir
    session_id, record, invalidated = await service._resolve_pi_binding(
        session=session, user_id=2, conversation_id="conv", history_service=history, desired_meta=desired,
    )
    assert invalidated and session_id == "" and session.native_agent_session_id is None
    assert record.pi_session_id == "" and record.workspace_history_head == "" and record.linear_index == 0
    old_record = service._pi_session_store.get(key)
    assert old_record.pi_session_id == "" and old_record.turns[0].status == "discarded"
    assert first.client.close_count == 1
    history.store.invalidate_conversation_workspace_history.assert_called_once_with("conv")
    await service._runtime_registry.shutdown()


@pytest.mark.asyncio
async def test_remote_native_turn_disables_local_history_and_loads_remote_env(remote_profile, tmp_path, monkeypatch):
    from bot.web.chat_history_service import ChatHistoryService
    from bot.web.chat_store import ChatStore

    prepared = chat.prepare_remote_chat(remote_profile, "http://127.0.0.1:8765")
    service = NativeAgentService()
    monkeypatch.setattr(native_service.config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(native_service.config, "NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS", 0)
    service._pi_session_store = PiSessionStore(tmp_path / "pi-sessions.json")
    monkeypatch.setattr(service, "_ensure_runtime_eviction_task", lambda: None)
    monkeypatch.setattr(service, "_prompt_options", lambda _: ("provider/model", "", "", ""))
    preflight = Mock(return_value={"ok": True})
    monkeypatch.setattr(native_service, "run_pi_windows_preflight", preflight)
    service._workspace_history.checkpoint = AsyncMock()
    start = AsyncMock(return_value=FakeClient())
    monkeypatch.setattr(PiRpcClient, "start", start)
    session = UserSession(bot_id=1, user_id=2, bot_alias="remote", working_dir=remote_profile.working_dir)
    session.disable_persistence()
    history = ChatHistoryService(ChatStore(tmp_path / "history"))
    events = [event async for event in service.stream_chat(
        profile=remote_profile, session=session, user_text="remote task", prompt_text="remote task", history_service=history,
    )]
    assert events[-1]["type"] == "done", events[-1]
    assert preflight.call_args.args[0].workspace_history_enabled is False
    service._workspace_history.checkpoint.assert_not_awaited()
    request = start.call_args.args[0]
    assert request.env["TCB_REMOTE_MCP_CONFIG"] == str(prepared.config_path)
    assert "/work/project" in request.append_system_prompt
    with pytest.raises(ValueError, match="disabled"):
        await service.rollback_workspace_history(profile=remote_profile, session=session, conversation_id="conv", target_head="head")
    await service._runtime_registry.shutdown()


@pytest.mark.asyncio
async def test_pi_rpc_launch_scopes_extension_to_remote_process(tmp_path, monkeypatch):
    from bot.native_agent import pi_rpc_client

    monkeypatch.setattr(pi_rpc_client, "_build_rpc_command", lambda *args, **kwargs: ["pi", "--mode", "rpc"])
    popen = Mock()
    monkeypatch.setattr(pi_rpc_client.subprocess, "Popen", popen)
    monkeypatch.setattr(PiRpcClient, "__init__", lambda *args, **kwargs: None)
    for env, remote in ((None, False), ({"TCB_REMOTE_MCP_CONFIG": "private-config.json"}, True)):
        await PiRpcClient.start(PiRpcStartRequest(command="pi", cwd=tmp_path, env=env))
        args = popen.call_args.args[0]
        assert ("--extension" in args) is remote
        assert ("--no-builtin-tools" in args) is remote
        if remote:
            assert Path(args[-1]).name == "pi_extension.ts"
