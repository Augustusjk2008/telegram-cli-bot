from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.native_agent.pi_turn_stream import PiTurnChannel
from bot.web import api_service


@pytest.mark.asyncio
async def test_turn_channel_replays_after_sequence_without_restarting_producer() -> None:
    release = asyncio.Event()
    producer_starts = 0

    async def producer():
        nonlocal producer_starts
        producer_starts += 1
        yield {"type": "meta", "turn_id": "turn-1"}
        yield {"type": "delta", "text": "a"}
        await release.wait()
        yield {"type": "delta", "text": "b"}
        yield {"type": "done", "turn_id": "turn-1"}

    channel = PiTurnChannel(producer(), replay_max_events=16, replay_max_bytes=4096)
    first = channel.events().__aiter__()
    meta = await first.__anext__()
    delta = await first.__anext__()
    await first.aclose()

    release.set()
    await channel.wait_finished()
    replay = [event async for event in channel.events(after_sequence=delta["sequence"])]

    assert producer_starts == 1
    assert meta["stream_id"] == channel.stream_id
    assert [event["type"] for event in replay] == ["delta", "done"]
    assert [event["sequence"] for event in replay] == [3, 4]
    await channel.close()


@pytest.mark.asyncio
async def test_turn_channel_reports_gap_when_replay_budget_evicts_data() -> None:
    async def producer():
        for index in range(12):
            yield {"type": "trace", "event": {"summary": str(index)}}
        yield {"type": "done", "turn_id": "turn-2"}

    channel = PiTurnChannel(producer(), replay_max_events=4, replay_max_bytes=4096)
    await channel.wait_finished()

    replay = [event async for event in channel.events(after_sequence=0)]

    assert replay[0]["type"] == "gap"
    assert replay[0]["gap_from"] == 1
    assert replay[0]["gap_to"] >= 1
    assert replay[0]["snapshot_required"] is True
    assert replay[-1]["type"] == "done"
    await channel.close()


@pytest.mark.asyncio
async def test_turn_id_copied_to_data_events_does_not_make_all_replay_critical() -> None:
    async def producer():
        yield {"type": "meta", "turn_id": "turn-budget"}
        for index in range(12):
            yield {"type": "trace", "event": {"summary": str(index)}}
        yield {"type": "done", "turn_id": "turn-budget"}

    channel = PiTurnChannel(
        producer(),
        replay_max_events=4,
        replay_max_bytes=4096,
        control_max_events=4,
    )
    await channel.wait_finished()

    diagnostics = channel.diagnostics()

    assert diagnostics["overflowed"] is False
    assert diagnostics["replay_events"] <= 4
    assert diagnostics["dropped_count"] > 0
    replay = [event async for event in channel.events(after_sequence=0)]
    assert replay[0]["type"] == "meta"
    assert replay[1]["type"] == "gap"
    await channel.close()


@pytest.mark.asyncio
async def test_turn_channel_disconnect_grace_aborts_turn_but_keeps_channel() -> None:
    producer_release = asyncio.Event()
    aborted = asyncio.Event()

    async def producer():
        yield {"type": "meta", "turn_id": "turn-3"}
        await producer_release.wait()
        yield {"type": "done", "turn_id": "turn-3"}

    async def abort_turn() -> None:
        aborted.set()
        producer_release.set()

    channel = PiTurnChannel(
        producer(),
        reconnect_grace_seconds=0.01,
        abort_turn=abort_turn,
    )
    stream = channel.events().__aiter__()
    await stream.__anext__()
    await stream.aclose()

    await asyncio.wait_for(aborted.wait(), timeout=1)
    await channel.wait_finished()
    assert channel.diagnostics()["finished"] is True
    await channel.close()


@pytest.mark.asyncio
async def test_native_stream_resume_does_not_start_cluster_or_send_prompt(monkeypatch) -> None:
    class FakeChannel:
        async def events(self, *, after_sequence: int):
            assert after_sequence == 4
            yield {"type": "done", "stream_id": "pit-existing", "sequence": 5}

    class FakeService:
        def resume_turn_channel(self, stream_id: str, *, turn_id: str):
            assert stream_id == "pit-existing"
            assert turn_id == "turn-existing"
            return FakeChannel()

        async def stream_chat(self, **_kwargs):
            raise AssertionError("恢复请求不得重新执行 prompt")
            yield {}

    profile = SimpleNamespace(bot_mode="cli", cli_type="codex")
    session = SimpleNamespace()
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args: (profile, None, session))
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeService())
    monkeypatch.setattr(
        api_service,
        "_start_cluster_run_if_requested",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("恢复请求不得创建 cluster run")),
    )

    events = [
        event
        async for event in api_service._stream_native_agent_chat(
            None,
            "main",
            1,
            "",
            resume_stream_id="pit-existing",
            resume_turn_id="turn-existing",
            after_sequence=4,
        )
    ]

    assert events == [{"type": "done", "stream_id": "pit-existing", "sequence": 5}]


@pytest.mark.asyncio
async def test_turn_channel_control_overflow_aborts_with_explicit_error() -> None:
    abort_count = 0

    async def producer():
        yield {"type": "meta", "turn_id": "turn-overflow"}
        yield {"type": "permission", "permission_id": "p1"}
        yield {"type": "done", "turn_id": "turn-overflow"}

    async def abort_turn() -> None:
        nonlocal abort_count
        abort_count += 1

    channel = PiTurnChannel(
        producer(),
        replay_max_events=8,
        replay_max_bytes=4096,
        control_max_events=1,
        control_max_bytes=4096,
        abort_turn=abort_turn,
    )
    await channel.wait_finished()
    replay = [event async for event in channel.events()]

    assert abort_count == 1
    assert any(
        event.get("type") == "error" and event.get("code") == "stream_overflow"
        for event in replay
    )
    await channel.close()
