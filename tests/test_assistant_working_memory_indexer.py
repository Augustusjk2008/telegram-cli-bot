from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_recall import recall_assistant_memories
from bot.assistant_working_memory_indexer import index_working_memories


def test_index_working_memories_makes_recent_summary_recallable(tmp_path):
    home = bootstrap_assistant_home(tmp_path)
    (home.root / "memory" / "working" / "recent_summary.md").write_text(
        "- startup_misfire 补跑成功，email_recvbox_check 仍需复测。\n",
        encoding="utf-8",
    )

    result = index_working_memories(home)

    assert result.indexed_count == 1
    recall = recall_assistant_memories(home, user_id=1001, user_text="startup_misfire")
    assert "startup_misfire" in recall.prompt_block


def test_index_working_memories_is_idempotent(tmp_path):
    home = bootstrap_assistant_home(tmp_path)
    (home.root / "memory" / "working" / "open_loops.md").write_text(
        "- email_recvbox_check 仍需复测。\n",
        encoding="utf-8",
    )

    first = index_working_memories(home)
    second = index_working_memories(home)

    assert first.indexed_count == 1
    assert second.indexed_count == 1
    assert first.memory_ids == second.memory_ids
