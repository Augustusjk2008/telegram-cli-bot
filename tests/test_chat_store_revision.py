from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.web.chat_store import ChatStore
from bot.web import api_service


def _begin(store: ChatStore, *, conversation_id: str | None = None, text: str = "hello"):
    return store.begin_turn(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        agent_id="main",
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(store.workspace_dir),
        session_epoch=0,
        user_text=text,
        native_provider="codex",
        conversation_id=conversation_id,
    )


def test_history_revision_delta_tracks_add_stream_update_and_finalize(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    handle = _begin(store)

    initial = store.get_history_delta(handle.conversation_id, revision=0, limit=20)
    assert initial["reset"] is True
    assert {item["id"] for item in initial["items"]} == {
        handle.user_message_id,
        handle.assistant_message_id,
    }
    first_revision = initial["revision"]

    store.replace_assistant_content(handle, "partial", state="streaming")
    streaming = store.get_history_delta(handle.conversation_id, revision=first_revision, limit=20)
    assert [item["id"] for item in streaming["items"]] == [handle.assistant_message_id]
    assert streaming["items"][0]["content"] == "partial"

    store.complete_turn(handle, content="final", completion_state="completed")
    finalized = store.get_history_delta(
        handle.conversation_id,
        revision=streaming["revision"],
        limit=20,
    )
    assert finalized["items"][0]["content"] == "final"
    assert finalized["items"][0]["state"] == "done"
    assert finalized["deleted_ids"] == []


def test_history_revision_delta_emits_tombstones_for_discarded_turns(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    first = _begin(store, text="first")
    store.complete_turn(first, content="one", completion_state="completed")
    second = _begin(store, conversation_id=first.conversation_id, text="second")
    store.complete_turn(second, content="two", completion_state="completed")
    before = store.get_conversation_revision(first.conversation_id)

    assert store.mark_turns_after_discarded(first.conversation_id, first.turn_id) == 1
    delta = store.get_history_delta(first.conversation_id, revision=before, limit=20)

    assert set(delta["deleted_ids"]) == {second.user_message_id, second.assistant_message_id}
    assert delta["items"] == []
    assert delta["reset"] is False


def test_history_delta_keeps_legacy_after_id_and_uses_revision_only_when_requested(monkeypatch) -> None:
    items = [{"id": "m1"}, {"id": "m2"}]

    class FakeHistoryService:
        def list_history(self, _profile, _session, *, limit):
            assert limit == 50
            return items

        def list_history_delta(self, _profile, _session, **kwargs):
            return {"items": [{"id": "updated"}], "deleted_ids": ["gone"], **kwargs}

    profile = SimpleNamespace()
    session = SimpleNamespace()
    service = FakeHistoryService()
    monkeypatch.setattr(api_service, "get_chat_session_for_alias", lambda *_args: (profile, None, session))
    monkeypatch.setattr(api_service, "_resolve_requested_execution_mode", lambda *_args: "cli")
    monkeypatch.setattr(api_service, "_history_service_for_execution_mode", lambda *_args: service)

    legacy = api_service.get_history_delta(None, "main", 1, "m1")
    revision = api_service.get_history_delta(None, "main", 1, "", revision=3, cursor="7")

    assert legacy == {"items": [{"id": "m2"}], "reset": False}
    assert revision["items"] == [{"id": "updated"}]
    assert revision["deleted_ids"] == ["gone"]
    assert revision["revision"] == 3
    assert revision["cursor"] == "7"
