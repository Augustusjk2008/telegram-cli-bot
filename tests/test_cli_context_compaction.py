from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import api_service
from bot.web.chat_store import ChatStore, ChatTurnHandle


@pytest.fixture
def web_manager(tmp_path: Path) -> MultiBotManager:
    storage_file = tmp_path / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(tmp_path),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


def _codex_context_usage(left_percent: int, *, session_id: str = "thread-1") -> dict[str, object]:
    return {
        "provider": "codex",
        "source": "codex_session_token_count",
        "session_id": session_id,
        "used_tokens": 76_593,
        "context_window": 258_400,
        "context_left_percent": left_percent,
        "used_display": "76.6K",
        "window_display": "258K",
        "status_text": f"{left_percent}% context left | 76.6K / 258K",
    }


class _ScheduledFakeStdout:
    def __init__(self, owner: _ScheduledFakeProcess, schedule: list[tuple[float, str]]) -> None:
        self._owner = owner
        self._schedule = list(schedule)

    def readline(self, _size: int = -1) -> str:
        if not self._schedule:
            self._owner.returncode = 0
            return ""
        delay, line = self._schedule.pop(0)
        if delay:
            time.sleep(delay)
        return line

    def read(self) -> str:
        return ""

    def close(self) -> None:
        pass


class _ScheduledFakeProcess:
    def __init__(
        self,
        session_id: str = "thread-1",
        *,
        session_delay: float = 0,
        response_delay: float = 0.02,
    ) -> None:
        self.returncode: int | None = None
        self.stdout = _ScheduledFakeStdout(
            self,
            [
                (session_delay, f'{{"type":"thread.started","thread_id":"{session_id}"}}\n'),
                (response_delay, '{"type":"item.completed","item":{"type":"assistant_message","text":"done"}}\n'),
            ],
        )
        self.stdin = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def _store_completed_turn(
    store: ChatStore,
    *,
    provider: str,
    session_id: str,
    context_usage: dict[str, object],
) -> ChatTurnHandle:
    handle = store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        cli_type=provider,
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        user_text="hello",
        native_provider=provider,
    )
    store.complete_turn(
        handle,
        content="done",
        completion_state="completed",
        native_session_id=session_id,
        context_usage=context_usage,
    )
    return handle


def test_chat_store_returns_latest_context_usage_for_exact_native_session(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    old_codex_turn = _store_completed_turn(
        store,
        provider="codex",
        session_id="shared-id",
        context_usage={**_codex_context_usage(80, session_id="shared-id"), "compaction_count": 1},
    )
    _store_completed_turn(
        store,
        provider="claude",
        session_id="shared-id",
        context_usage={"session_id": "shared-id", "context_left_percent": 50, "compaction_count": 7},
    )
    expected = {**_codex_context_usage(70, session_id="shared-id"), "compaction_count": 2}
    _store_completed_turn(
        store,
        provider="codex",
        session_id="shared-id",
        context_usage=expected,
    )
    store.append_trace_event(old_codex_turn.turn_id, kind="event", summary="late trace recovery")

    assert store.get_latest_native_session_context_usage(
        native_provider="codex",
        native_session_id="shared-id",
    ) == expected
    assert store.get_latest_native_session_context_usage(
        native_provider="claude",
        native_session_id="shared-id",
    ) == {"session_id": "shared-id", "context_left_percent": 50, "compaction_count": 7}
    assert store.get_latest_native_session_context_usage(
        native_provider="codex",
        native_session_id="missing",
    ) is None


@pytest.mark.asyncio
async def test_stream_cli_chat_keeps_compaction_count_across_turns_in_same_session(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = [
        _codex_context_usage(20),
        _codex_context_usage(80),
        _codex_context_usage(80),
        _codex_context_usage(79),
    ]

    def fake_resolve(_cli_type: str, _session_id: str, _cwd_hint: str | None = None):
        return readings.pop(0) if len(readings) > 1 else readings[0]

    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", fake_resolve)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: _ScheduledFakeProcess())

    first_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "hello")
    ]
    second_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "hello again")
    ]

    first_done = next(event for event in first_events if event["type"] == "done")
    second_done = next(event for event in second_events if event["type"] == "done")
    assert first_done["message"]["meta"]["context_usage"]["compaction_count"] == 1
    assert second_done["message"]["meta"]["context_usage"]["compaction_count"] == 1


@pytest.mark.asyncio
async def test_stream_cli_chat_increments_compaction_count_across_turns_in_same_session(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = [
        _codex_context_usage(20),
        _codex_context_usage(80),
        _codex_context_usage(30),
        _codex_context_usage(90),
    ]

    def fake_resolve(_cli_type: str, _session_id: str, _cwd_hint: str | None = None):
        return readings.pop(0) if len(readings) > 1 else readings[0]

    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", fake_resolve)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: _ScheduledFakeProcess())

    first_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "hello")
    ]
    second_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "hello again")
    ]

    first_done = next(event for event in first_events if event["type"] == "done")
    second_done = next(event for event in second_events if event["type"] == "done")
    assert first_done["message"]["meta"]["context_usage"]["compaction_count"] == 1
    assert second_done["message"]["meta"]["context_usage"]["compaction_count"] == 2


@pytest.mark.asyncio
async def test_stream_cli_chat_resets_compaction_count_when_session_id_changes(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = [
        _codex_context_usage(20),
        _codex_context_usage(80),
        _codex_context_usage(80, session_id="thread-2"),
        _codex_context_usage(79, session_id="thread-2"),
    ]
    process_session_ids = iter(["thread-1", "thread-2"])

    def fake_resolve(_cli_type: str, _session_id: str, _cwd_hint: str | None = None):
        return readings.pop(0) if len(readings) > 1 else readings[0]

    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", fake_resolve)
    monkeypatch.setattr(
        api_service.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _ScheduledFakeProcess(next(process_session_ids)),
    )

    first_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "hello")
    ]
    second_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "new session")
    ]

    first_done = next(event for event in first_events if event["type"] == "done")
    second_done = next(event for event in second_events if event["type"] == "done")
    assert first_done["message"]["meta"]["context_usage"]["compaction_count"] == 1
    assert "compaction_count" not in second_done["message"]["meta"]["context_usage"]


@pytest.mark.asyncio
async def test_stream_cli_chat_switches_compaction_baseline_when_session_changes_mid_turn(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = [
        _codex_context_usage(20),
        _codex_context_usage(80),
        _codex_context_usage(80),
        _codex_context_usage(30, session_id="thread-2"),
        _codex_context_usage(90, session_id="thread-2"),
    ]
    processes = iter(
        [
            _ScheduledFakeProcess("thread-1"),
            _ScheduledFakeProcess("thread-2", session_delay=0.15, response_delay=0.15),
        ]
    )

    def fake_resolve(_cli_type: str, _session_id: str, _cwd_hint: str | None = None):
        return readings.pop(0) if len(readings) > 1 else readings[0]

    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["codex"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", fake_resolve)
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: next(processes))

    _ = [event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "hello")]
    second_events = [
        event async for event in api_service._stream_cli_chat(web_manager, "main", 1001, "new thread")
    ]

    second_done = next(event for event in second_events if event["type"] == "done")
    context_usage = second_done["message"]["meta"]["context_usage"]
    assert context_usage["session_id"] == "thread-2"
    assert context_usage["context_left_percent"] == 90
    assert context_usage["compaction_count"] == 1
