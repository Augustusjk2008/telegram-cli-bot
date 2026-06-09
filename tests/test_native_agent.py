from __future__ import annotations

import asyncio
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
            await asyncio.sleep(0.05)
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
async def test_native_agent_service_run_chat_clears_flags_before_return(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
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
            await asyncio.sleep(0.05)
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
            cluster_run_id="clr_123",
        )
    ]

    meta = next(item for item in events if item["type"] == "meta")
    ag_ui_events = [event_adapter.validate_python(item["event"]) for item in events if item["type"] == "ag_ui"]
    ag_ui_types = [event.type for event in ag_ui_events]
    done = next(event for event in events if event["type"] == "done")

    assert meta["cluster_run_id"] == "clr_123"
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
async def test_native_agent_service_completes_from_stop_finish_without_idle(tmp_path: Path):
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
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-1",
                    "partID": "answer",
                    "field": "text",
                    "delta": "不能确认上轮实际调用次数。",
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
                {"id": self.prompt_message_id, "role": "user", "content": "你上轮对话是调用了一次还是两次"},
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "不能确认上轮实际调用次数。",
                },
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
    profile = BotProfile(alias="agent-test", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="agent-test", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = await asyncio.wait_for(
        _collect_native_stream(
            service.stream_chat(
                profile=profile,
                session=session,
                user_text="你上轮对话是调用了一次还是两次",
                prompt_text="你上轮对话是调用了一次还是两次",
                history_service=history,
            )
        ),
        timeout=3,
    )

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "不能确认上轮实际调用次数。"
    assert done["message"]["meta"]["completion_state"] == "completed"
    assert fake_client.list_calls >= 1
    assert fake_client.cancelled is True


@pytest.mark.asyncio
async def test_native_agent_service_finalizes_completed_answer_before_duplicate_loop(tmp_path: Path):
    blocker = asyncio.Event()

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.cancelled = False
            self.abort_calls: list[str] = []
            self.prompt_message_id = ""
            self.completed_emitted = 0

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            self.prompt_message_id = str(message_id or "")
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            for index, text in enumerate(["第一次完整答复。", "第二次重复答复。", "第三次重复答复。"], start=1):
                message_id = f"assistant-{index}"
                yield {
                    "directory": str(tmp_path),
                    "payload": {
                        "type": "message.part.delta",
                        "sessionID": "sess-1",
                        "messageID": message_id,
                        "partID": f"text-{index}",
                        "field": "text",
                        "delta": text,
                    },
                }
                self.completed_emitted = index
                yield {
                    "directory": str(tmp_path),
                    "payload": {
                        "type": "message.updated",
                        "sessionID": "sess-1",
                        "message": {
                            "id": message_id,
                            "role": "assistant",
                            "finish": "stop",
                            "content": text,
                            "time": {"completed": index},
                        },
                    },
                }
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        async def list_messages(self, session_id):
            completed_messages = [
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "第一次完整答复。",
                    "time": {"completed": 1},
                },
                {
                    "id": "assistant-2",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "第二次重复答复。",
                    "time": {"completed": 2},
                },
                {
                    "id": "assistant-3",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "第三次重复答复。",
                    "time": {"completed": 3},
                },
            ]
            return [
                {"id": self.prompt_message_id, "role": "user", "content": "你上轮对话是调用了一次还是两次"},
                *completed_messages[: self.completed_emitted],
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
    profile = BotProfile(alias="agent-test", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="agent-test", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = await asyncio.wait_for(
        _collect_native_stream(
            service.stream_chat(
                profile=profile,
                session=session,
                user_text="你上轮对话是调用了一次还是两次",
                prompt_text="你上轮对话是调用了一次还是两次",
                history_service=history,
            )
        ),
        timeout=1.5,
    )

    done = next(event for event in events if event["type"] == "done")
    assert [event["type"] for event in events].count("done") == 1
    assert done["output"] == "第二次重复答复。"
    assert done["message"]["meta"]["completion_state"] == "completed"
    assert fake_client.cancelled is True
    assert fake_client.abort_calls == ["sess-1"]
    assert session.is_processing is False
    assert session.native_agent_run_id is None


@pytest.mark.asyncio
async def test_native_agent_service_finishes_after_tool_followup_repeated_completed_without_idle(tmp_path: Path):
    blocker = asyncio.Event()
    event_adapter = TypeAdapter(core.Event)

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.cancelled = False
            self.abort_calls: list[str] = []
            self.prompt_message_id = ""
            self.completed_emitted = 0

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            self.prompt_message_id = str(message_id or "")
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-tool",
                    "partID": "preview",
                    "field": "text",
                    "delta": "先检查。",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-tool",
                        "role": "assistant",
                        "finish": "tool-calls",
                        "content": "先检查。",
                        "time": {"completed": 1},
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {
                        "id": "tool-1",
                        "type": "tool",
                        "tool": "shell_command",
                        "output": "Exit code: 0",
                        "state": "completed",
                    },
                },
            }
            for index in (1, 2):
                message_id = f"assistant-final-{index}"
                yield {
                    "directory": str(tmp_path),
                    "payload": {
                        "type": "message.part.delta",
                        "sessionID": "sess-1",
                        "messageID": message_id,
                        "partID": f"final-{index}",
                        "field": "text",
                        "delta": "最终答复。",
                    },
                }
                self.completed_emitted = index
                yield {
                    "directory": str(tmp_path),
                    "payload": {
                        "type": "message.updated",
                        "sessionID": "sess-1",
                        "message": {
                            "id": message_id,
                            "role": "assistant",
                            "finish": "stop",
                            "content": "最终答复。",
                            "time": {"completed": index + 1},
                        },
                    },
                }
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        async def list_messages(self, session_id):
            final_messages = [
                {
                    "id": "assistant-final-1",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "最终答复。",
                    "time": {"completed": 2},
                },
                {
                    "id": "assistant-final-2",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "最终答复。",
                    "time": {"completed": 3},
                },
            ]
            return [
                {"id": self.prompt_message_id, "role": "user", "content": "需要工具后总结"},
                {
                    "id": "assistant-tool",
                    "role": "assistant",
                    "finish": "tool-calls",
                    "content": "先检查。",
                    "time": {"completed": 1},
                },
                *final_messages[: self.completed_emitted],
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
    profile = BotProfile(alias="agent-test", working_dir=str(tmp_path))
    session = UserSession(bot_id=1, bot_alias="agent-test", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))

    events = await asyncio.wait_for(
        _collect_native_stream(
            service.stream_chat(
                profile=profile,
                session=session,
                user_text="需要工具后总结",
                prompt_text="需要工具后总结",
                history_service=history,
                protocol="ag-ui",
            )
        ),
        timeout=1.5,
    )

    done = next(event for event in events if event["type"] == "done")
    ag_ui_types = [event_adapter.validate_python(item["event"]).type for item in events if item["type"] == "ag_ui"]
    assert [event["type"] for event in events].count("done") == 1
    assert done["output"] == "最终答复。"
    assert done["message"]["meta"]["completion_state"] == "completed"
    assert ag_ui_types[-1] == core.EventType.RUN_FINISHED
    assert fake_client.abort_calls == ["sess-1"]
    assert fake_client.cancelled is True
    assert session.is_processing is False
    assert session.native_agent_run_id is None


@pytest.mark.asyncio
async def test_native_agent_service_waits_for_final_assistant_id_switch_without_abort(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.abort_calls: list[str] = []
            self.idle_seen = False
            self.reader_cancelled = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-1",
                    "partID": "part-text",
                    "field": "text",
                    "delta": "OK",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-1",
                        "role": "assistant",
                        "finish": "stop",
                        "time": {"completed": 1},
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-2",
                        "role": "assistant",
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-2",
                    "partID": "part-text-2",
                    "field": "text",
                    "delta": "后续半截",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-2",
                    "partID": "part-text-2",
                    "field": "text",
                    "delta": "最终",
                },
            }
            self.idle_seen = True
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            messages = [
                {"id": "user-1", "role": "user", "content": "只回复 OK"},
                {"id": "assistant-1", "role": "assistant", "content": "OK", "time": {"completed": 1}},
            ]
            if self.idle_seen:
                messages.append({"id": "assistant-2", "role": "assistant", "content": "最终", "time": {"completed": 2}})
            return messages

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
            user_text="只回复 OK",
            prompt_text="只回复 OK",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "最终"
    assert done["message"]["content"] == "最终"
    messages = history.list_history(profile, session)
    assert messages[-1]["content"] == "最终"
    assert fake_client.abort_calls == []
    assert fake_client.idle_seen is True


@pytest.mark.asyncio
async def test_native_agent_service_marks_tool_failure_as_error(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.abort_calls: list[str] = []

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

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
                    "part": {
                        "id": "tool-1",
                        "type": "tool",
                        "tool": "shell_command",
                        "arguments": {"command": "bad-command"},
                        "error": "command not found",
                        "state": "failed",
                    },
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [
                {"id": "user-1", "role": "user", "content": "运行命令"},
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": "",
                    "time": {"completed": 1},
                },
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

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="运行命令",
            prompt_text="运行命令",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    messages = history.list_history(profile, session)

    assert done["returncode"] == 1
    assert done["message"]["state"] == "error"
    assert done["message"]["meta"]["completion_state"] == "error"
    assert done["message"]["content"] == "command not found"
    assert messages[-1]["content"] == "command not found"
    assert fake_client.abort_calls == []


@pytest.mark.asyncio
async def test_native_agent_service_preserves_commentary_on_tool_failure(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.abort_calls: list[str] = []

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-tool",
                    "partID": "preview",
                    "field": "text",
                    "delta": "先运行命令。",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-tool",
                        "role": "assistant",
                        "finish": "tool-calls",
                        "content": "先运行命令。",
                        "time": {"completed": 1},
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": "sess-1",
                    "part": {
                        "id": "tool-1",
                        "type": "tool",
                        "tool": "shell_command",
                        "arguments": {"command": "bad-command"},
                        "error": "command not found",
                        "state": "failed",
                    },
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [
                {"id": "user-1", "role": "user", "content": "运行命令"},
                {
                    "id": "assistant-tool",
                    "role": "assistant",
                    "finish": "tool-calls",
                    "content": "先运行命令。",
                    "time": {"completed": 1},
                },
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

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="运行命令",
            prompt_text="运行命令",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    trace = history.get_message_trace(profile, session, done["message"]["id"])

    assert done["returncode"] == 1
    assert done["message"]["state"] == "error"
    assert done["message"]["content"] == "command not found"
    assert trace is not None
    assert [item["kind"] for item in trace["trace"]] == ["commentary", "tool_call", "tool_result"]
    assert trace["trace"][0]["summary"] == "先运行命令。"
    assert trace["process_count"] == 1
    assert fake_client.abort_calls == []


@pytest.mark.asyncio
async def test_native_agent_service_persists_commentary_tool_and_result_trace(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
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
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-tool",
                    "partID": "preview",
                    "field": "text",
                    "delta": "先检查目录结构。",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-tool",
                        "role": "assistant",
                        "finish": "tool-calls",
                        "content": "先检查目录结构。",
                        "time": {"completed": 1},
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
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
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-final",
                    "partID": "final",
                    "field": "text",
                    "delta": "这是最终答复。",
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-1"}}

        async def list_messages(self, session_id):
            return [
                {"id": "user-1", "role": "user", "content": "看项目"},
                {
                    "id": "assistant-tool",
                    "role": "assistant",
                    "finish": "tool-calls",
                    "content": "先检查目录结构。",
                    "time": {"completed": 1},
                },
                {
                    "id": "assistant-final",
                    "role": "assistant",
                    "finish": "stop",
                    "content": "这是最终答复。",
                    "time": {"completed": 2},
                    "parts": [{"type": "text", "text": "这是最终答复。"}],
                },
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

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="看项目",
            prompt_text="看项目",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    trace = history.get_message_trace(profile, session, done["message"]["id"])

    assert done["message"]["content"] == "这是最终答复。"
    assert done["message"]["meta"]["process_count"] == 1
    assert trace is not None
    assert [item["kind"] for item in trace["trace"]] == ["commentary", "tool_call", "tool_result"]
    assert trace["trace"][0]["summary"] == "先检查目录结构。"
    assert trace["process_count"] == 1


@pytest.mark.asyncio
async def test_native_agent_service_user_cancel_aborts_and_persists_cancelled(tmp_path: Path):
    blocker = asyncio.Event()
    cancel_ready = asyncio.Event()

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.abort_calls: list[str] = []

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-1",
                    "partID": "text-1",
                    "field": "text",
                    "delta": "先检查目录结构。",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-1",
                        "role": "assistant",
                        "finish": "tool-calls",
                        "content": "先检查目录结构。",
                        "time": {"completed": 1},
                    },
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-2",
                    "partID": "text-2",
                    "field": "text",
                    "delta": "半截",
                },
            }
            await asyncio.sleep(0.05)
            cancel_ready.set()
            await asyncio.sleep(0.05)
            yield {"directory": str(tmp_path), "payload": {"type": "session.status", "sessionID": "sess-1", "status": "取消中"}}
            await blocker.wait()

        async def list_messages(self, session_id):
            return [
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "finish": "tool-calls",
                    "content": "先检查目录结构。",
                    "time": {"completed": 1},
                },
                {"id": "assistant-2", "role": "assistant", "content": "半截"},
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

    async def request_cancel() -> None:
        while not fake_client.prompt_called:
            await asyncio.sleep(0)
        await cancel_ready.wait()
        with session._lock:
            session.stop_requested = True

    cancel_task = asyncio.create_task(request_cancel())
    try:
        events = await asyncio.wait_for(
            _collect_native_stream(
                service.stream_chat(
                    profile=profile,
                    session=session,
                    user_text="继续写",
                    prompt_text="继续写",
                    history_service=history,
                )
            ),
            timeout=3,
        )
    finally:
        blocker.set()
        await cancel_task

    done = next(event for event in events if event["type"] == "done")
    messages = history.list_history(profile, session)
    trace = history.get_message_trace(profile, session, done["message"]["id"])

    assert done["returncode"] == 0
    assert done["message"]["state"] == "error"
    assert done["message"]["meta"]["completion_state"] == "cancelled"
    assert done["message"]["content"] == "半截"
    assert messages[-1]["meta"]["completion_state"] == "cancelled"
    assert trace is not None
    assert [item["kind"] for item in trace["trace"][:1]] == ["commentary"]
    assert trace["trace"][-1]["kind"] == "cancelled"
    assert fake_client.abort_calls == ["sess-1"]


@pytest.mark.asyncio
async def test_native_agent_service_abort_and_list_messages_have_local_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(native_service_module, "LIST_MESSAGES_TIMEOUT_SECONDS", 0.005)
    monkeypatch.setattr(native_service_module, "ABORT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(native_service_module, "FINAL_CANDIDATE_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(native_service_module, "FINAL_CANDIDATE_MAX_SECONDS", 0.02)

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.list_calls = 0
            self.abort_calls: list[str] = []
            self.abort_cancelled = False
            self.reader_cancelled = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.abort_cancelled = True
                raise

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.delta",
                    "sessionID": "sess-1",
                    "messageID": "assistant-1",
                    "partID": "answer",
                    "field": "text",
                    "delta": "OK",
                },
            }
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.updated",
                    "sessionID": "sess-1",
                    "message": {
                        "id": "assistant-1",
                        "role": "assistant",
                        "finish": "stop",
                        "content": "OK",
                        "time": {"completed": 1},
                    },
                },
            }
            try:
                while True:
                    await asyncio.sleep(0.002)
                    yield {"directory": str(tmp_path), "payload": {"type": "session.status", "sessionID": "sess-1", "status": "仍在生成"}}
            except asyncio.CancelledError:
                self.reader_cancelled = True
                raise

        async def list_messages(self, session_id):
            self.list_calls += 1
            await asyncio.Event().wait()
            return []

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
                user_text="只回复 OK",
                prompt_text="只回复 OK",
                history_service=history,
            )
        ),
        timeout=1,
    )

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "OK"
    assert done["message"]["meta"]["completion_state"] == "completed"
    assert fake_client.list_calls >= 1
    assert fake_client.abort_calls == ["sess-1"]
    assert fake_client.abort_cancelled is True
    assert fake_client.reader_cancelled is True
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_native_agent_service_marks_no_progress_stream_as_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(native_service_module, "LIST_MESSAGES_TIMEOUT_SECONDS", 0.005)
    monkeypatch.setattr(native_service_module, "ABORT_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(native_service_module, "NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS", 0.03, raising=False)

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.abort_calls: list[str] = []
            self.reader_cancelled = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def abort(self, session_id):
            self.abort_calls.append(session_id)
            return True

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            try:
                while True:
                    await asyncio.sleep(0.002)
                    yield {
                        "directory": str(tmp_path),
                        "payload": {
                            "type": "file.watcher.updated",
                            "sessionID": "sess-1",
                            "path": "generated.tmp",
                        },
                    }
            except asyncio.CancelledError:
                self.reader_cancelled = True
                raise

        async def list_messages(self, session_id):
            return []

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
                user_text="生成文件",
                prompt_text="生成文件",
                history_service=history,
            )
        ),
        timeout=1,
    )

    done = next(event for event in events if event["type"] == "done")
    trace_events = [event for event in events if event["type"] == "trace"]
    assert trace_events == []
    assert done["returncode"] == 1
    assert done["message"]["state"] == "error"
    assert done["message"]["meta"]["completion_state"] == "error"
    assert "长时间无输出" in done["output"]
    assert fake_client.abort_calls == ["sess-1"]
    assert fake_client.reader_cancelled is True
    assert session.is_processing is False


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
async def test_native_agent_service_event_ready_has_local_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(native_service_module, "EVENT_READY_TIMEOUT_SECONDS", 0.005)

    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.reader_cancelled = False

        async def create_session(self, *, cwd=None):
            return {"id": "sess-1"}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.reader_cancelled = True
                raise
            if False:
                yield {}

        async def list_messages(self, session_id):
            return []

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
        timeout=1,
    )

    assert events[-1] == {
        "type": "error",
        "code": "native_agent_error",
        "message": "原生 agent 执行失败: 原生 agent 事件流准备超时",
    }
    assert fake_client.prompt_called is False
    assert fake_client.reader_cancelled is True
    assert session.is_processing is False


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
            if session_id == "sess-old":
                return {"id": "sess-old", "directory": str(old_dir)}
            return {"id": session_id, "directory": str(new_dir)}

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
async def test_native_agent_service_recreates_session_when_persisted_session_ends_with_user_message(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.prompt_session_id = ""

        async def get_session(self, session_id):
            return {"id": session_id, "directory": str(tmp_path)}

        async def create_session(self, *, cwd=None):
            assert cwd == str(tmp_path)
            return {"id": "sess-new", "directory": str(tmp_path)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_session_id = session_id
            assert session_id == "sess-new"
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
                    "sessionID": "sess-new",
                    "part": {
                        "id": "part-assistant",
                        "type": "text",
                        "delta": "OK",
                        "messageID": "msg-assistant",
                    },
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-new"}}

        async def list_messages(self, session_id):
            if session_id == "sess-old":
                return [{"id": "user-old", "role": "user", "content": "未回答"}]
            assert session_id == "sess-new"
            return [{"id": "msg-assistant", "role": "assistant", "content": "OK"}]

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
            user_text="回复ok",
            prompt_text="回复ok",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "OK"
    assert session.native_agent_session_id == "sess-new"
    assert fake_client.prompt_session_id == "sess-new"


@pytest.mark.asyncio
async def test_native_agent_service_uses_fresh_native_session_with_web_history(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.created_count = 0
            self.prompt_sessions: list[str] = []
            self.prompt_texts: list[str] = []

        async def get_session(self, session_id):
            return {"id": session_id, "directory": str(tmp_path)}

        async def create_session(self, *, cwd=None):
            assert cwd == str(tmp_path)
            self.prompt_called = False
            self.created_count += 1
            return {"id": f"sess-new-{self.created_count}", "directory": str(tmp_path)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_sessions.append(session_id)
            self.prompt_texts.append(text)
            self.prompt_called = True
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while not self.prompt_called:
                await asyncio.sleep(0)
            session_id = self.prompt_sessions[-1]
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": session_id,
                    "part": {
                        "id": "part-assistant",
                        "type": "text",
                        "delta": session_id,
                        "messageID": f"msg-{session_id}",
                    },
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": session_id}}

        async def list_messages(self, session_id):
            return [{"id": f"msg-{session_id}", "role": "assistant", "content": session_id}]

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
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        working_dir=str(tmp_path),
    )
    history = ChatHistoryService(ChatStore(tmp_path))

    error_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="失败问题",
        native_provider="native_agent",
    )
    history.complete_turn(
        error_handle,
        content="半截错误",
        completion_state="error",
        native_session_id="sess-error",
    )

    first = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="1",
            prompt_text="1",
            history_service=history,
        )
    ]
    second = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="2",
            prompt_text="2",
            history_service=history,
        )
    ]

    assert next(event for event in first if event["type"] == "done")["output"] == "sess-new-1"
    assert next(event for event in second if event["type"] == "done")["output"] == "sess-new-2"
    assert fake_client.created_count == 2
    assert fake_client.prompt_sessions == ["sess-new-1", "sess-new-2"]
    assert fake_client.prompt_texts[0] == "1"
    assert "失败问题" not in fake_client.prompt_texts[0]
    assert "半截错误" not in fake_client.prompt_texts[0]
    assert "用户: 1" in fake_client.prompt_texts[1]
    assert "助手: sess-new-1" in fake_client.prompt_texts[1]
    assert "半截错误" not in fake_client.prompt_texts[1]
    assert fake_client.prompt_texts[1].endswith("2")


@pytest.mark.asyncio
async def test_native_agent_service_reuses_native_session_for_three_completed_turns(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.create_count = 0
            self.prompt_count = 0
            self.event_count = 0
            self.prompt_sessions: list[str] = []
            self.prompt_texts: list[str] = []
            self.messages_by_session: dict[str, list[dict[str, object]]] = {}

        async def get_session(self, session_id):
            return {"id": session_id, "directory": str(tmp_path)}

        async def create_session(self, *, cwd=None):
            assert cwd == str(tmp_path)
            self.create_count += 1
            session_id = "sess-1"
            self.messages_by_session.setdefault(session_id, [])
            return {"id": session_id, "directory": str(tmp_path)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_count += 1
            self.prompt_sessions.append(session_id)
            self.prompt_texts.append(text)
            self.messages_by_session.setdefault(session_id, []).append({
                "id": f"a-{self.prompt_count}",
                "role": "assistant",
                "content": f"答{self.prompt_count}",
                "finish": "stop",
                "time": {"completed": self.prompt_count},
            })
            return {}

        async def events(self, *, global_events=True, ready_event=None):
            if ready_event is not None:
                ready_event.set()
            while self.event_count >= self.prompt_count:
                await asyncio.sleep(0)
            index = self.event_count
            self.event_count += 1
            session_id = self.prompt_sessions[index]
            text = str(self.messages_by_session[session_id][-1]["content"])
            yield {
                "directory": str(tmp_path),
                "payload": {
                    "type": "message.part.updated",
                    "sessionID": session_id,
                    "part": {"id": f"p-{index}", "type": "text", "delta": text, "messageID": f"a-{index + 1}"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": session_id}}

        async def list_messages(self, session_id):
            return list(self.messages_by_session.get(session_id, []))

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

    outputs = []
    for text in ["1", "2", "3"]:
        events = [
            event async for event in service.stream_chat(
                profile=profile,
                session=session,
                user_text=text,
                prompt_text=text,
                history_service=history,
            )
        ]
        outputs.append(next(event for event in events if event["type"] == "done")["output"])

    assert outputs == ["答1", "答2", "答3"]
    assert fake_client.create_count == 1
    assert fake_client.prompt_sessions == ["sess-1", "sess-1", "sess-1"]
    assert fake_client.prompt_texts == ["1", "2", "3"]
    assert ChatStore(tmp_path).get_conversation_native_session(str(session.active_conversation_id))["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_native_agent_service_recreates_session_when_model_or_agent_changes(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.created_count = 0
            self.prompt_payload: tuple[str, str, str] | None = None

        async def get_session(self, session_id):
            return {"id": session_id, "directory": str(tmp_path)}

        async def create_session(self, *, cwd=None):
            self.created_count += 1
            return {"id": "sess-new", "directory": str(tmp_path)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_payload = (session_id, str(model or ""), str(agent or ""))
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
                    "sessionID": "sess-new",
                    "part": {"id": "p-new", "type": "text", "delta": "新配置"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-new"}}

        async def list_messages(self, session_id):
            return [{"id": "a-new", "role": "assistant", "content": "新配置", "finish": "stop", "time": {"completed": 1}}]

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
        native_agent={"native_agent_model": "anthropic/new-model", "opencode_agent": "writer"},
    )
    session = UserSession(bot_id=1, bot_alias="main", user_id=1001, working_dir=str(tmp_path))
    history = ChatHistoryService(ChatStore(tmp_path))
    old_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="旧问题",
        native_provider="native_agent",
    )
    history.complete_turn(old_handle, content="旧回复", completion_state="completed", native_session_id="sess-old")
    ChatStore(tmp_path).set_conversation_native_session(
        old_handle.conversation_id,
        "sess-old",
        {"cwd": str(tmp_path), "model_id": "anthropic/old-model", "opencode_agent": "reviewer"},
    )

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="新问题",
            prompt_text="新问题",
            history_service=history,
        )
    ]

    assert next(event for event in events if event["type"] == "done")["output"] == "新配置"
    assert fake_client.created_count == 1
    assert fake_client.prompt_payload == ("sess-new", "anthropic/new-model", "writer")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_payload", "old_messages"),
    [
        ({}, [{"id": "a-tool", "role": "assistant", "content": "工具中", "finish": "tool-calls", "time": {"completed": 1}}]),
        ({}, [{"id": "a-cancel", "role": "assistant", "content": "取消", "status": "cancelled"}]),
        ({"permissions": [{"id": "perm-1", "status": "pending"}]}, [{"id": "a-ok", "role": "assistant", "content": "OK", "finish": "stop", "time": {"completed": 1}}]),
        ({}, [{"id": "a-open", "role": "assistant", "content": "未完成"}]),
    ],
)
async def test_native_agent_service_recreates_unhealthy_persisted_session(
    tmp_path: Path,
    old_payload: dict[str, object],
    old_messages: list[dict[str, object]],
):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.created_count = 0
            self.prompt_session_id = ""

        async def get_session(self, session_id):
            payload = dict(old_payload) if session_id == "sess-old" else {}
            payload.update({"id": session_id, "directory": str(tmp_path)})
            return payload

        async def create_session(self, *, cwd=None):
            self.created_count += 1
            return {"id": "sess-new", "directory": str(tmp_path)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_session_id = session_id
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
                    "sessionID": "sess-new",
                    "part": {"id": "p-new", "type": "text", "delta": "恢复"},
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-new"}}

        async def list_messages(self, session_id):
            if session_id == "sess-old":
                return old_messages
            return [{"id": "a-new", "role": "assistant", "content": "恢复", "finish": "stop", "time": {"completed": 1}}]

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
    old_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="旧问题",
        native_provider="native_agent",
    )
    history.complete_turn(old_handle, content="旧回复", completion_state="completed", native_session_id="sess-old")

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="继续",
            prompt_text="继续",
            history_service=history,
        )
    ]

    assert next(event for event in events if event["type"] == "done")["output"] == "恢复"
    assert fake_client.created_count == 1
    assert fake_client.prompt_session_id == "sess-new"


@pytest.mark.asyncio
async def test_native_agent_service_recreates_persisted_session_that_ends_with_user_message(tmp_path: Path):
    class FakeClient:
        def __init__(self) -> None:
            self.prompt_called = False
            self.created_count = 0
            self.prompt_sessions: list[str] = []

        async def get_session(self, session_id):
            return {"id": session_id, "directory": str(tmp_path)}

        async def create_session(self, *, cwd=None):
            assert cwd == str(tmp_path)
            self.created_count += 1
            return {"id": "sess-new", "directory": str(tmp_path)}

        async def prompt_async(self, session_id, text, *, message_id=None, model=None, agent=None):
            self.prompt_sessions.append(session_id)
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
                    "sessionID": "sess-new",
                    "part": {
                        "id": "part-assistant",
                        "type": "text",
                        "delta": "恢复",
                        "messageID": "msg-sess-new",
                    },
                },
            }
            yield {"directory": str(tmp_path), "payload": {"type": "session.idle", "sessionID": "sess-new"}}

        async def list_messages(self, session_id):
            if session_id == "sess-old":
                return [{"id": "user-old", "role": "user", "content": "未回答"}]
            return [{"id": "msg-sess-new", "role": "assistant", "content": "恢复", "time": {"completed": 1}}]

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

    old_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="旧问题",
        native_provider="native_agent",
    )
    history.complete_turn(
        old_handle,
        content="旧回复",
        completion_state="completed",
        native_session_id="sess-old",
    )

    events = [
        event async for event in service.stream_chat(
            profile=profile,
            session=session,
            user_text="新问题",
            prompt_text="新问题",
            history_service=history,
        )
    ]

    done = next(event for event in events if event["type"] == "done")
    assert done["output"] == "恢复"
    assert session.native_agent_session_id == "sess-new"
    assert fake_client.created_count == 1
    assert fake_client.prompt_sessions == ["sess-new"]


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
