from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_maintenance import find_duplicate_memories, invalidate_duplicate_memories
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


def test_find_duplicate_memories_groups_active_duplicate_summaries(tmp_path):
    home = bootstrap_assistant_home(tmp_path)
    store = AssistantMemoryStore(home)
    for source_ref in ("cap_1", "cap_2", "cap_3"):
        store.upsert(
            MemoryRecordInput(
                user_id=1001,
                scope="user",
                kind="semantic",
                source_type="chat",
                source_ref=source_ref,
                title="用户身份",
                summary="邮箱",
                body="- 邮箱",
                tags=["identity"],
                entity_keys=["user:1001"],
            )
        )

    groups = find_duplicate_memories(home)

    assert len(groups) == 1
    assert groups[0].summary == "邮箱"
    assert len(groups[0].memory_ids) == 3


def test_invalidate_duplicate_memories_keeps_newest_active_record(tmp_path):
    home = bootstrap_assistant_home(tmp_path)
    store = AssistantMemoryStore(home)
    for source_ref in ("cap_1", "cap_2", "cap_3"):
        store.upsert(
            MemoryRecordInput(
                user_id=1001,
                scope="user",
                kind="semantic",
                source_type="chat",
                source_ref=source_ref,
                title="用户身份",
                summary="邮箱",
                body="- 邮箱",
                tags=["identity"],
                entity_keys=["user:1001"],
            )
        )

    result = invalidate_duplicate_memories(home, reason="duplicate")

    assert result.invalidated_count == 2
    rows = store.search_lexical(user_id=1001, query_text="邮箱")
    assert len(rows) == 1
