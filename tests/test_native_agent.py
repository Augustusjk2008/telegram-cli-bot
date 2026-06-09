from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path

import pytest
from ag_ui import core
from pydantic import TypeAdapter

from bot.models import BotProfile, UserSession
from bot.native_agent.aggregator import NativeAgentAggregator
from bot.native_agent.ag_ui_mapper import AgUiTurnState, build_run_error_event, build_run_finished_event, map_event as map_ag_ui_event
from bot.native_agent.client import NativeAgentClient, NativeAgentClientError, NativeAgentServerRef, parse_sse_block
from bot.native_agent.events import is_relevant_event, unwrap_event
from bot.native_agent import service as native_service_module
from bot.native_agent.run_client import NativeAgentRunClient, NativeAgentRunError, NativeAgentRunRequest
from bot.native_agent.run_events import extract_step_finish_usage, run_json_to_events
from bot.native_agent.service import NativeAgentService, normalize_execution_mode
from bot.native_agent.turn_state import NativeAgentTurnState
from bot.native_agent.server_manager import NativeAgentServerManager, _is_opencode_serve_process
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


@pytest.fixture(autouse=True)
def clear_native_agent_global_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from bot import config

    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "tcb-data"))
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


def test_native_agent_relevant_event_normalizes_cwd(tmp_path: Path):
    event_dir = str(tmp_path).replace(os.sep, "/" if os.sep == "\\" else os.sep)
    event = unwrap_event({
        "directory": event_dir.upper() if os.name == "nt" else event_dir,
        "payload": {"type": "session.idle", "sessionID": "sess-1"},
    })

    assert event is not None
    assert is_relevant_event(event, session_id="sess-1", cwd=str(tmp_path))


def test_native_agent_server_manager_matches_only_opencode_serve_processes():
    assert _is_opencode_serve_process("opencode.exe", ["opencode", "serve", "--port", "4750"])
    assert _is_opencode_serve_process("node.exe", ["node", "opencode", "serve"])
    assert not _is_opencode_serve_process("opencode.exe", ["opencode", "run"])
    assert not _is_opencode_serve_process("python.exe", ["python", "-m", "bot"])


def test_native_agent_server_manager_matches_only_tcb_managed_opencode_serve_processes(tmp_path: Path):
    from bot.native_agent import server_manager as server_manager_module

    helper = server_manager_module._is_tcb_managed_opencode_serve_process
    native_root = tmp_path / "data" / "native-agent"
    old_config = native_root / "opencode-workspace-abc.json"

    assert not helper("node.exe", ["node", "opencode", "serve"], {}, app_data_root=tmp_path / "data")
    assert helper(
        "node.exe",
        ["node", "opencode", "serve"],
        {"TCB_NATIVE_AGENT_MANAGED": "1"},
        app_data_root=tmp_path / "data",
    )
    assert helper(
        "node.exe",
        ["node", "opencode", "serve"],
        {"OPENCODE_CONFIG": str(old_config)},
        app_data_root=tmp_path / "data",
    )
    assert not helper(
        "opencode.exe",
        ["opencode", "run"],
        {"TCB_NATIVE_AGENT_MANAGED": "1", "OPENCODE_CONFIG": str(old_config)},
        app_data_root=tmp_path / "data",
    )


def test_native_agent_server_manager_terminates_only_tcb_managed_opencode_processes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from types import SimpleNamespace
    from bot.native_agent import server_manager as server_manager_module

    class FakePsutilError(Exception):
        pass

    class FakeProcess:
        def __init__(self, pid: int, name: str, cmdline: list[str], environ: dict[str, str] | None = None) -> None:
            self.pid = pid
            self.info = {"pid": pid, "name": name, "cmdline": cmdline}
            self._environ = environ
            self.terminated = False
            self.killed = False

        def environ(self):
            if self._environ is None:
                raise FakePsutilError()
            return self._environ

        def children(self, recursive: bool = False):
            return []

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    manual = FakeProcess(101, "node.exe", ["node", "opencode", "serve"], {})
    managed = FakeProcess(102, "node.exe", ["node", "opencode", "serve"], {"TCB_NATIVE_AGENT_MANAGED": "1"})
    unreadable = FakeProcess(103, "opencode.exe", ["opencode", "serve"], None)
    other = FakeProcess(104, "python.exe", ["python", "-m", "bot"], {"TCB_NATIVE_AGENT_MANAGED": "1"})
    processes = [manual, managed, unreadable, other]

    fake_psutil = SimpleNamespace(
        NoSuchProcess=FakePsutilError,
        AccessDenied=FakePsutilError,
        ZombieProcess=FakePsutilError,
        process_iter=lambda _attrs: processes,
        wait_procs=lambda procs, timeout: (procs, []),
    )
    monkeypatch.setattr(server_manager_module, "psutil", fake_psutil)
    monkeypatch.setattr(server_manager_module, "get_app_data_root", lambda: tmp_path / "data")

    killed = NativeAgentServerManager().terminate_stale_opencode_processes()

    assert killed == [102]
    assert manual.terminated is False
    assert managed.terminated is True
    assert unreadable.terminated is False
    assert other.terminated is False


def test_native_agent_server_manager_injects_tcb_cluster_mcp_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent import config_store
    from bot.native_agent import server_manager as server_manager_module

    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(server_manager_module, "get_app_data_root", lambda: tmp_path / "data")
    config_store.save_native_agent_config({
        "provider": {
            "jojocode": {
                "models": {"gpt-5.4": {"name": "gpt-5.4"}},
            }
        },
        "mcp": {
            "existing": {"type": "local", "command": ["existing"], "enabled": True},
        },
    })

    manager = NativeAgentServerManager()
    path = manager._write_opencode_config("key-1", {"native_agent_model": "jojocode/gpt-5.4"})

    launcher = Path.home() / ".tcb" / "bin" / ("tcb-cluster-mcp.cmd" if os.name == "nt" else "tcb-cluster-mcp.sh")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mcp"]["existing"]["command"] == ["existing"]
    assert payload["mcp"]["tcb-cluster"] == {
        "type": "local",
        "command": [str(launcher)],
        "enabled": True,
    }


def test_native_agent_server_manager_server_key_includes_cluster_mcp_launcher(monkeypatch: pytest.MonkeyPatch):
    from bot.native_agent import server_manager as server_manager_module

    manager = NativeAgentServerManager()
    server_config = {
        "command": "opencode",
        "hostname": "127.0.0.1",
        "port": 0,
        "password": "",
        "native_agent": {},
        "working_dir": ".",
    }
    first_key = manager._server_key(server_config)
    monkeypatch.setattr(
        server_manager_module,
        "_cluster_mcp_launcher_signature",
        lambda: {"launcher_path": "C:/other/tcb-cluster-mcp.cmd"},
    )
    second_key = manager._server_key(server_config)

    assert first_key != second_key


def test_native_agent_run_config_injects_tcb_cluster_mcp_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent import config_store, run_config

    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(run_config, "get_app_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(run_config, "prepare_cluster_mcp_launcher_for_native", lambda: tmp_path / "tcb-cluster-mcp.cmd")
    config_store.save_native_agent_config({
        "provider": {
            "jojocode": {
                "models": {"gpt-5.4": {"name": "gpt-5.4"}},
            }
        },
        "mcp": {
            "existing": {"type": "local", "command": ["existing"], "enabled": True},
        },
    })

    path = run_config.write_runtime_opencode_config(
        key="key-1",
        native_agent={"native_agent_model": "jojocode/gpt-5.4"},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mcp"]["existing"]["command"] == ["existing"]
    assert payload["mcp"]["tcb-cluster"] == {
        "type": "local",
        "command": [str(tmp_path / "tcb-cluster-mcp.cmd")],
        "enabled": True,
    }


def test_native_agent_run_events_map_text_and_step_finish():
    text_events = run_json_to_events(
        {
            "type": "text",
            "sessionID": "sess-1",
            "part": {"id": "p1", "type": "text", "text": "你好"},
        },
        cwd="/repo",
        assistant_message_id="assistant-1",
    )
    finish_events = run_json_to_events(
        {
            "type": "step_finish",
            "sessionID": "sess-1",
            "tokens": {"input": 10, "cache": {"read": 2}, "output": 3},
            "cost": 0.01,
        },
        cwd="/repo",
        assistant_message_id="assistant-1",
    )

    assert text_events[0]["payload"]["type"] == "message.part.updated"
    assert text_events[0]["payload"]["part"]["delta"] == "你好"
    assert finish_events[0]["payload"]["type"] == "message.updated"
    assert finish_events[1]["payload"]["type"] == "session.idle"
    assert extract_step_finish_usage(finish_events[0]["payload"]["raw"]) == {
        "input": 10,
        "cache": {"read": 2},
        "output": 3,
        "cost": 0.01,
    }


def test_native_agent_run_client_builds_opencode_run_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot.native_agent import run_client

    monkeypatch.setattr(run_client, "runtime_config_key", lambda **_kwargs: "key-1")
    monkeypatch.setattr(run_client, "write_runtime_opencode_config", lambda **_kwargs: tmp_path / "run.json")
    monkeypatch.setattr(run_client, "resolve_cli_executable", lambda command, _cwd=None: f"C:/tools/{command}.cmd")
    monkeypatch.setattr(run_client, "build_executable_invocation", lambda path: ["cmd.exe", "/d", "/c", path])

    args, env, config_path = NativeAgentRunClient().build_run_command(
        NativeAgentRunRequest(
            cwd=str(tmp_path),
            prompt="你好",
            command="opencode",
            session_id="sess-1",
            model_id="anthropic/claude",
            agent_id="reviewer",
            variant="high",
            native_agent={"native_agent_model": "anthropic/claude"},
        )
    )

    assert args == [
        "cmd.exe",
        "/d",
        "/c",
        "C:/tools/opencode.cmd",
        "run",
        "--format",
        "json",
        "--dir",
        str(tmp_path.resolve()),
        "--session",
        "sess-1",
        "--model",
        "anthropic/claude",
        "--agent",
        "reviewer",
        "--variant",
        "high",
        "你好",
    ]
    assert env["OPENCODE_CONFIG"] == str(tmp_path / "run.json")
    assert config_path == tmp_path / "run.json"


@pytest.mark.asyncio
async def test_native_agent_run_client_stream_parses_json_and_raw_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot.native_agent import run_client

    class FakeProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdout = io.StringIO('{"type":"text","text":"回"}\nnot-json\n')
            self.stderr = io.StringIO("")
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

    monkeypatch.setattr(run_client.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(run_client, "runtime_config_key", lambda **_kwargs: "key-1")
    monkeypatch.setattr(run_client, "write_runtime_opencode_config", lambda **_kwargs: tmp_path / "run.json")

    events = [
        event async for event in NativeAgentRunClient().stream(
            NativeAgentRunRequest(cwd=str(tmp_path), prompt="你好", command="opencode")
        )
    ]

    assert events == [
        {"type": "text", "text": "回"},
        {"type": "raw_text", "raw_text": "not-json"},
    ]


@pytest.mark.asyncio
async def test_native_agent_run_client_raises_with_stderr_on_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot.native_agent import run_client

    class FakeProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("bad session\n")
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 2
            return 2

        def terminate(self):
            self.returncode = -15

    monkeypatch.setattr(run_client.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(run_client, "runtime_config_key", lambda **_kwargs: "key-1")
    monkeypatch.setattr(run_client, "write_runtime_opencode_config", lambda **_kwargs: tmp_path / "run.json")

    with pytest.raises(NativeAgentRunError) as exc_info:
        _ = [
            event async for event in NativeAgentRunClient().stream(
                NativeAgentRunRequest(cwd=str(tmp_path), prompt="你好", command="opencode")
            )
        ]

    assert exc_info.value.returncode == 2
    assert "bad session" in str(exc_info.value)


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


def test_native_agent_aggregator_uses_part_message_id_over_event_id_for_opencode_events():
    aggregator = NativeAgentAggregator(user_message_id="msg-user")

    user_part = unwrap_event({
        "directory": "/repo",
        "payload": {
            "type": "message.part.updated",
            "properties": {
                "sessionID": "sess-1",
                "messageID": "evt-user-part-updated",
                "part": {
                    "id": "part-user",
                    "type": "text",
                    "text": "你是谁",
                    "messageID": "msg-user",
                    "sessionID": "sess-1",
                },
            },
        },
    })
    assistant_start = unwrap_event({
        "directory": "/repo",
        "payload": {
            "type": "message.updated",
            "properties": {
                "sessionID": "sess-1",
                "info": {
                    "id": "msg-assistant",
                    "role": "assistant",
                    "sessionID": "sess-1",
                },
            },
        },
    })
    assistant_delta = unwrap_event({
        "directory": "/repo",
        "payload": {
            "type": "message.part.delta",
            "properties": {
                "sessionID": "sess-1",
                "messageID": "evt-assistant-delta",
                "partID": "part-assistant",
                "field": "text",
                "delta": "我是助手",
            },
        },
    })

    assert user_part is not None
    assert assistant_start is not None
    assert assistant_delta is not None

    assert aggregator.apply(user_part).delta == ""
    assert aggregator.apply(assistant_start).assistant_message_id == "msg-assistant"
    assert aggregator.apply(assistant_delta).delta == "我是助手"
    assert aggregator.text() == "我是助手"


def test_native_agent_aggregator_suppresses_reasoning_and_sync_noise():
    aggregator = NativeAgentAggregator(user_message_id="msg-user")

    reasoning = unwrap_event({
        "payload": {
            "type": "message.part.updated",
            "properties": {
                "sessionID": "sess-1",
                "messageID": "msg-assistant",
                "part": {
                    "id": "part-reasoning",
                    "type": "reasoning",
                    "text": "internal thinking",
                    "messageID": "msg-assistant",
                },
            },
        },
    })
    sync = unwrap_event({"payload": {"type": "sync", "properties": {"sessionID": "sess-1"}}})
    session_updated = unwrap_event({"payload": {"type": "session.updated", "properties": {"sessionID": "sess-1"}}})

    assert reasoning is not None
    assert sync is not None
    assert session_updated is not None

    assert aggregator.apply(reasoning).trace == []
    assert aggregator.apply(sync).trace == []
    assert aggregator.apply(session_updated).trace == []


def test_native_agent_aggregator_suppresses_reasoning_delta_and_step_noise():
    aggregator = NativeAgentAggregator(user_message_id="msg-user")

    assistant_start = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {"id": "msg-assistant", "role": "assistant", "sessionID": "sess-1"},
    })
    step_start = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "part-step",
            "type": "step-start",
            "messageID": "msg-assistant",
            "sessionID": "sess-1",
        },
    })
    reasoning_start = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "part-reasoning",
            "type": "reasoning",
            "messageID": "msg-assistant",
            "sessionID": "sess-1",
        },
    })
    reasoning_delta = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "msg-assistant",
        "partID": "part-reasoning",
        "field": "text",
        "delta": "**Counting project folders**",
    })
    final_text = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "msg-assistant",
        "partID": "part-text",
        "field": "text",
        "delta": "最终回答",
    })

    assert assistant_start is not None
    assert step_start is not None
    assert reasoning_start is not None
    assert reasoning_delta is not None
    assert final_text is not None

    assert aggregator.apply(assistant_start).assistant_message_id == "msg-assistant"
    assert aggregator.apply(step_start).trace == []
    assert aggregator.apply(reasoning_start).trace == []
    assert aggregator.apply(reasoning_delta).delta == ""
    assert aggregator.apply(final_text).delta == "最终回答"
    assert aggregator.text() == "最终回答"


def test_native_agent_aggregator_filters_watcher_noise_from_process_events():
    aggregator = NativeAgentAggregator(user_message_id="msg-user")
    edited = unwrap_event({
        "type": "file.edited",
        "id": "evt-file-edited",
        "path": "docs/runtime-environment-note.md",
    })
    watcher = unwrap_event({
        "type": "file.watcher.updated",
        "id": "evt-file-watcher",
        "path": "docs/runtime-environment-note.md",
    })

    assert edited is not None
    assert watcher is not None

    edited_result = aggregator.apply(edited)
    watcher_result = aggregator.apply(watcher)

    assert edited_result.trace[0]["kind"] == "event"
    assert watcher_result.trace == []


def test_native_agent_aggregator_ignores_idle_before_current_turn_activity():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    idle = unwrap_event({"type": "session.idle", "sessionID": "sess-1"})

    assert idle is not None

    result = aggregator.apply(idle)

    assert result.status == "session.idle"
    assert result.done is False
    assert aggregator.text() == ""


@pytest.mark.asyncio
async def test_native_agent_turn_state_waits_past_tool_calls_message_for_final_answer():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(native_session_id="sess-1", user_message_id="u-new", baseline_message_count=0)

    tool_calls_only = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-new", "role": "user", "content": "pwd"},
            {
                "id": "a-tool",
                "role": "assistant",
                "finish": "tool-calls",
                "content": "中间说明",
                "time": {"completed": 1},
                "parts": [
                    {"type": "reasoning", "text": "internal"},
                    {"type": "tool", "tool": "bash", "state": {"status": "completed", "output": "H:\\repo"}},
                ],
            },
        ],
        aggregator,
        now=1.0,
    )
    final_answer = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-new", "role": "user", "content": "pwd"},
            {
                "id": "a-tool",
                "role": "assistant",
                "finish": "tool-calls",
                "content": "中间说明",
                "time": {"completed": 1},
                "parts": [
                    {"type": "reasoning", "text": "internal"},
                    {"type": "tool", "tool": "bash", "state": {"status": "completed", "output": "H:\\repo"}},
                ],
            },
            {
                "id": "a-final",
                "role": "assistant",
                "finish": "stop",
                "content": "当前工作目录是 `H:\\repo`。",
                "time": {"completed": 2},
                "parts": [{"type": "text", "text": "当前工作目录是 `H:\\repo`。"}],
            },
        ],
        aggregator,
        now=2.0,
    )

    assert tool_calls_only == {"done": False, "text": ""}
    assert final_answer == {"done": True, "text": "当前工作目录是 `H:\\repo`。"}


@pytest.mark.asyncio
async def test_native_agent_turn_state_ignores_live_tool_calls_text_until_final_answer():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(native_session_id="sess-1", user_message_id="u-new", baseline_message_count=0)
    text_event = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-tool",
        "partID": "p-text",
        "field": "text",
        "delta": "先看目录结构。",
    })
    tool_call_message = unwrap_event({
        "type": "message.updated",
        "message": {
            "id": "a-tool",
            "role": "assistant",
            "finish": "tool-calls",
            "content": "先看目录结构。",
            "time": {"completed": 1},
        },
    })
    idle_event = unwrap_event({"type": "session.idle", "sessionID": "sess-1"})

    assert text_event is not None
    assert tool_call_message is not None
    assert idle_event is not None

    first = aggregator.apply(text_event)
    state.observe(text_event, first, now=1.0)
    followup = aggregator.apply(tool_call_message)
    state.observe(tool_call_message, followup, now=2.0)
    idle = aggregator.apply(idle_event)
    state.observe(idle_event, idle, now=3.0)

    assert first.delta == "先看目录结构。"
    assert followup.replace_text is True
    assert followup.snapshot == ""
    assert aggregator.text() == ""
    assert state.done is False

    final = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-new", "role": "user", "content": "看项目"},
            {
                "id": "a-tool",
                "role": "assistant",
                "finish": "tool-calls",
                "content": "先看目录结构。",
                "time": {"completed": 1},
            },
            {
                "id": "a-final",
                "role": "assistant",
                "finish": "stop",
                "content": "这是最终结论。",
                "time": {"completed": 2},
                "parts": [{"type": "text", "text": "这是最终结论。"}],
            },
        ],
        aggregator,
        now=4.0,
    )

    assert final == {"done": True, "text": "这是最终结论。"}


def test_native_agent_aggregator_idle_completes_after_tool_followup_final_delta_only():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(native_session_id="sess-1", user_message_id="u-new", baseline_message_count=0)
    preview = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-tool",
        "partID": "p-preview",
        "field": "text",
        "delta": "先检查。",
    })
    followup = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "a-tool",
            "role": "assistant",
            "finish": "tool-calls",
            "content": "先检查。",
            "time": {"completed": 1},
        },
    })
    final_delta = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-final",
        "partID": "p-final",
        "field": "text",
        "delta": "这是最终答复。",
    })
    idle = unwrap_event({"type": "session.idle", "sessionID": "sess-1"})

    assert preview is not None
    assert followup is not None
    assert final_delta is not None
    assert idle is not None

    for now, event in enumerate([preview, followup, final_delta], start=1):
        result = aggregator.apply(event)
        state.observe(event, result, now=float(now))
        assert result.done is False

    result = aggregator.apply(idle)
    state.observe(idle, result, now=4.0)

    assert aggregator.text() == "这是最终答复。"
    assert result.done is True
    assert state.done is True


def test_native_agent_aggregator_reclassifies_followup_preview_as_commentary_trace():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    preview = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-tool",
        "partID": "p-preview",
        "field": "text",
        "delta": "先检查目录结构。",
    })
    followup = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "a-tool",
            "role": "assistant",
            "finish": "tool-calls",
            "content": "先检查目录结构。",
            "time": {"completed": 1},
        },
    })

    assert preview is not None
    assert followup is not None

    assert aggregator.apply(preview).delta == "先检查目录结构。"
    result = aggregator.apply(followup)

    assert result.replace_text is True
    assert result.snapshot == ""
    assert result.trace[0]["kind"] == "commentary"
    assert result.trace[0]["summary"] == "先检查目录结构。"
    assert aggregator.text() == ""


def test_native_agent_trace_keeps_commentary_before_tool_call():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    preview = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "assistant-tool",
        "partID": "preview",
        "field": "text",
        "delta": "我先读取文件。",
    })
    tool = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "tool-1",
            "type": "tool",
            "messageID": "assistant-tool",
            "tool": "bash",
            "arguments": {"command": "pwd"},
            "state": {"status": "running"},
        },
    })

    assert preview is not None
    assert tool is not None
    assert aggregator.apply(preview).delta == "我先读取文件。"
    result = aggregator.apply(tool)

    assert [item["kind"] for item in result.trace] == ["commentary", "tool_call"]
    assert result.trace[0]["summary"] == "我先读取文件。"
    assert result.trace[1]["call_id"] == "tool-1"
    assert aggregator.text() == ""


def test_native_agent_aggregator_deduplicates_commentary_reclassified_after_tool_flush():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    preview = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "assistant-tool",
            "role": "assistant",
            "content": "我先读取文件。",
        },
    })
    tool = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "tool-1",
            "type": "tool",
            "messageID": "assistant-tool",
            "tool": "bash",
            "arguments": {"command": "pwd"},
            "state": {"status": "running"},
        },
    })
    replayed_preview = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "assistant-tool",
            "role": "assistant",
            "content": "我先读取文件。",
        },
    })
    followup = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "assistant-tool",
            "role": "assistant",
            "finish": "tool-calls",
            "content": "我先读取文件。",
        },
    })

    assert preview is not None
    assert tool is not None
    assert replayed_preview is not None
    assert followup is not None

    aggregator.apply(preview)
    tool_result = aggregator.apply(tool)
    aggregator.apply(replayed_preview)
    followup_result = aggregator.apply(followup)

    assert [item["kind"] for item in tool_result.trace] == ["commentary", "tool_call"]
    assert tool_result.trace[0]["summary"] == "我先读取文件。"
    assert followup_result.trace == []


def test_native_agent_trace_collapses_running_and_completed_tool_results():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    running_empty = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "tool-1",
            "type": "tool",
            "tool": "bash",
            "arguments": {"command": "pwd"},
            "state": {"status": "running"},
        },
    })
    running_output = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "tool-1",
            "type": "tool",
            "tool": "bash",
            "arguments": {"command": "pwd"},
            "state": {"status": "running", "output": "C:/repo"},
        },
    })
    completed_same_output = unwrap_event({
        "type": "message.part.updated",
        "sessionID": "sess-1",
        "part": {
            "id": "tool-1",
            "type": "tool",
            "tool": "bash",
            "arguments": {"command": "pwd"},
            "state": {"status": "completed", "output": "C:/repo"},
        },
    })

    assert running_empty is not None
    assert running_output is not None
    assert completed_same_output is not None

    first = aggregator.apply(running_empty)
    second = aggregator.apply(running_output)
    third = aggregator.apply(completed_same_output)

    assert [item["kind"] for item in first.trace] == ["tool_call"]
    assert [item["kind"] for item in second.trace] == ["tool_result"]
    assert second.trace[0]["summary"] == "C:/repo"
    assert third.trace == []


def test_native_agent_aggregator_reclassifies_multipart_preview_in_display_order():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    later = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-tool",
        "partID": "z-later",
        "field": "text",
        "delta": "第二句。",
    })
    earlier = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-tool",
        "partID": "a-earlier",
        "field": "text",
        "delta": "第一句。",
    })
    followup = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "a-tool",
            "role": "assistant",
            "finish": "tool-calls",
            "content": "第一句。第二句。",
            "time": {"completed": 1},
        },
    })

    assert later is not None
    assert earlier is not None
    assert followup is not None

    aggregator.apply(later)
    aggregator.apply(earlier)
    assert aggregator.text() == "第二句。第一句。"
    result = aggregator.apply(followup)

    assert result.trace[0]["kind"] == "commentary"
    assert result.trace[0]["summary"] == "第二句。第一句。"


def test_native_agent_aggregator_reclassifies_unfinished_message_when_assistant_id_switches():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    preview = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "assistant-preview",
        "partID": "preview",
        "field": "text",
        "delta": "先检查目录结构。",
    })
    final = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "assistant-final",
        "partID": "final",
        "field": "text",
        "delta": "这是最终答复。",
    })

    assert preview is not None
    assert final is not None

    assert aggregator.apply(preview).delta == "先检查目录结构。"
    result = aggregator.apply(final)

    assert result.replace_text is True
    assert result.snapshot == "这是最终答复。"
    assert result.trace[0]["kind"] == "commentary"
    assert result.trace[0]["summary"] == "先检查目录结构。"
    assert aggregator.text() == "这是最终答复。"


def test_native_agent_aggregator_does_not_trace_final_answer_as_commentary():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    delta = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-final",
        "partID": "p-final",
        "field": "text",
        "delta": "这是最终答复。",
    })
    completed = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "a-final",
            "role": "assistant",
            "finish": "stop",
            "content": "这是最终答复。",
            "time": {"completed": 1},
        },
    })

    assert delta is not None
    assert completed is not None

    assert aggregator.apply(delta).delta == "这是最终答复。"
    result = aggregator.apply(completed)

    assert result.trace == []
    assert aggregator.text() == "这是最终答复。"


def test_native_agent_aggregator_does_not_reclassify_final_answer_on_completed_message_switch():
    aggregator = NativeAgentAggregator(user_message_id="u-new")

    streamed_final = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "assistant-stream",
        "partID": "final-part",
        "field": "text",
        "delta": "这是最终答复。",
    })
    completed_final = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "properties": {
            "sessionID": "sess-1",
            "info": {
                "id": "assistant-final",
                "role": "assistant",
                "finish": "stop",
                "content": "这是最终答复。",
                "time": {"completed": 1},
            },
        },
    })

    assert streamed_final is not None
    assert completed_final is not None

    assert aggregator.apply(streamed_final).delta == "这是最终答复。"
    result = aggregator.apply(completed_final)

    assert result.trace == []
    assert result.snapshot == "这是最终答复。"
    assert aggregator.text() == "这是最终答复。"


def test_native_agent_aggregator_completes_on_stop_finish_without_completed_time():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    delta = unwrap_event({
        "type": "message.part.delta",
        "sessionID": "sess-1",
        "messageID": "a-final",
        "partID": "p-final",
        "field": "text",
        "delta": "这是最终答复。",
    })
    completed = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "a-final",
            "role": "assistant",
            "finish": "stop",
            "content": "这是最终答复。",
        },
    })

    assert delta is not None
    assert completed is not None

    assert aggregator.apply(delta).delta == "这是最终答复。"
    result = aggregator.apply(completed)

    assert result.done is False
    assert aggregator.assistant_completed is True
    assert aggregator.text() == "这是最终答复。"


@pytest.mark.asyncio
async def test_native_agent_turn_state_completes_on_stop_finish_without_completed_time():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(native_session_id="sess-1", user_message_id="u-new", baseline_message_count=0)

    result = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-new", "role": "user", "content": "继续"},
            {"id": "a-final", "role": "assistant", "finish": "stop", "content": "这是最终答复。"},
        ],
        aggregator,
        now=1.0,
    )

    assert result == {"done": True, "text": "这是最终答复。"}
    assert state.done is True


@pytest.mark.asyncio
async def test_native_agent_turn_state_does_not_complete_from_stable_text_without_final_signal():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(native_session_id="sess-1", user_message_id="u-new", baseline_message_count=0)

    first = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-new", "role": "user", "content": "继续"},
            {"id": "a-preview", "role": "assistant", "content": "处理中"},
        ],
        aggregator,
        now=1.0,
    )
    second = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-new", "role": "user", "content": "继续"},
            {"id": "a-preview", "role": "assistant", "content": "处理中"},
        ],
        aggregator,
        now=2.0,
    )

    assert first == {"done": False, "text": "处理中"}
    assert second == {"done": False, "text": "处理中"}
    assert state.done is False


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


@pytest.mark.asyncio
async def test_native_agent_turn_state_reconcile_ignores_assistant_with_other_parent_id():
    aggregator = NativeAgentAggregator(user_message_id="u-new")
    state = NativeAgentTurnState(
        native_session_id="sess-1",
        user_message_id="u-new",
        baseline_message_count=2,
        baseline_known=True,
    )

    stale_result = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-old", "role": "user", "content": "old"},
            {"id": "a-old", "role": "assistant", "parentID": "u-old", "content": "旧回复", "time": {"completed": 1}},
            {"id": "a-late", "role": "assistant", "parentID": "u-old", "content": "迟到旧回复", "time": {"completed": 2}},
        ],
        aggregator,
        now=1.0,
    )
    current_result = await state.maybe_reconcile(
        lambda _session_id: [
            {"id": "u-old", "role": "user", "content": "old"},
            {"id": "a-old", "role": "assistant", "parentID": "u-old", "content": "旧回复", "time": {"completed": 1}},
            {"id": "u-new", "role": "user", "content": "new"},
            {"id": "a-late", "role": "assistant", "parentID": "u-old", "content": "迟到旧回复", "time": {"completed": 2}},
            {"id": "a-new", "role": "assistant", "parentID": "u-new", "content": "新回复", "time": {"completed": 3}},
        ],
        aggregator,
        now=2.0,
    )

    assert stale_result == {"done": False, "text": ""}
    assert current_result == {"done": True, "text": "新回复"}


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


def test_native_agent_aggregator_reconcile_uses_later_final_assistant_when_message_id_switches():
    aggregator = NativeAgentAggregator(user_message_id="u1")
    completed = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "assistant-1",
            "role": "assistant",
            "content": "OK",
            "finish": "stop",
            "time": {"completed": 1},
        },
    })

    assert completed is not None
    aggregator.apply(completed)
    text = aggregator.reconcile_messages([
        {"id": "u1", "role": "user", "content": "只回复 OK"},
        {"id": "assistant-1", "role": "assistant", "content": "OK", "time": {"completed": 1}},
        {"id": "assistant-2", "role": "assistant", "content": "最终答复", "time": {"completed": 2}},
    ])

    assert text == "最终答复"
    assert aggregator.text() == "最终答复"


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


def test_native_agent_ag_ui_mapper_suppresses_reasoning_and_emits_tool_and_error_outcome():
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
    context_usage = {"session_id": "sess-1", "context_used": 100}
    finished_event = build_run_finished_event(
        state=state,
        completion_state="error",
        content="",
        context_usage=context_usage,
    )

    assert reasoning_types == []
    assert tool_types == [
        core.EventType.TOOL_CALL_START,
        core.EventType.TOOL_CALL_ARGS,
        core.EventType.TOOL_CALL_END,
        core.EventType.TOOL_CALL_RESULT,
    ]
    assert error_event.type == core.EventType.RUN_ERROR
    assert finished_event.outcome.type == "interrupt"
    assert finished_event.result["contextUsage"] == context_usage
    assert finished_event.result["context_usage"] == context_usage


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


def test_native_agent_ag_ui_mapper_suppresses_session_status_noise():
    state = AgUiTurnState(
        thread_id="conv-1",
        run_id="run-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    aggregator = NativeAgentAggregator(user_message_id="user-1")
    event = unwrap_event({"type": "session.status", "sessionID": "sess-1", "status": "处理中"})

    assert event is not None
    mapped = map_ag_ui_event(event=event, result=aggregator.apply(event), state=state)

    assert mapped == []


def test_native_agent_ag_ui_mapper_emits_empty_message_snapshot_for_replace_text():
    state = AgUiTurnState(
        thread_id="conv-1",
        run_id="run-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    event = unwrap_event({
        "type": "message.updated",
        "sessionID": "sess-1",
        "message": {
            "id": "assistant-1",
            "role": "assistant",
            "finish": "tool-calls",
            "content": "先查一下...",
            "time": {"completed": 1},
        },
    })
    assert event is not None
    result = NativeAgentAggregator(user_message_id="user-1").apply(event)
    result.replace_text = True
    result.snapshot = ""

    mapped = map_ag_ui_event(event=event, result=result, state=state)
    snapshot = next(item for item in mapped if item.type == core.EventType.MESSAGES_SNAPSHOT)

    assert snapshot.messages[0].content == ""


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
    from bot.native_agent import config_store
    from bot.native_agent import config_store

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
    from bot.native_agent import config_store

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
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
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
    assert captured_envs[0]["TCB_NATIVE_AGENT_MANAGED"] == "1"
    assert captured_envs[0]["TCB_NATIVE_AGENT_SERVER_KEY"] == first.key
    assert captured_envs[0]["TCB_NATIVE_AGENT_CONFIG_PATH"] == str(first.config_path)
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

    assert changed.config_path.exists() is True
    assert created_processes[0].terminated is True


@pytest.mark.asyncio
async def test_native_agent_server_manager_uses_global_provider_model_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import server_manager as server_manager_module
    from bot.native_agent import config_store

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
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
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


@pytest.mark.asyncio
async def test_native_agent_server_manager_writes_profile_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import config_store
    from bot.native_agent import server_manager as server_manager_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opencode_path = tmp_path / "opencode.json"
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_path))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
    config_store.save_native_agent_config({
        "provider": {
            "jojocode": {
                "models": {
                    "gpt-5.4": {
                        "name": "gpt-5.4",
                        "reasoningEfforts": ["low", "medium", "high"],
                        "options": {"reasoningEffort": "medium"},
                    }
                }
            }
        }
    })

    class FakeProcess:
        returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        return FakeProcess()

    async def fake_health(self):
        return {"ok": True}

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
    monkeypatch.setattr(config, "WORKING_DIR", str(workspace))
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", lambda command, _cwd=None: f"C:/tools/{command}.cmd")
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: [path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    monkeypatch.setattr(manager, "_pick_port", lambda _host: 4101)

    handle = await manager.ensure_started(BotProfile(
        alias="agent-test",
        working_dir=str(workspace),
        supported_execution_modes=["native_agent"],
        default_execution_mode="native_agent",
        native_agent={
            "native_agent_model": "jojocode/gpt-5.4",
            "reasoning_effort": "high",
        },
    ))

    assert handle.config_path is not None
    payload = json.loads(handle.config_path.read_text(encoding="utf-8"))
    assert payload["model"] == "jojocode/gpt-5.4"
    assert payload["provider"]["jojocode"]["models"]["gpt-5.4"]["options"]["reasoningEffort"] == "high"


@pytest.mark.asyncio
async def test_native_agent_server_manager_defaults_reasoning_effort_to_first_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot import config
    from bot.native_agent import config_store
    from bot.native_agent import server_manager as server_manager_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    opencode_path = tmp_path / "opencode.json"
    monkeypatch.setenv("OPENCODE_CONFIG", str(opencode_path))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
    config_store.save_native_agent_config({
        "provider": {
            "jojocode": {
                "models": {
                    "gpt-5.4": {
                        "name": "gpt-5.4",
                        "reasoningEfforts": ["low", "high"],
                    }
                }
            }
        }
    })

    class FakeProcess:
        returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_args, **kwargs):
        return FakeProcess()

    async def fake_health(self):
        return {"ok": True}

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
    monkeypatch.setattr(config, "WORKING_DIR", str(workspace))
    monkeypatch.setattr(server_manager_module, "resolve_cli_executable", lambda command, _cwd=None: f"C:/tools/{command}.cmd")
    monkeypatch.setattr(server_manager_module, "build_executable_invocation", lambda path: [path])
    monkeypatch.setattr(server_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(server_manager_module.NativeAgentClient, "health", fake_health)

    manager = NativeAgentServerManager()
    monkeypatch.setattr(manager, "_pick_port", lambda _host: 4101)

    handle = await manager.ensure_started(BotProfile(
        alias="agent-test",
        working_dir=str(workspace),
        supported_execution_modes=["native_agent"],
        default_execution_mode="native_agent",
        native_agent={"native_agent_model": "jojocode/gpt-5.4"},
    ))

    assert handle.config_path is not None
    payload = json.loads(handle.config_path.read_text(encoding="utf-8"))
    assert payload["provider"]["jojocode"]["models"]["gpt-5.4"]["options"]["reasoningEffort"] == "low"


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
    from bot.native_agent import config_store

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
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
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
    from bot.native_agent import config_store

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
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    monkeypatch.setattr(config_store, "get_app_data_root", lambda: tmp_path / "data")
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
                    "info": {
                        "id": "assistant-1",
                        "role": "assistant",
                        "finish": "stop",
                        "tokens": {"input": 10, "cache": {"read": 20, "write": 3}, "output": 4},
                    },
                    "parts": [
                        {"type": "step-start"},
                        {"type": "reasoning", "text": "internal"},
                        {"type": "text", "text": {"value": "回"}},
                        {"type": "text", "content": "答"},
                        {"type": "step-finish"},
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
            "finish": "stop",
            "tokens": {"input": 10, "cache": {"read": 20, "write": 3}, "output": 4},
            "content": "回答",
            "info": {
                "id": "assistant-1",
                "role": "assistant",
                "finish": "stop",
                "tokens": {"input": 10, "cache": {"read": 20, "write": 3}, "output": 4},
            },
            "parts": [
                {"type": "step-start"},
                {"type": "reasoning", "text": "internal"},
                {"type": "text", "text": {"value": "回"}},
                {"type": "text", "content": "答"},
                {"type": "step-finish"},
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


class FakeRunProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9


class FakeRunClient:
    def __init__(
        self,
        events: list[dict[str, object]] | None = None,
        *,
        error: BaseException | None = None,
        export_messages: list[dict[str, object]] | None = None,
        gate: asyncio.Event | None = None,
        started: asyncio.Event | None = None,
    ) -> None:
        self.events = list(events or [])
        self.error = error
        self.export_messages = list(export_messages or [])
        self.requests: list[NativeAgentRunRequest] = []
        self.export_requests: list[object] = []
        self.process = FakeRunProcess()
        self.killed = False
        self.gate = gate
        self.started = started

    async def stream(self, request: NativeAgentRunRequest):
        self.requests.append(request)
        if request.on_process is not None:
            request.on_process(self.process)
        if self.started is not None:
            self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        for event in self.events:
            await asyncio.sleep(0)
            yield event

    async def export_session(self, request):
        self.export_requests.append(request)
        return self.export_messages

    def kill(self) -> None:
        self.killed = True
        self.process.terminate()


@pytest.mark.asyncio
async def test_native_agent_service_streams_opencode_run_and_persists_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    fake_client = FakeRunClient([
        {"type": "text", "sessionID": "sess-1", "part": {"id": "p1", "type": "text", "text": "回"}},
        {"type": "text", "sessionID": "sess-1", "part": {"id": "p1", "type": "text", "text": "答"}},
        {"type": "step_finish", "sessionID": "sess-1"},
    ])
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
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
    assert done["native_session_id"] == "sess-1"
    assert done["message"]["meta"]["native_source"]["provider"] == "native_agent"
    assert session.native_agent_session_id == "sess-1"
    assert session.is_processing is False
    assert fake_client.requests[0].session_id == ""
    assert fake_client.requests[0].prompt == "你好"


@pytest.mark.asyncio
async def test_native_agent_service_reuses_bound_run_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    fake_client = FakeRunClient([
        {"type": "text", "sessionID": "sess-old", "part": {"id": "p1", "type": "text", "text": "继续"}},
        {"type": "step_finish", "sessionID": "sess-old"},
    ])
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))
    old_handle = history.start_turn(profile=profile, session=session, user_text="旧问题", native_provider="native_agent")
    history.complete_turn(old_handle, content="旧回复", completion_state="completed", native_session_id="sess-old")
    history.store.set_conversation_native_session(
        old_handle.conversation_id,
        "sess-old",
        {"cwd": str(tmp_path), "model_id": "", "opencode_agent": ""},
    )

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="继续",
            prompt_text="继续",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "继续"
    assert fake_client.requests[0].session_id == "sess-old"
    assert fake_client.requests[0].prompt == "继续"


@pytest.mark.asyncio
async def test_native_agent_service_retries_once_when_run_session_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    first = FakeRunClient(error=NativeAgentRunError("session not found", returncode=1, stderr="session not found"))
    second = FakeRunClient([
        {"type": "text", "sessionID": "sess-new", "part": {"id": "p1", "type": "text", "text": "新回复"}},
        {"type": "step_finish", "sessionID": "sess-new"},
    ])
    clients = [first, second]
    service = NativeAgentService()
    service._run_client_factory = lambda: clients.pop(0)
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))
    old_handle = history.start_turn(profile=profile, session=session, user_text="旧问题", native_provider="native_agent")
    history.complete_turn(old_handle, content="旧回复", completion_state="completed", native_session_id="sess-old")
    history.store.set_conversation_native_session(
        old_handle.conversation_id,
        "sess-old",
        {"cwd": str(tmp_path), "model_id": "", "opencode_agent": ""},
    )

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="继续",
            prompt_text="继续",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["native_session_id"] == "sess-new"
    assert first.requests[0].session_id == "sess-old"
    assert second.requests[0].session_id == ""
    assert "旧回复" in second.requests[0].prompt
    assert session.native_agent_session_id == "sess-new"


@pytest.mark.asyncio
async def test_native_agent_service_context_usage_from_step_finish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    fake_client = FakeRunClient([
        {"type": "text", "sessionID": "sess-1", "part": {"id": "p1", "type": "text", "text": "完成"}},
        {"type": "step_finish", "sessionID": "sess-1", "tokens": {"input": 10, "cache": {"read": 2, "write": 3}, "output": 4}, "cost": 0.05},
    ])
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="做事",
            prompt_text="做事",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["context_usage"]["source"] == "native_agent_run_tokens"
    assert done["context_usage"]["used_tokens"] == 15
    assert done["context_usage"]["output_tokens"] == 4
    assert done["context_usage"]["cost"] == 0.05


@pytest.mark.asyncio
async def test_native_agent_service_permission_event_fails_in_run_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    fake_client = FakeRunClient([
        {"type": "permission", "sessionID": "sess-1", "permission": {"id": "perm-1", "title": "允许执行？"}},
    ])
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="执行",
            prompt_text="执行",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["returncode"] == 1
    assert done["message"]["state"] == "error"
    assert "权限" in done["output"]


@pytest.mark.asyncio
async def test_native_agent_service_abort_terminates_local_run_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    started = asyncio.Event()
    gate = asyncio.Event()
    fake_client = FakeRunClient(gate=gate, started=started)
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    task = asyncio.create_task(_collect_native_stream(service.stream_chat(
        profile=profile,
        session=session,
        user_text="停下",
        prompt_text="停下",
        history_service=history,
    )))
    await asyncio.wait_for(started.wait(), timeout=1)

    aborted = await service.abort(session)
    gate.set()
    events = await asyncio.wait_for(task, timeout=2)

    done = next(event for event in events if event["type"] == "done")
    assert aborted is True
    assert fake_client.process.terminated is True
    assert done["message"]["state"] == "error"
    assert done["message"]["meta"]["completion_state"] == "cancelled"
    assert session.process is None


@pytest.mark.asyncio
async def test_native_agent_service_persists_turn_when_run_start_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    fake_client = FakeRunClient(error=NativeAgentRunError("run failed", returncode=2, stderr="run failed"))
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
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

    error = next(event for event in events if event["type"] == "error")
    assert "run failed" in error["message"]
    messages = history.list_history(profile, session)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["state"] == "error"
    assert "run failed" in messages[1]["content"]


@pytest.mark.asyncio
async def test_native_agent_service_run_chat_clears_flags_before_return(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot import config

    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    fake_client = FakeRunClient([
        {"type": "text", "sessionID": "sess-1", "part": {"id": "p1", "type": "text", "text": "完成"}},
        {"type": "step_finish", "sessionID": "sess-1"},
    ])
    service = NativeAgentService()
    service._run_client_factory = lambda: fake_client
    profile = BotProfile(alias="main", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    result = await service.run_chat(
        profile=profile,
        session=session,
        user_text="你好",
        prompt_text="你好",
        history_service=history,
    )

    assert result["output"] == "完成"
    assert session.is_processing is False
    assert session.native_agent_run_id is None
    assert session.native_agent_server_key is None
    assert session.stop_requested is False
