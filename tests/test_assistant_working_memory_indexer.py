from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.memory.recall import recall_assistant_memories
from bot.assistant.memory.working_indexer import index_working_memories


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


def test_index_working_memories_skips_unchanged_files(tmp_path):
    home = bootstrap_assistant_home(tmp_path)
    target = home.root / "memory" / "working" / "open_loops.md"
    target.write_text(
        "- email_recvbox_check 仍需复测。\n",
        encoding="utf-8",
    )

    first = index_working_memories(home)
    second = index_working_memories(home)

    assert first.indexed_count == 1
    assert second.indexed_count == 0
    assert second.memory_ids == first.memory_ids
