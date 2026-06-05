from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from ag_ui import core
from pydantic import TypeAdapter

from bot.models import BotProfile, UserSession
from bot.native_agent.aggregator import NativeAgentAggregator
from bot.native_agent.ag_ui_mapper import AgUiTurnState, build_run_error_event, build_run_finished_event, map_event as map_ag_ui_event
from bot.native_agent.client import NativeAgentClient, NativeAgentClientError, NativeAgentServerRef, parse_sse_block
from bot.native_agent.events import is_relevant_event, unwrap_event
from bot.native_agent.service import NativeAgentService, normalize_execution_mode
from bot.native_agent.turn_state import NativeAgentTurnState
from bot.native_agent.server_manager import NativeAgentServerManager, _is_opencode_serve_process
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


@pytest.fixture(autouse=True)
def clear_native_agent_global_config(monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")


async def _collect_native_stream(stream):
    return [event async for event in stream]


def test_parse_sse_block_and_unwrap_global_event():
    raw = parse_sse_block(
        "event: message.part.updated\n"
        'data: {"directory":"/repo","payload":{"type":"message.part.updated","sessionID":"s1","part":{"id":"p1","type":"text","delta":"你好"}}}\n'
    )

    assert raw is not None
    event = unwrap_event(raw)

    assert event is not None
    assert event.type == "message.part.updated"
    assert event.directory == "/repo"
    assert is_relevant_event(event, session_id="s1", cwd="/repo")


def test_native_agent_server_manager_matches_only_opencode_serve_processes():
    assert _is_opencode_serve_process("opencode.exe", ["opencode", "serve", "--port", "4750"])
    assert _is_opencode_serve_process("node.exe", ["node", "opencode", "serve"])
    assert not _is_opencode_serve_process("opencode.exe", ["opencode", "run"])
    assert not _is_opencode_serve_process("python.exe", ["python", "-m", "bot"])


def test_native_agent_normalizer_accepts_official_properties_part_delta():
    aggregator = NativeAgentAggregator(user_message_id="u1")
    event = unwrap_event({
        "type": "message.part.updated",
        "properties": {
            "sessionID": "sess-1",
            "part": {"id": "p1", "type": "text"},
            "delta": "ok",
        },
    })

    assert event is not None
    assert event.session_id == "sess-1"
    assert event.part["id"] == "p1"
    assert is_relevant_event(event, session_id="sess-1", cwd="")
    result = aggregator.apply(event)
    assert result.delta == "ok"
    assert aggregator.text() == "ok"


def test_native_agent_aggregator_ignores_user_part_and_streams_opencode_delta():
    aggregator = NativeAgentAggregator(user_message_id="msg-user")

    user_part = unwrap_event({
        "directory": "/repo",
        "payload": {
            "type": "message.part.updated",
            "properties": {
                "sessionID": "sess-1",
                "part": {
                    "id": "part-user",
                    "type": "text",
                    "text": "收到消息没",
                    "messageID": "msg-user",
                    "sessionID": "sess-1",
                },
            },
        },
    })
    first_delta = unwrap_event({
        "directory": "/repo",
        "payload": {
            "type": "message.part.delta",
            "properties": {
                "sessionID": "sess-1",
                "messageID": "msg-assistant",
                "partID": "part-assistant",
                "field": "text",
                "delta": "收",
            },
        },
    })
    second_delta = unwrap_event({
        "directory": "/repo",
        "payload": {
            "type": "message.part.delta",
            "properties": {
                "sessionID": "sess-1",
                "messageID": "msg-assistant",
                "partID": "part-assistant",
                "field": "text",
                "delta": "到了",
            },
        },
    })

    assert user_part is not None
    assert first_delta is not None
    assert second_delta is not None

    user_result = aggregator.apply(user_part)
    first_result = aggregator.apply(first_delta)
    second_result = aggregator.apply(second_delta)

    assert user_result.delta == ""
    assert aggregator.assistant_message_id == "msg-assistant"
    assert first_result.delta == "收"
    assert second_result.delta == "到了"
    assert aggregator.text() == "收到了"


def test_native_agent_transport_events_are_filtered_before_aggregation():
    event = unwrap_event({"type": "server.heartbeat"})

    assert event is not None
    assert event.transport is True
    assert not is_relevant_event(event, session_id="sess-1", cwd="")


@pytest.mark.asyncio
async def test_native_agent_turn_state_reconcile_ignores_messages_before_current_user():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(native_session_id="sess-1", user_message_id="u-new", baseline_message_count=2)

    old_result = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-old", "role": "user", "content": "old"},
            {"id": "a-old", "role": "assistant", "content": "旧回复", "time": {"completed": 1}},
        ],
        aggregator,
        now=1.0,
    )
    new_result = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-old", "role": "user", "content": "old"},
            {"id": "a-old", "role": "assistant", "content": "旧回复", "time": {"completed": 1}},
            {"id": "u-new", "role": "user", "content": "new"},
            {"id": "a-new", "role": "assistant", "content": "新回复", "time": {"completed": 1}},
        ],
        aggregator,
        now=2.0,
    )

    assert old_result == {"done": False, "text": ""}
    assert new_result == {"done": True, "text": "新回复"}


def test_native_agent_aggregator_delta_replace_and_removed():
    aggregator = NativeAgentAggregator(user_message_id="u1")

    first = aggregator.apply(unwrap_event({"type": "message.part.updated", "sessionID": "s1", "part": {"id": "p1", "type": "text", "delta": "你"}}))
    second = aggregator.apply(unwrap_event({"type": "message.part.updated", "sessionID": "s1", "part": {"id": "p1", "type": "text", "delta": "好"}}))
    replace = aggregator.apply(unwrap_event({"type": "message.part.updated", "sessionID": "s1", "part": {"id": "p1", "type": "text", "text": "完成"}}))
    removed = aggregator.apply(unwrap_event({"type": "message.part.removed", "sessionID": "s1", "part": {"id": "p1"}}))

    assert first.delta == "你"
    assert second.delta == "好"
    assert replace.snapshot == "完成"
    assert removed.snapshot == ""


def test_native_agent_permission_event_uses_official_properties_shape():
    aggregator = NativeAgentAggregator(user_message_id="u1")
    event = unwrap_event({
        "type": "permission.updated",
        "properties": {
            "id": "perm-1",
            "sessionID": "sess-1",
            "title": "允许读取文件？",
        },
    })

    assert event is not None
    assert is_relevant_event(event, session_id="sess-1", cwd="")
    result = aggregator.apply(event)

    assert result.status == "允许读取文件？"
    assert result.trace[0]["payload"]["id"] == "perm-1"
    assert aggregator.permission_pending["perm-1"]["sessionID"] == "sess-1"


def test_native_agent_ag_ui_mapper_emits_reasoning_tool_and_error_outcome():
    state = AgUiTurnState(
        thread_id="conv-1",
        run_id="run-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    aggregator = NativeAgentAggregator(user_message_id="user-1")

    reasoning_event = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {"id": "reason-1", "type": "reasoning", "delta": "思考", "state": "completed"},
    })
    assert reasoning_event is not None
    reasoning_result = aggregator.apply(reasoning_event)
    reasoning_types = [event.type for event in map_ag_ui_event(event=reasoning_event, result=reasoning_result, state=state)]

    tool_event = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "tool-1",
            "type": "tool",
            "tool": "shell_command",
            "arguments": {"command": "dir"},
            "output": "Exit code: 0",
            "state": "completed",
        },
    })
    assert tool_event is not None
    tool_result = aggregator.apply(tool_event)
    tool_types = [event.type for event in map_ag_ui_event(event=tool_event, result=tool_result, state=state)]
    error_event = build_run_error_event("OpenCode failed")
    finished_event = build_run_finished_event(state=state, completion_state="error", content="")

    assert reasoning_types == [
        core.EventType.REASONING_START,
        core.EventType.REASONING_MESSAGE_CONTENT,
        core.EventType.REASONING_END,
    ]
    assert tool_types == [
        core.EventType.TOOL_CALL_START,
        core.EventType.TOOL_CALL_ARGS,
        core.EventType.TOOL_CALL_END,
        core.EventType.TOOL_CALL_RESULT,
    ]
    assert error_event.type == core.EventType.RUN_ERROR
    assert finished_event.outcome.type == "interrupt"


def test_native_agent_ag_ui_mapper_keeps_generic_trace_activities_distinct():
    state = AgUiTurnState(
        thread_id="conv-1",
        run_id="run-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    aggregator = NativeAgentAggregator(user_message_id="user-1")
    first_event = unwrap_event({"type": "session.retry", "sessionID": "sess-1"})
    second_event = unwrap_event({"type": "message.retry", "sessionID": "sess-1"})

    assert first_event is not None
    assert second_event is not None
    first_mapped = map_ag_ui_event(event=first_event, result=aggregator.apply(first_event), state=state)
    second_mapped = map_ag_ui_event(event=second_event, result=aggregator.apply(second_event), state=state)

    first_activity = next(event for event in first_mapped if event.type == core.EventType.ACTIVITY_SNAPSHOT)
    second_activity = next(event for event in second_mapped if event.type == core.EventType.ACTIVITY_SNAPSHOT)

    assert first_activity.message_id != second_activity.message_id
    assert first_activity.content["id"] != second_activity.content["id"]
    assert first_activity.content["rawKind"] == "retry"
    assert second_activity.content["rawKind"] == "retry"


def test_native_agent_client_basic_auth_uses_opencode_username():
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096", password="secret"))

    headers = client._headers()

    assert headers["Authorization"] == "Basic b3BlbmNvZGU6c2VjcmV0"


def test_normalize_execution_mode_uses_profile_default_for_pure_native_bot():
    profile = BotProfile(
        alias="native",
        supported_execution_modes=["native_agent"],
        default_execution_mode="native_agent",
    )

    assert normalize_execution_mode("cli", profile) == "native_agent"
    assert normalize_execution_mode("", profile) == "native_agent"


@pytest.mark.asyncio
async def test_native_agent_client_prompt_async_uses_parts_shape(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_request_json(self, method, path, *, json_body=None):
        captured.update({"method": method, "path": path, "json_body": json_body})
        return {}

    monkeypatch.setattr(NativeAgentClient, "_request_json", fake_request_json)
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096"))

    await client.prompt_async(
        "sess-1",
        "你好",
        message_id="msg-1",
        model="anthropic/claude-sonnet-4-5",
        agent="reviewer",
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/session/sess-1/prompt_async"
    assert captured["json_body"] == {
        "messageID": "msg-1",
        "parts": [{"type": "text", "text": "你好"}],
        "model": {
            "providerID": "anthropic",
            "modelID": "claude-sonnet-4-5",
        },
        "agent": "reviewer",
    }


@pytest.mark.asyncio
async def test_native_agent_client_prompt_async_keeps_slash_in_model_id(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_request_json(self, method, path, *, json_body=None):
        captured["json_body"] = json_body
        return {}

    monkeypatch.setattr(NativeAgentClient, "_request_json", fake_request_json)
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096"))

    await client.prompt_async("sess-1", "你好", model="openrouter/openai/gpt-4o-mini")

    assert captured["json_body"]["model"] == {
        "providerID": "openrouter",
        "modelID": "openai/gpt-4o-mini",
    }


@pytest.mark.asyncio
async def test_native_agent_server_manager_reuses_single_global_handle_and_falls_back_to_legacy_path(monkeypatch: pytest.MonkeyPatch):
    from bot import config
    from bot.native_agent import server_manager as server_manager_module

    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    async def fake_health(self):
        return {"ok": True}

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_COMMAND", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PATH", "legacy-opencode")
    monkeypatch.setattr(config, "NATIVE_AGENT_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "NATIVE_AGENT_PORT", 0)
    monkeypatch.setattr(config, "NATIVE_AGENT_SERVER_PASSWORD", "secret")
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", lambda command, _cwd=None: "C:/tools/opencode.cmd")
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: ["cmd.exe", "/d", "/c", path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    monkeypatch.setattr(manager, "_pick_port", lambda _host: 4096)

    first = await manager.ensure_started()
    second = await manager.ensure_started()

    assert first is second
    assert first.base_url == "http://127.0.0.1:4096"
    assert first.password == "secret"
    assert captured["args"] == (
        "cmd.exe",
        "/d",
        "/c",
        "C:/tools/opencode.cmd",
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        "4096",
    )


@pytest.mark.asyncio
async def test_native_agent_server_manager_ignores_bot_provider_config_and_writes_global_opencode_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import server_manager as server_manager_module

    created_processes = []
    captured_envs: list[dict[str, str]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.terminated = False
            self.killed = False

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.killed = True
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        process = FakeProcess()
        created_processes.append(process)
        captured_envs.append(dict(kwargs["env"]))
        return process

    async def fake_health(self):
        return {"ok": True}

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_COMMAND", "opencode")
    monkeypatch.setattr(config, "NATIVE_AGENT_PATH", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "NATIVE_AGENT_PORT", 0)
    monkeypatch.setattr(config, "NATIVE_AGENT_SERVER_PASSWORD", "secret")
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "codeflow")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "gpt-5.1-codex")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "https://cdn.codeflow.asia/v1/")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "sk-server-1234")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")
    monkeypatch.setattr(server_manager_module, "get_app_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", lambda command, _cwd=None: f"C:/tools/{command}.cmd")
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: [path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    ports = iter([4101, 4102, 4103])
    monkeypatch.setattr(manager, "_pick_port", lambda _host: next(ports))
    native_agent = {
        "provider": "codeflow",
        "model": "gpt-5.1-codex",
        "base_url": "https://cdn.codeflow.asia/v1/",
        "api_key": "sk-server-1234",
    }
    first_profile = BotProfile(alias="alpha", native_agent=native_agent)
    same_profile = BotProfile(alias="alpha", native_agent=dict(native_agent))
    other_profile = BotProfile(alias="beta", native_agent=dict(native_agent))
    changed_profile = BotProfile(alias="alpha", native_agent={**native_agent, "model": "gpt-5.2-codex"})

    first = await manager.ensure_started(first_profile)
    same = await manager.ensure_started(same_profile)
    other = await manager.ensure_started(other_profile)
    changed = await manager.ensure_started(changed_profile)

    assert same is first
    assert other is first
    assert changed is first
    assert created_processes == [first.process]
    assert created_processes[0].terminated is False
    assert first.config_path is not None
    assert first.config_path.exists()
    assert changed.config_path is not None and changed.config_path.exists()
    assert captured_envs[0]["OPENCODE_CONFIG"] == str(first.config_path)
    assert captured_envs[0]["OPENCODE_SERVER_PASSWORD"] == "secret"

    payload = json.loads(changed.config_path.read_text(encoding="utf-8"))
    provider = payload["provider"]["codeflow"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {
        "baseURL": "https://cdn.codeflow.asia/v1",
        "apiKey": "sk-server-1234",
    }
    assert provider["models"]["gpt-5.1-codex"]["name"] == "gpt-5.1-codex"
    assert "sk-server-1234" not in changed.key
    assert await manager.get_existing_for_alias("beta") is changed
    assert await manager.get_existing_for_alias("alpha") is changed

    await manager.stop_all()

    assert changed.config_path.exists() is False
    assert created_processes[0].terminated is True


@pytest.mark.asyncio
async def test_native_agent_server_manager_uses_global_provider_model_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import server_manager as server_manager_module

    captured_envs: list[dict[str, str]] = []
    captured_cwds: list[str] = []
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class FakeProcess:
        returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        captured_envs.append(dict(kwargs["env"]))
        captured_cwds.append(str(kwargs["cwd"]))
        return FakeProcess()

    async def fake_health(self):
        return {"ok": True}

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_COMMAND", "opencode")
    monkeypatch.setattr(config, "NATIVE_AGENT_PATH", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "NATIVE_AGENT_PORT", 0)
    monkeypatch.setattr(config, "NATIVE_AGENT_SERVER_PASSWORD", "secret")
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "jojocode")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "gpt-5.4")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "https://api2.jojocode.com/v1/")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "sk-global-1234")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "planner")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "high")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "4096")
    monkeypatch.setattr(config, "WORKING_DIR", str(workspace))
    monkeypatch.setattr(server_manager_module, "get_app_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", lambda command, _cwd=None: f"C:/tools/{command}.cmd")
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: [path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    ports = iter([4101, 4102])
    monkeypatch.setattr(manager, "_pick_port", lambda _host: next(ports))
    bot_workspace = tmp_path / "bot-workspace"
    bot_workspace.mkdir()

    handle = await manager.ensure_started(BotProfile(
        alias="agent-test",
        working_dir=str(bot_workspace),
        native_agent={"provider": "old", "model": "old-model"},
    ))
    same = await manager.ensure_started()

    assert same is not handle
    assert captured_cwds == [str(bot_workspace.resolve()), str(workspace.resolve())]
    assert handle.config_path is not None
    payload = json.loads(handle.config_path.read_text(encoding="utf-8"))
    assert payload["model"] == "jojocode/gpt-5.4"
    provider = payload["provider"]["jojocode"]
    assert provider["options"] == {
        "baseURL": "https://api2.jojocode.com/v1",
        "apiKey": "sk-global-1234",
    }
    assert provider["models"]["gpt-5.4"]["options"] == {
        "reasoningEffort": "high",
        "thinking": {"type": "enabled", "budgetTokens": 4096},
    }
    assert captured_envs[0]["OPENCODE_CONFIG"] == str(handle.config_path)


def test_native_agent_global_config_requires_provider_when_model_has_no_provider(monkeypatch: pytest.MonkeyPatch):
    from bot import config
    from bot.native_agent.configuration import global_native_agent_config, validate_native_agent_model_config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "gpt-5.4")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "https://jojocode.com/v1")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "sk-global-1234")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    with pytest.raises(RuntimeError, match="NATIVE_AGENT_PROVIDER"):
        validate_native_agent_model_config(global_native_agent_config())


def test_native_agent_global_config_splits_provider_from_model(monkeypatch: pytest.MonkeyPatch):
    from bot import config
    from bot.native_agent.configuration import global_native_agent_config, validate_native_agent_model_config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "jojocode/gpt-5.4")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "https://jojocode.com/v1")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "sk-global-1234")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    native_agent = global_native_agent_config()
    validate_native_agent_model_config(native_agent)

    assert native_agent["provider"] == "jojocode"
    assert native_agent["model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_native_agent_server_manager_starts_serve_in_profile_working_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import server_manager as server_manager_module

    workspace_one = tmp_path / "workspace-one"
    workspace_two = tmp_path / "workspace-two"
    workspace_one.mkdir()
    workspace_two.mkdir()
    captured_cwds: list[str] = []
    resolver_cwds: list[str] = []
    created_processes = []

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        process = FakeProcess()
        created_processes.append(process)
        captured_cwds.append(str(kwargs["cwd"]))
        return process

    async def fake_health(self):
        return {"ok": True}

    def fake_resolve_cli_executable(command, cwd=None):
        resolver_cwds.append(str(cwd))
        return f"C:/tools/{command}.cmd"

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_COMMAND", "opencode")
    monkeypatch.setattr(config, "NATIVE_AGENT_PATH", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "NATIVE_AGENT_PORT", 0)
    monkeypatch.setattr(config, "NATIVE_AGENT_SERVER_PASSWORD", "secret")
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")
    monkeypatch.setattr(config, "WORKING_DIR", str(tmp_path / "repo-root"))
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", fake_resolve_cli_executable)
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: [path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    ports = iter([4201, 4202])
    monkeypatch.setattr(manager, "_pick_port", lambda _host: next(ports))

    first = await manager.ensure_started(BotProfile(alias="alpha", working_dir=str(workspace_one)))
    second = await manager.ensure_started(BotProfile(alias="alpha", working_dir=str(workspace_two)))
    same_first = await manager.ensure_started(BotProfile(alias="beta", working_dir=str(workspace_one)))

    assert second is not first
    assert same_first is first
    assert created_processes[0].terminated is False
    assert created_processes[1].terminated is False
    assert captured_cwds == [str(workspace_one.resolve()), str(workspace_two.resolve())]
    assert resolver_cwds == [str(workspace_one.resolve()), str(workspace_two.resolve())]

    await manager.stop_all()


@pytest.mark.asyncio
async def test_native_agent_server_manager_keeps_builtin_provider_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import server_manager as server_manager_module

    captured_envs: list[dict[str, str]] = []

    class FakeProcess:
        returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        captured_envs.append(dict(kwargs["env"]))
        return FakeProcess()

    async def fake_health(self):
        return {"ok": True}

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_COMMAND", "opencode")
    monkeypatch.setattr(config, "NATIVE_AGENT_PATH", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "NATIVE_AGENT_PORT", 0)
    monkeypatch.setattr(config, "NATIVE_AGENT_SERVER_PASSWORD", "secret")
    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "claude-sonnet-4-5")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "https://api.anthropic.com/v1")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "sk-ant-1234")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")
    monkeypatch.setattr(server_manager_module, "get_app_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", lambda command, _cwd=None: f"C:/tools/{command}.cmd")
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: [path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    monkeypatch.setattr(manager, "_pick_port", lambda _host: 4101)
    handle = await manager.ensure_started(BotProfile(
        alias="anthropic-bot",
        native_agent={
            "provider": "ignored",
            "model": "ignored-model",
            "base_url": "https://ignored.example/v1",
            "api_key": "sk-ignored",
        },
    ))

    assert handle.config_path is not None
    payload = json.loads(handle.config_path.read_text(encoding="utf-8"))
    provider = payload["provider"]["anthropic"]
    assert "npm" not in provider
    assert provider["options"] == {
        "baseURL": "https://api.anthropic.com/v1",
        "apiKey": "sk-ant-1234",
    }
    assert provider["models"]["claude-sonnet-4-5"]["name"] == "claude-sonnet-4-5"
    assert captured_envs[0]["OPENCODE_CONFIG"] == str(handle.config_path)

    await manager.stop_all()


@pytest.mark.asyncio
async def test_native_agent_client_list_messages_flattens_info_parts(monkeypatch: pytest.MonkeyPatch):
    async def fake_request_json(self, method, path, *, json_body=None):
        assert method == "GET"
        assert path == "/session/sess-1/message"
        return {
            "data": [
                {
                    "info": {"id": "assistant-1", "role": "assistant"},
                    "parts": [
                        {"type": "text", "text": {"value": "回"}},
                        {"type": "text", "content": "答"},
                    ],
                }
            ]
        }

    monkeypatch.setattr(NativeAgentClient, "_request_json", fake_request_json)
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096"))

    messages = await client.list_messages("sess-1")

    assert messages == [
        {
            "id": "assistant-1",
            "role": "assistant",
            "content": "回答",
            "info": {"id": "assistant-1", "role": "assistant"},
            "parts": [
                {"type": "text", "text": {"value": "回"}},
                {"type": "text", "content": "答"},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_native_agent_client_reply_permission_uses_official_permissions_endpoint(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_request_json(self, method, path, *, json_body=None):
        captured.update({"method": method, "path": path, "json_body": json_body})
        return {"ok": True}

    monkeypatch.setattr(NativeAgentClient, "_request_json", fake_request_json)
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096"))

    await client.reply_permission("sess-1", "perm-1", approved=True)

    assert captured["method"] == "POST"
    assert captured["path"] == "/session/sess-1/permissions/perm-1"
    assert captured["json_body"]["response"] == "once"


@pytest.mark.asyncio
async def test_native_agent_client_events_supports_crlf_and_sets_ready(monkeypatch: pytest.MonkeyPatch):
    class FakeContent:
        async def iter_chunked(self, _size):
            yield (
                b"event: server.connected\r\n"
                b"data: {\"type\":\"server.connected\"}\r\n\r\n"
                b"event: message.part.updated\r\n"
                b"data: {\"directory\":\"/repo\",\"payload\":{\"type\":\"message.part.updated\",\"sessionID\":\"s1\",\"part\":{\"id\":\"p1\",\"type\":\"text\",\"delta\":\"hi\"}}}\r\n\r\n"
            )

    class FakeResponse:
        status = 200
        content = FakeContent()

        async def text(self):
            return ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, url, headers=None):
            assert url == "http://127.0.0.1:4096/event"
            assert headers["Accept"] == "text/event-stream"
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("bot.native_agent.client.ClientSession", FakeSession)
    client = NativeAgentClient(NativeAgentServerRef(base_url="http://127.0.0.1:4096"))
    ready = asyncio.Event()

    events = [event async for event in client.events(global_events=False, ready_event=ready)]

    assert ready.is_set()
    assert events[0]["type"] == "server.connected"
    assert events[1]["type"] == "message.part.updated"
    assert events[1]["payload"]["part"]["delta"] == "hi"


@pytest.mark.asyncio
async def test_native_agent_service_stream_persists_done_message(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.ready = False
            self.prompt_called = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            assert session_id == "sess-1"
            assert text == "你好"
            assert message_id
            assert str(message_id).startswith("msg")
            assert self.ready is True
            assert model in {"", None}
            assert agent in {"", None}
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            self.ready = True
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "回"},
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "答"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [{"role": "assistant", "content": "回答"}]

    class FakeHandle:
        def client(self):
            return FakeClient()

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "回答"
    assert done["message"]["meta"]["native_source"]["provider"] == "native_agent"
    assert session.native_agent_session_id == "sess-1"
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_native_agent_service_stream_protocol_ag_ui_emits_ag_ui_events_and_filters_heartbeat(tmp_path: Path):
    event_adapter = TypeAdapter(core.Event)

    class FakeClient:
        def __init__(self) -> None:
            self.ready = False
            self.prompt_called = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            assert session_id == "sess-1"
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            self.ready = True
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {"directory": str(tmp_path), "payload": {"type": "server.connected"}}
            yield {"directory": str(tmp_path), "payload": {"type": "server.heartbeat"}}
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "permission.updated",
                    "permission": {
                        "id": "perm-1",
                        "sessionID": "sess-1",
                        "title": "允许读取文件？",
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "回"},
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "答"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.status", "sessionID": "sess-1", "status": "处理中"}}
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [{"role": "assistant", "content": "回答"}]

    class FakeHandle:
        def client(self):
            return FakeClient()

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
            protocol="ag-ui",
        )
    ]

    ag_ui_events = [event_adapter.validate_python(item["event"]) for item in events if item["type"] == "ag_ui"]
    ag_ui_types = [event.type for event in ag_ui_events]
    done = next(event for event in events if event["type"] == "done")

    assert ag_ui_types[0] == core.EventType.RUN_STARTED
    assert core.EventType.ACTIVITY_SNAPSHOT in ag_ui_types
    assert core.EventType.TEXT_MESSAGE_START in ag_ui_types
    assert ag_ui_types.count(core.EventType.TEXT_MESSAGE_CONTENT) == 2
    assert core.EventType.TEXT_MESSAGE_END in ag_ui_types
    assert ag_ui_types[-1] == core.EventType.RUN_FINISHED
    ag_ui_payload_text = json.dumps([event.model_dump(mode="json", by_alias=True) for event in ag_ui_events], ensure_ascii=False)
    assert "server.connected" not in ag_ui_payload_text
    assert "server.heartbeat" not in ag_ui_payload_text
    assert "server.heartbeat" not in json.dumps(done["message"].get("meta", {}), ensure_ascii=False)
    assert done["output"] == "回答"


@pytest.mark.asyncio
async def test_native_agent_service_completes_from_list_messages_without_idle(tmp_path: Path):
    blocker = asyncio.Event()

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.cancelled = False
            self.list_calls = 0
            self.prompt_message_id = ""

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            self.prompt_message_id = str(message_id or "")
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "回"},
                },
            }
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        async def list_messages(self, session_id):
            self.list_calls += 1
            if not self.prompt_called:
                return []
            return [
                {"id": self.prompt_message_id, "role": "user", "content": "你好"},
                {"id": "assistant-1", "role": "assistant", "content": "回答", "time": {"completed": 1}},
            ]

    fake_client = FakeClient()

    class FakeHandle:
        def client(self):
            return fake_client

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = await asyncio.wait_for(
        _collect_native_stream(
            service.stream_chat(
                profile=profile,
                session=session,
                user_text="你好",
                prompt_text="你好",
                history_service=history,
            )
        ),
        timeout=3,
    )

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "回答"
    assert fake_client.list_calls >= 1
    assert fake_client.cancelled is True


@pytest.mark.asyncio
async def test_native_agent_service_waits_for_event_ready_before_prompt(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.ready = False
            self.prompt_ready_states: list[bool] = []
            self.prompt_called = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_ready_states.append(self.ready)
            assert model in {"", None}
            assert agent in {"", None}
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            self.ready = True
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "完成"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [{"role": "assistant", "content": "完成"}]

    fake_client = FakeClient()

    class FakeHandle:
        def client(self):
            return fake_client

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    assert fake_client.prompt_ready_states == [True]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_native_agent_stream_starts_separate_conversation_from_cli(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            assert model in {"", None}
            assert agent in {"", None}
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {"id": "p1", "type": "text", "delta": "原生"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [{"role": "assistant", "content": "原生"}]

    class FakeHandle:
        def client(self):
            return FakeClient()

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", cli_type="codex", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    cli_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="CLI",
        native_provider="codex",
    )
    history.complete_turn(cli_handle, content="CLI 回复", completion_state="completed", native_session_id="thread-1")
    cli_conversation_id = session.active_conversation_id

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["message"]["meta"]["native_source"]["provider"] == "native_agent"
    assert session.active_conversation_id != cli_conversation_id
    conversations = ChatStore(tmp_path).list_conversations(
        bot_id=1,
        user_id=1001,
        agent_id="main",
        working_dir=str(tmp_path),
        limit=10,
    )
    providers = {item["native_provider"] for item in conversations}
    assert providers == {"codex", "native_agent"}


@pytest.mark.asyncio
async def test_native_agent_service_recreates_session_when_working_dir_changes(tmp_path: Path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False

        async def get_session(self, session_id):
            assert session_id == "sess-old"
            return {"id": "sess-old", "directory": str(old_dir)}

        async def create_session(self, *, cwd=None):
            assert cwd == str(new_dir)
            return {"id": "sess-new", "directory": str(new_dir)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            assert session_id == "sess-new"
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(new_dir),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-new",
                    "part": {"id": "p1", "type": "text", "delta": "新目录"},
                },
            }
            yield {"directory": str(new_dir), "payload": {"type": "session.idle", "sessionID": "sess-new"}}

        async def list_messages(self, session_id):
            assert session_id == "sess-new"
            return [{"role": "assistant", "content": "新目录"}]

    fake_client = FakeClient()

    class FakeHandle:
        def client(self):
            return fake_client

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(alias="main", working_dir=str(new_dir))
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        working_dir=str(new_dir),
        native_agent_session_id="sess-old",
    )
    history = ChatHistoryService(ChatStore(new_dir))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "新目录"
    assert session.native_agent_session_id == "sess-new"


@pytest.mark.asyncio
async def test_native_agent_service_recreates_invalid_persisted_session_and_passes_model_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "claude-sonnet-4-5")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "https://api.anthropic.com/v1")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "sk-ant-1234")
    monkeypatch.setattr(config, "NATIVE_AGENT_OPENCODE_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.prompt_payload: tuple[str, str, str, str, str] | None = None

        async def get_session(self, session_id):
            raise NativeAgentClientError(f"missing session {session_id}")

        async def create_session(self, *, cwd=None):
            assert cwd == str(tmp_path)
            return {"id": "sess-new"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            self.prompt_payload = (session_id, text, str(message_id or ""), str(model or ""), str(agent or ""))
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-new",
                    "part": {"id": "p1", "type": "text", "delta": "完成"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-new"}}

        async def list_messages(self, session_id):
            assert session_id == "sess-new"
            return [{"role": "assistant", "content": "完成"}]

    fake_client = FakeClient()

    class FakeHandle:
        def client(self):
            return fake_client

    class FakeManager:
        async def ensure_started(self):
            return FakeHandle()

        async def get_existing(self):
            return FakeHandle()

    service = NativeAgentService()
    service._server_manager = FakeManager()
    profile = BotProfile(
        alias="main",
        working_dir=str(tmp_path),
        native_agent={
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "opencode_agent": "reviewer",
        },
    )
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        working_dir=str(tmp_path),
        native_agent_session_id="sess-old",
    )
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "完成"
    assert session.native_agent_session_id == "sess-new"
    assert fake_client.prompt_payload is not None
    assert fake_client.prompt_payload[0] == "sess-new"
    assert fake_client.prompt_payload[1] == "你好"
    assert fake_client.prompt_payload[3] == "anthropic/claude-sonnet-4-5"
    assert fake_client.prompt_payload[4] == "reviewer"


@pytest.mark.asyncio
async def test_native_agent_service_persists_turn_when_server_start_fails(tmp_path: Path):
    class FailingManager:
        async def ensure_started(self, profile):
            raise RuntimeError("serve failed")

    service = NativeAgentService()
    service._server_manager = FailingManager()
    profile = BotProfile(alias="agent_test", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="agent_test", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="你好",
            prompt_text="你好",
            history_service=history,
        )
    ]

    assert events == [{"type": "error", "code": "native_agent_error", "message": "原生 agent 执行失败: serve failed"}]
    assert session.is_processing is False

    messages = history.list_history(profile, session)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "你好"
    assert messages[1]["state"] == "error"
    assert messages[1]["content"] == "serve failed"
