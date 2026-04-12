import json

from bot.assistant_compaction import (
    build_compaction_memory_block,
    finalize_compaction,
    load_compaction_state,
    refresh_compaction_state,
    list_pending_capture_ids,
    snapshot_managed_surface,
)
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_state import record_assistant_capture


def test_refresh_compaction_state_marks_pending_after_six_new_captures(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    latest_capture = None
    for index in range(6):
        latest_capture = record_assistant_capture(
            home,
            1001,
            f"user {index}",
            f"assistant {index}",
        )
    state = refresh_compaction_state(home, latest_capture=latest_capture)

    assert latest_capture is not None
    assert state["latest_capture_id"] == latest_capture["id"]
    assert state["pending"] is True
    assert state["pending_reason"] == "capture_threshold"
    assert state["pending_capture_count"] == 6
    assert load_compaction_state(home)["pending_capture_count"] == 6


def test_refresh_compaction_state_marks_pending_for_strong_signal_before_threshold(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    latest_capture = record_assistant_capture(
        home,
        1001,
        "assistant 是全局的，工作路径固定，不允许修改",
        "记住了",
    )

    state = refresh_compaction_state(home, latest_capture=latest_capture)

    assert state["pending"] is True
    assert state["pending_reason"] == "strong_signal"
    assert state["pending_capture_count"] == 1


def test_build_compaction_memory_block_returns_empty_when_not_pending(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    assert build_compaction_memory_block(home) == ""


def test_build_compaction_memory_block_includes_quiet_maintenance_and_proposals_path_when_pending(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    latest_capture = record_assistant_capture(
        home,
        1001,
        "assistant 是全局的，工作路径固定，不允许修改",
        "记住了",
    )
    refresh_compaction_state(home, latest_capture=latest_capture)

    block = build_compaction_memory_block(home)

    assert "后台维护" in block
    assert "不要在回复中主动提及" in block
    assert ".assistant/proposals" in block


def test_finalize_compaction_writes_audit_when_working_files_change(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    before = snapshot_managed_surface(home)

    capture = record_assistant_capture(home, 1001, "hello", "world")
    refresh_compaction_state(home, latest_capture=capture)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "- Updated working memory\n",
        encoding="utf-8",
    )
    after = snapshot_managed_surface(home)

    changed = finalize_compaction(
        home,
        before=before,
        after=after,
        consumed_capture_ids=[capture["id"]],
    )

    audit_path = home.root / "audit" / "compactions.jsonl"
    lines = audit_path.read_text(encoding="utf-8").splitlines()

    assert changed is True
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["consumed_capture_ids"] == [capture["id"]]
    assert payload["before"] != payload["after"]

    state = load_compaction_state(home)
    assert state["pending"] is False
    assert state["pending_capture_count"] == 0
    assert state["cursor_capture_id"] == capture["id"]
    assert state["last_compacted_at"]


def test_list_pending_capture_ids_returns_full_cursor_range(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    first = record_assistant_capture(home, 1001, "user 1", "assistant 1")
    second = record_assistant_capture(home, 1001, "user 2", "assistant 2")
    save_state = load_compaction_state(home)
    save_state["cursor_capture_id"] = first["id"]
    from bot.assistant_compaction import save_compaction_state
    save_compaction_state(home, save_state)

    assert list_pending_capture_ids(home) == [second["id"]]


def test_finalize_compaction_writes_real_consumed_capture_range_to_audit(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    old_capture = record_assistant_capture(home, 1001, "old", "done")
    state = load_compaction_state(home)
    from bot.assistant_compaction import save_compaction_state
    save_compaction_state(
        home,
        {
            **state,
            "cursor_capture_id": old_capture["id"],
            "last_compacted_at": old_capture["created_at"],
        },
    )

    capture_a = record_assistant_capture(home, 1001, "user a", "assistant a")
    capture_b = record_assistant_capture(home, 1001, "user b", "assistant b")
    refresh_compaction_state(home, latest_capture=capture_b)

    before = snapshot_managed_surface(home)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "- Updated working memory\n",
        encoding="utf-8",
    )
    after = snapshot_managed_surface(home)

    consumed_capture_ids = list_pending_capture_ids(home)
    changed = finalize_compaction(
        home,
        before=before,
        after=after,
        consumed_capture_ids=consumed_capture_ids,
    )

    audit_path = home.root / "audit" / "compactions.jsonl"
    payload = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    state = load_compaction_state(home)

    assert changed is True
    assert consumed_capture_ids == [capture_a["id"], capture_b["id"]]
    assert payload["from_cursor_capture_id"] == old_capture["id"]
    assert payload["to_cursor_capture_id"] == capture_b["id"]
    assert payload["consumed_capture_count"] == 2
    assert payload["consumed_capture_ids"] == [capture_a["id"], capture_b["id"]]
    assert state["cursor_capture_id"] == capture_b["id"]


def test_finalize_compaction_keeps_pending_when_surface_is_unchanged(tmp_path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    capture = record_assistant_capture(home, 1001, "assistant 是全局的", "记住了")
    refresh_compaction_state(home, latest_capture=capture)
    before = snapshot_managed_surface(home)

    changed = finalize_compaction(
        home,
        before=before,
        after=before,
        consumed_capture_ids=[capture["id"]],
    )

    state = load_compaction_state(home)
    assert changed is False
    assert state["pending"] is True
    assert state["pending_reason"] == "strong_signal"
    assert state["pending_capture_count"] == 1
    assert state["cursor_capture_id"] is None
    assert not (home.root / "audit" / "compactions.jsonl").exists()
