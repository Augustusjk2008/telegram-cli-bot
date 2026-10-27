from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from bot.web import api_service as api


def _done_event(*, turn_id: str, content: str, completion_state: str) -> dict[str, object]:
    return {
        "type": "done",
        "turn_id": turn_id,
        "assistant_message_id": f"assistant-{turn_id}",
        "user_message_id": f"user-{turn_id}",
        "output": content,
        "message": {
            "id": f"assistant-{turn_id}",
            "turn_id": turn_id,
            "role": "assistant",
            "content": content,
            "state": "error" if completion_state != "completed" else "done",
            "meta": {"completion_state": completion_state},
        },
    }


def _session() -> SimpleNamespace:
    return SimpleNamespace(stop_requested=False, _lock=threading.Lock())


@pytest.mark.asyncio
async def test_endless_attempts_emit_intermediate_errors_and_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    prompts: list[str] = []

    async def no_delay(_session: object) -> None:
        return None

    async def attempt(text: str, _request: api._ChatRunRequest):
        prompts.append(text)
        yield {"type": "meta", "turn_id": f"turn-{len(prompts)}"}
        yield _done_event(
            turn_id=f"turn-{len(prompts)}",
            content="temporary failure" if len(prompts) == 1 else "finished",
            completion_state="error" if len(prompts) == 1 else "completed",
        )

    monkeypatch.setattr(api, "_wait_for_endless_retry", no_delay)
    request = api._build_chat_run_request("main", 1, "initial", endless_mode=True)
    events = [
        event
        async for event in api._stream_endless_attempts(
            session=session,
            alias="main",
            shared_user_id=1,
            initial_text="initial",
            initial_request=request,
            attempt_factory=attempt,
        )
    ]

    assert prompts == ["initial", "Continue"]
    assert [event["type"] for event in events] == ["meta", "endless_error", "meta", "done"]
    assert events[1]["message"]["content"] == "temporary failure"
    assert events[1]["attempt"] == 1


@pytest.mark.asyncio
async def test_endless_attempts_stop_before_sending_next_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    prompts: list[str] = []

    async def stop_during_delay(_session: object) -> None:
        raise api.ChatInputCancelled()

    async def attempt(text: str, _request: api._ChatRunRequest):
        prompts.append(text)
        yield _done_event(turn_id="turn-1", content="temporary failure", completion_state="error")

    monkeypatch.setattr(api, "_wait_for_endless_retry", stop_during_delay)
    request = api._build_chat_run_request("main", 1, "initial", endless_mode=True)
    events = [
        event
        async for event in api._stream_endless_attempts(
            session=session,
            alias="main",
            shared_user_id=1,
            initial_text="initial",
            initial_request=request,
            attempt_factory=attempt,
        )
    ]

    assert prompts == ["initial"]
    assert [event["type"] for event in events] == ["endless_error", "error"]
    assert events[-1]["code"] == "cancelled"


@pytest.mark.asyncio
async def test_endless_attempts_retry_native_error_events(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    prompts: list[str] = []

    async def no_delay(_session: object) -> None:
        return None

    async def attempt(text: str, _request: api._ChatRunRequest):
        prompts.append(text)
        if len(prompts) == 1:
            yield {
                "type": "error",
                "code": "native_agent_error",
                "turn_id": "turn-1",
                "assistant_message_id": "assistant-turn-1",
                "message": "Pi 暂时失败",
            }
            return
        yield _done_event(turn_id="turn-2", content="finished", completion_state="completed")

    monkeypatch.setattr(api, "_wait_for_endless_retry", no_delay)
    request = api._build_chat_run_request("main", 1, "initial", endless_mode=True)
    events = [
        event
        async for event in api._stream_endless_attempts(
            session=session,
            alias="main",
            shared_user_id=1,
            initial_text="initial",
            initial_request=request,
            attempt_factory=attempt,
        )
    ]

    assert prompts == ["initial", "Continue"]
    assert [event["type"] for event in events] == ["endless_error", "done"]
    assert events[0]["output"] == "Pi 暂时失败"


@pytest.mark.asyncio
async def test_endless_attempts_stop_on_session_binding_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    prompts: list[str] = []

    async def attempt(text: str, _request: api._ChatRunRequest):
        prompts.append(text)
        yield {"type": "error", "code": "conversation_changed", "message": "会话已变化"}

    request = api._build_chat_run_request("main", 1, "initial", endless_mode=True)
    events = [
        event
        async for event in api._stream_endless_attempts(
            session=session,
            alias="main",
            shared_user_id=1,
            initial_text="initial",
            initial_request=request,
            attempt_factory=attempt,
        )
    ]

    assert prompts == ["initial"]
    assert events == [{"type": "error", "code": "conversation_changed", "message": "会话已变化"}]


@pytest.mark.asyncio
async def test_endless_attempts_keep_ag_ui_success_terminal_event(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    prompts: list[str] = []

    async def no_delay(_session: object) -> None:
        return None

    async def attempt(text: str, _request: api._ChatRunRequest):
        prompts.append(text)
        if len(prompts) == 1:
            yield {"type": "ag_ui", "event": {"type": "RUN_ERROR", "message": "Pi 暂时失败"}}
            yield {
                "type": "ag_ui",
                "event": {
                    "type": "RUN_FINISHED",
                    "result": {
                        "completion_state": "error",
                        "turn_id": "turn-1",
                        "assistant_message_id": "assistant-turn-1",
                        "content": "Pi 暂时失败",
                    },
                },
            }
            return
        yield {
            "type": "ag_ui",
            "event": {
                "type": "RUN_FINISHED",
                "result": {
                    "completion_state": "completed",
                    "turn_id": "turn-2",
                    "assistant_message_id": "assistant-turn-2",
                    "content": "完成",
                },
            },
        }
        yield _done_event(turn_id="turn-2", content="完成", completion_state="completed")

    monkeypatch.setattr(api, "_wait_for_endless_retry", no_delay)
    request = api._build_chat_run_request("main", 1, "initial", endless_mode=True)
    events = [
        event
        async for event in api._stream_endless_attempts(
            session=session,
            alias="main",
            shared_user_id=1,
            initial_text="initial",
            initial_request=request,
            attempt_factory=attempt,
        )
    ]

    assert prompts == ["initial", "Continue"]
    assert [event["type"] for event in events] == ["endless_error", "ag_ui", "done"]
    assert events[1]["event"]["result"]["completion_state"] == "completed"
