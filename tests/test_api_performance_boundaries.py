from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key
from bot.web import api_service
from bot.web.async_chat_store import AsyncChatStore, ChatStoreOverloadedError
from bot.web.chat_store import ChatStore


@pytest.mark.asyncio
async def test_async_chat_store_keeps_event_loop_progressing(tmp_path: Path) -> None:
    store = AsyncChatStore(
        ChatStore(tmp_path),
        executor=ThreadPoolExecutor(max_workers=1),
        max_pending=2,
    )
    ticks = 0

    def slow_read() -> str:
        time.sleep(0.12)
        return "done"

    async def ticker() -> None:
        nonlocal ticks
        deadline = asyncio.get_running_loop().time() + 0.1
        while asyncio.get_running_loop().time() < deadline:
            ticks += 1
            await asyncio.sleep(0.01)

    result, _ = await asyncio.gather(store.run_read(slow_read), ticker())

    assert result == "done"
    assert ticks >= 5


@pytest.mark.asyncio
async def test_async_chat_store_serializes_writes_per_workspace(tmp_path: Path) -> None:
    executor = ThreadPoolExecutor(max_workers=2)
    first = AsyncChatStore(ChatStore(tmp_path), executor=executor)
    second = AsyncChatStore(ChatStore(tmp_path), executor=executor)
    state_lock = threading.Lock()
    active = 0
    peak = 0

    def write() -> None:
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with state_lock:
            active -= 1

    await asyncio.gather(
        first.run_write(write),
        second.run_write(write),
    )

    assert peak == 1


@pytest.mark.asyncio
async def test_async_chat_store_rejects_requests_above_pending_budget(tmp_path: Path) -> None:
    store = AsyncChatStore(
        ChatStore(tmp_path),
        executor=ThreadPoolExecutor(max_workers=1),
        max_pending=1,
    )
    started = threading.Event()
    release = threading.Event()

    def blocked_read() -> str:
        started.set()
        release.wait(timeout=2)
        return "done"

    first = asyncio.create_task(store.run_read(blocked_read))
    await asyncio.to_thread(started.wait, 1)

    with pytest.raises(ChatStoreOverloadedError):
        await store.run_read(lambda: "overflow")

    release.set()
    assert await first == "done"


@pytest.mark.asyncio
async def test_update_download_progress_is_bounded_and_keeps_done(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_download(*, repo_root, progress_callback):
        assert repo_root == tmp_path.resolve()
        for index in range(1000):
            progress_callback({"index": index})
        return {"ready": True}

    monkeypatch.setattr(api_service, "download_latest_update", fake_download)

    events = [
        event
        async for event in api_service._stream_update_download(tmp_path)
    ]

    progress = [event for event in events if event["type"] == "progress"]
    assert progress
    assert progress[-1]["index"] == 999
    assert events[-1] == {"type": "done", "status": {"ready": True}}


def test_list_conversations_uses_native_batch_decorator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = SimpleNamespace(
        bot_id=1,
        user_id=2,
        agent_id="main",
        working_dir=str(workspace),
        active_conversation_id="conversation-1",
    )
    profile = SimpleNamespace()
    items = [
        {"id": f"conversation-{index}", "native_provider": "native_agent"}
        for index in range(3)
    ]

    class FakeStore:
        history_reads = 0
        requested_limit = 0

        def list_conversations(self, **kwargs):
            self.requested_limit = int(kwargs["limit"])
            return list(items)

        def get_conversation_native_provider(self, _conversation_id):
            return "native_agent"

        def latest_active_workspace_histories(self, conversation_ids):
            self.history_reads += 1
            assert list(conversation_ids) == [
                "conversation-0",
                "conversation-1",
                "conversation-2",
            ]
            return {
                conversation_id: {
                    "workspace_history_head": f"head-{conversation_id}",
                    "linear_index": index,
                }
                for index, conversation_id in enumerate(conversation_ids)
            }

        def latest_active_workspace_history(self, _conversation_id):
            raise AssertionError("list_conversations must not query workspace history per item")

    store = FakeStore()
    pi_store = PiSessionStore(tmp_path / "pi-sessions.json")
    for index, item in enumerate(items):
        conversation_id = str(item["id"])
        pi_store.upsert(
            PiSessionRecord(
                key=pi_session_key(
                    cwd=str(workspace),
                    bot_id=1,
                    user_id=2,
                    conversation_id=conversation_id,
                ),
                conversation_id=conversation_id,
                workspace_history_head=f"pi-head-{index}",
                linear_index=index + 10,
            )
        )
    pi_reads = 0
    original_read = pi_store._read_payload

    def counted_read():
        nonlocal pi_reads
        pi_reads += 1
        return original_read()

    monkeypatch.setattr(pi_store, "_read_payload", counted_read)
    monkeypatch.setattr(
        api_service,
        "get_chat_session_for_alias",
        lambda *_args, **_kwargs: (profile, None, session),
    )
    monkeypatch.setattr(
        api_service,
        "_resolve_requested_execution_mode",
        lambda *_args, **_kwargs: "native_agent",
    )
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _session: store)
    monkeypatch.setattr(api_service, "_pi_store", lambda: pi_store)

    payload = api_service.list_conversations(
        SimpleNamespace(),
        "main",
        2,
        limit=10_000,
        execution_mode="native_agent",
    )

    assert pi_reads == 1
    assert store.history_reads == 1
    assert store.requested_limit == 200
    assert payload["items"][1]["active"] is True
    assert payload["items"][1]["workspace_history_head"] == "pi-head-1"
