from __future__ import annotations

import asyncio
import hashlib
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bot import config
from bot.cluster.config import BotClusterConfig
from bot.models import AgentProfile
from bot.native_agent import service as native_module
from bot.native_agent.service import NativeAgentService
from bot.web import api_service, chat_translation
from bot.web.plan_mode import build_plan_execution_prompt
from bot.web.translation_config import PROMPT_TARGET_LANGUAGE, TranslationConfig
from tests.test_cli_streaming import _UsageProcess, usage_manager  # noqa: F401


@pytest.fixture(params=["cli", "native_agent"])
def chat(request, usage_manager, monkeypatch):
    profile, _, session = api_service.get_chat_session_for_alias(usage_manager, "main", 1001, "main")
    sent = []
    native = NativeAgentService()
    monkeypatch.setattr(native, "_ensure_runtime_eviction_task", lambda: None)
    monkeypatch.setattr(native, "_pi_runtime_env", lambda _: {})
    monkeypatch.setattr(native, "_runtime_config_fingerprint", lambda: "")
    monkeypatch.setattr(native, "_prompt_options", lambda _: ("test/model", "", "", ""))
    monkeypatch.setattr(native, "_append_system_prompt", lambda *a, **kw: ("", ""))
    monkeypatch.setattr(native_module, "run_pi_windows_preflight", lambda _: {"ok": True})
    monkeypatch.setattr(native_module, "effective_native_agent_config", lambda _: {"workspace_history_enabled": False})
    monkeypatch.setattr(config, "NATIVE_AGENT_ENABLED", True)

    async def prompt(text, **kwargs):
        sent.append(text)

    async def events():
        yield {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}], "stopReason": "stop"}}
        yield {"type": "agent_end"}

    runtime = SimpleNamespace(runtime_id="pi-test", state=SimpleNamespace(native_session_id="pi-session", workspace_history_head="", linear_index=0),
                              dropped_usage_events=0, prompt=prompt, events=events, abort=AsyncMock(), kill=AsyncMock())
    monkeypatch.setattr(native._runtime_registry, "open_or_create", AsyncMock(return_value=runtime))
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: native)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_: "codex")
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", AsyncMock(return_value=None))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *a, **kw: None)
    monkeypatch.setattr(api_service, "_reconcile_native_trace_before_completion", AsyncMock())

    def command(**kwargs):
        sent.append(kwargs["user_text"])
        return ["codex"], False

    monkeypatch.setattr(api_service, "build_cli_command", command)
    spawned = Mock(side_effect=lambda *a, **kw: _UsageProcess())
    monkeypatch.setattr(api_service.subprocess, "Popen", spawned)

    async def run(text="请解释", **kwargs):
        return [event async for event in api_service.stream_chat(usage_manager, "main", 1001, text,
                    execution_mode=request.param, **kwargs)]

    return SimpleNamespace(run=run, session=session, sent=sent, manager=usage_manager, mode=request.param, spawned=spawned,
                           history=api_service._history_service_for_execution_mode(session, request.param))


def translator(monkeypatch, *, enabled=True, outcome="completed"):
    settings = TranslationConfig(translate_user_enabled=enabled)

    async def translate(text, *, config, direction):
        assert direction == "user"
        result = {"status": outcome, "target_language": PROMPT_TARGET_LANGUAGE, "source_digest": hashlib.sha256(text.encode()).hexdigest()}
        result.update({"text": "Explain this"} if outcome == "completed" else {"error": "timeout"})
        return result

    service = SimpleNamespace(config_store=SimpleNamespace(get_config=lambda: settings), translate=AsyncMock(side_effect=translate), submit_answer=Mock(return_value=False))
    monkeypatch.setattr(chat_translation, "get_translation_service", lambda: service)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "disabled"])
async def test_input_translation_sends_once_and_preserves_original(chat, monkeypatch, outcome):
    service = translator(monkeypatch, enabled=outcome != "disabled", outcome=outcome)
    events = await chat.run()
    expected = "Explain this" if outcome == "completed" else "请解释"
    assert chat.sent == [expected]
    assert service.translate.await_count == (outcome != "disabled")
    meta = next(event for event in events if event["type"] == "meta")
    saved = chat.history.store.get_message(meta["user_message_id"])
    assert saved["content"] == "请解释"
    assert saved["agent_input_text"] == expected
    assert events[-1]["message"]["meta"]["completion_state"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("cluster_enabled", [False, True])
async def test_child_agent_skips_input_and_answer_translation(chat, monkeypatch, cluster_enabled):
    profile = api_service.get_profile_or_raise(chat.manager, "main")
    profile.agents.append(AgentProfile(id="worker", name="Worker"))
    profile.cluster = BotClusterConfig(enabled=cluster_enabled)
    service = translator(monkeypatch)
    settings = replace(service.config_store.get_config(), translate_assistant_enabled=True)
    service.config_store.get_config = lambda: settings

    events = await chat.run(agent_id="worker")

    assert len(chat.sent) == 1
    assert chat.sent[0].endswith("请解释")
    assert "Explain this" not in chat.sent[0]
    service.translate.assert_not_called()
    service.submit_answer.assert_not_called()
    assert events[-1]["type"] == "done"
    assert events[-1]["message"]["meta"]["completion_state"] == "completed"
    assert events[-1]["message"].get("translation") is None
    meta = next(event for event in events if event["type"] == "meta")
    _, _, session = api_service.get_chat_session_for_alias(chat.manager, "main", 1001, "worker")
    history = api_service._history_service_for_execution_mode(session, chat.mode)
    saved = history.store.get_message(meta["user_message_id"])
    assert saved["content"] == saved["agent_input_text"] == "请解释"
    assert saved.get("translation") is None


@pytest.mark.asyncio
async def test_stop_during_translation_keeps_session_owned_and_never_sends(chat, monkeypatch):
    service = translator(monkeypatch)
    settings = replace(service.config_store.get_config(), translate_assistant_enabled=True)
    service.config_store.get_config = lambda: settings
    entered = asyncio.Event()

    async def slow(*a, **kw):
        entered.set()
        await asyncio.Event().wait()

    service.translate.side_effect = slow
    task = asyncio.create_task(chat.run())
    await asyncio.wait_for(entered.wait(), 2)
    assert chat.session.is_processing
    busy = await chat.run("不应接受")
    assert busy[-1]["type"] == "error"
    result = await api_service.kill_user_process(chat.manager, "main", 1001, execution_mode=chat.mode)
    assert result["stop_requested"]
    events = await asyncio.wait_for(task, 2)
    assert chat.sent == []
    chat.spawned.assert_not_called()
    service.submit_answer.assert_not_called()
    assert events[-1]["message"]["meta"]["completion_state"] == "cancelled"
    assert not chat.session.is_processing


@pytest.mark.asyncio
async def test_plan_and_slash_are_prepared_after_translation(chat, monkeypatch):
    service = translator(monkeypatch)
    events = await chat.run("请解释", task_mode="plan")
    assert service.translate.call_args.args == ("请解释",)
    assert "Explain this" in chat.sent[0]
    assert "<PLAN_DRAFT>" in chat.sent[0]
    assert "请解释" not in chat.sent[0]
    assert len(chat.sent) == 1
    assert events[-1]["type"] == "done"
    service.config_store.get_config = lambda: TranslationConfig()
    await chat.run("//help")
    assert chat.sent[-1] == "/help"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        build_plan_execution_prompt("docs/plan/example.md"),
        "  请按方案执行。方案文件：docs/plan/example.md\n\n要求：\n- 先阅读方案和相关代码",
    ],
    ids=["current", "legacy"],
)
async def test_plan_execution_exits_plan_mode_for_current_and_legacy_prompts(chat, monkeypatch, prompt):
    translator(monkeypatch, enabled=False)

    events = await chat.run(prompt, task_mode="plan")

    assert chat.sent == [prompt.strip()]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_answer_translation_does_not_hold_turn_or_next_message(chat, monkeypatch):
    from bot.web.translation_service import TranslationService

    settings = TranslationConfig(translate_assistant_enabled=True, base_url="https://example.invalid/v1", api_key="test-key", model="test")
    service = TranslationService()
    service.config_store = SimpleNamespace(get_config=lambda: settings)
    release = asyncio.Event()

    async def slow(text, *, config, direction):
        assert direction == "assistant"
        await release.wait()
        return {"status": "completed", "text": "完成", "target_language": PROMPT_TARGET_LANGUAGE,
                "source_digest": hashlib.sha256(text.encode()).hexdigest()}

    service.translate = AsyncMock(side_effect=slow)
    monkeypatch.setattr(chat_translation, "get_translation_service", lambda: service)
    try:
        first = await asyncio.wait_for(chat.run(), 3)
        done = first[-1]["message"]
        assert done["content"] == "done"
        assert done["translation"]["status"] == "pending"
        assert not chat.session.is_processing
        second = await asyncio.wait_for(chat.run("下一轮"), 3)
        assert second[-1]["type"] == "done"
        release.set()
        for _ in range(100):
            saved = chat.history.store.get_message(done["id"])
            if (saved.get("translation") or {}).get("status") == "completed":
                break
            await asyncio.sleep(0.01)
        assert saved["translation"]["text"] == "完成"
    finally:
        release.set()
        await service.close()


@pytest.mark.asyncio
async def test_one_turn_keeps_translation_snapshot_when_config_changes(chat, monkeypatch):
    service = translator(monkeypatch)
    snapshot = replace(service.config_store.get_config(), translate_assistant_enabled=True)
    service.config_store.get_config = lambda: snapshot
    original_translate = service.translate.side_effect

    async def translate_and_disable(text, **kwargs):
        service.config_store.get_config = lambda: TranslationConfig()
        return await original_translate(text, **kwargs)

    service.translate.side_effect = translate_and_disable
    service.submit_answer = Mock(return_value=False)
    await chat.run()
    assert service.translate.call_args.kwargs["config"] is snapshot
    assert service.submit_answer.call_args.kwargs["config"] is snapshot
    await chat.run("下一轮")
    assert service.translate.await_count == 1
    assert service.submit_answer.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("chat", ["native_agent"], indirect=True)
async def test_pi_reconnect_reuses_pending_translation(chat, monkeypatch):
    service = translator(monkeypatch)
    original_translate = service.translate.side_effect
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(text, **kwargs):
        entered.set()
        await release.wait()
        return await original_translate(text, **kwargs)

    service.translate.side_effect = slow
    native = api_service.get_native_agent_service()
    stream = api_service._stream_native_agent_chat(chat.manager, "main", 1001, "请解释", enable_reconnect=True)
    first = await anext(stream)
    await asyncio.wait_for(entered.wait(), 2)
    await stream.aclose()
    release.set()
    try:
        resumed = [event async for event in api_service._stream_native_agent_chat(
            chat.manager, "main", 1001, "不应再次发送", resume_stream_id=first["stream_id"],
            resume_turn_id=first["turn_id"], after_sequence=first["sequence"],
        )]
        assert resumed[-1]["type"] == "done"
        assert service.translate.await_count == 1
        assert chat.sent == ["Explain this"]
    finally:
        await native.resume_turn_channel(first["stream_id"]).close()


@pytest.mark.asyncio
@pytest.mark.parametrize("chat", ["cli"], indirect=True)
async def test_stop_while_resuming_cli_does_not_write_prompt(chat, monkeypatch):
    translator(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    process = _UsageProcess()
    process.stdin = Mock()
    chat.spawned.side_effect = lambda *a, **kw: process
    monkeypatch.setattr(api_service, "build_cli_command", lambda **kwargs: (["codex"], True))

    def resume(*args):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(api_service, "resume_suspended_process", resume)
    task = asyncio.create_task(chat.run())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        result = await api_service.kill_user_process(chat.manager, "main", 1001)
        assert result["stop_requested"]
        release.set()
        events = await asyncio.wait_for(task, 2)
        process.stdin.write.assert_not_called()
        assert events[-1]["message"]["meta"]["completion_state"] == "cancelled"
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
