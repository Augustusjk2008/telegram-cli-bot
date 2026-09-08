from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import config
from bot.models import BotProfile, UserSession
from bot.native_agent import service as native_service
from bot.native_agent.pi_rpc_client import PiRpcRunError
from bot.native_agent.service import NativeAgentService
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


@pytest.fixture
def pi_chat(tmp_path, monkeypatch):
    prices = tmp_path / "prices.csv"
    prices.write_text(
        "model,currency,input_per_million,cache_read_per_million,cache_write_per_million,output_per_million\n"
        "test-model,USD,2,0.2,2.5,10\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MODEL_PRICES_FILE", str(prices))
    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(native_service, "run_pi_windows_preflight", lambda _: {"ok": True})
    monkeypatch.setattr(native_service, "effective_native_agent_config", lambda _: {"workspace_history_enabled": False})
    monkeypatch.setattr("bot.native_agent.context_usage.find_configured_model", lambda _: None)
    service = NativeAgentService()
    monkeypatch.setattr(service, "_ensure_runtime_eviction_task", lambda: None)
    monkeypatch.setattr(service, "_pi_runtime_env", lambda _: {})
    monkeypatch.setattr(service, "_runtime_config_fingerprint", lambda: "")
    monkeypatch.setattr(service, "_prompt_options", lambda _: ("provider/test-model", "", "", ""))
    monkeypatch.setattr(service, "_append_system_prompt", lambda *a, **kw: ("", ""))
    monkeypatch.setattr(service, "_evict_runtime", AsyncMock())
    runtime = SimpleNamespace(
        runtime_id="pi-runtime",
        state=SimpleNamespace(native_session_id="pi-session", workspace_history_head="", linear_index=0),
        dropped_usage_events=7,
        prompt=AsyncMock(),
        abort=AsyncMock(),
        kill=AsyncMock(),
    )
    monkeypatch.setattr(service._runtime_registry, "open_or_create", AsyncMock(return_value=runtime))
    session = UserSession(bot_id=1, bot_alias="main", user_id=2, working_dir=str(tmp_path))
    session.disable_persistence()
    history = ChatHistoryService(ChatStore(tmp_path))
    received = []

    async def run(raw_events, *, outcome="completed"):
        async def events():
            for event in raw_events:
                yield event
            if outcome == "cancelled":
                session.stop_requested = True
            elif outcome == "task_cancelled":
                raise asyncio.CancelledError()
            elif outcome == "rpc_error":
                raise PiRpcRunError("Pi RPC failed")
            elif outcome == "transient_error":
                raise PiRpcRunError("503 Service Unavailable")
            else:
                if outcome == "dropped_usage":
                    runtime.dropped_usage_events += 1
                yield {"type": "agent_end"}

        runtime.events = events
        received.clear()
        async for event in service.stream_chat(
            profile=BotProfile(alias="main"), session=session,
            user_text="测试费用", prompt_text="测试费用", history_service=history, protocol="ag-ui",
        ):
            received.append(event)
        return received

    return SimpleNamespace(run=run, history=history, session=session, received=received, runtime=runtime)


def _finished_call():
    return {"type": "message_end", "message": {
        "role": "assistant", "id": "call-1", "stopReason": "toolUse",
        "content": [{"type": "text", "text": "继续处理"}],
        "usage": {"input": 100_000, "cacheRead": 300_000, "cacheWrite": 0, "output": 10_000},
    }}


def _saved_message(chat):
    meta = next(event for event in chat.received if event["type"] == "meta")
    return chat.history.store.get_message(meta["assistant_message_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [
    "cancelled", "message_error", "rpc_error", "transient_error", "task_cancelled", "completed", "dropped_usage",
])
async def test_finished_call_cost_survives_turn_finalization(pi_chat, outcome):
    events = [_finished_call(), _finished_call()]
    if outcome == "message_error":
        events.append({"type": "message_end", "message": {
            "role": "assistant", "id": "failed-call", "stopReason": "error", "errorMessage": "上游错误",
        }})
    if outcome == "task_cancelled":
        with pytest.raises(asyncio.CancelledError):
            await pi_chat.run(events, outcome=outcome)
    else:
        await pi_chat.run(events, outcome=outcome)

    saved = _saved_message(pi_chat)
    usage = saved["meta"]["context_usage"]
    cost = usage["estimated_cost"]
    assert cost["total"] == 0.36
    assert cost["scope"] == "turn"
    assert bool(cost.get("is_partial")) is (outcome != "completed")
    state = "completed" if outcome in {"completed", "dropped_usage"} else (
        "cancelled" if outcome in {"cancelled", "task_cancelled"} else "error"
    )
    assert saved["meta"]["completion_state"] == state
    assert pi_chat.session.is_processing is False
    if outcome == "task_cancelled":
        return

    finished = next(
        item["event"] for item in pi_chat.received
        if item["type"] == "ag_ui" and item["event"].type == "RUN_FINISHED"
    )
    assert finished.result["context_usage"] == usage
    assert finished.result["message"]["meta"]["context_usage"] == usage
    assert finished.result["turn_id"] == saved["turn_id"]
    assert finished.result["assistant_message_id"] == saved["id"]
    terminal = pi_chat.received[-1]
    assert terminal["type"] == ("error" if outcome in {"rpc_error", "transient_error"} else "done")
    assert terminal["context_usage"] == usage


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancelled", "rpc_error"])
async def test_interrupted_turn_without_usage_does_not_reuse_previous_turn_cost(pi_chat, outcome):
    await pi_chat.run([_finished_call()])
    previous = _saved_message(pi_chat)
    assert previous["meta"]["context_usage"]["estimated_cost"]["total"] == 0.36

    await pi_chat.run([{"type": "message_end", "message": {
        "role": "assistant", "id": "call-2", "stopReason": "toolUse",
    }}], outcome=outcome)
    current = _saved_message(pi_chat)
    assert current["id"] != previous["id"]
    assert not (current["meta"].get("context_usage") or {}).get("estimated_cost")
    assert not (pi_chat.received[-1].get("context_usage") or {}).get("estimated_cost")
