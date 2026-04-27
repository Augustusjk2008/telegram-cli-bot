from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


def test_memory_store_bootstraps_schema_and_supports_upsert_and_search(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path / "assistant-root")
    store = AssistantMemoryStore(home)
    memory_id = store.upsert(MemoryRecordInput(
        user_id=1001, scope="user", kind="semantic", source_type="chat", source_ref="cap_1",
        title="语言偏好", summary="默认中文", body="- 默认中文\n- 输出短",
        tags=["preference", "language"], entity_keys=["user:1001", "pref:language"],
        importance=0.9, confidence=1.0, freshness=0.9,
    ))
    rows = store.search_lexical(user_id=1001, query_text="默认中文", kinds=["semantic"], scopes=["user"], limit=5)
    assert memory_id
    assert rows
    assert rows[0].id == memory_id
    assert rows[0].summary == "默认中文"
    assert store.db_path == home.root / "indexes" / "memory.db"
    assert store.db_path.is_file()


def test_memory_store_marks_invalidated_rows_out_of_recall_results(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path / "assistant-root")
    store = AssistantMemoryStore(home)
    memory_id = store.upsert(MemoryRecordInput(
        user_id=1001, scope="user", kind="semantic", source_type="chat", source_ref="cap_2",
        title="旧偏好", summary="旧结论", body="- 这条会失效", tags=["preference"],
        entity_keys=["user:1001", "pref:style"], importance=0.4, confidence=0.9, freshness=0.2,
    ))
    store.invalidate(memory_id, reason="superseded")
    rows = store.search_lexical(user_id=1001, query_text="旧偏好", kinds=["semantic"], scopes=["user"], limit=5)
    assert rows == []


def test_search_lexical_matches_short_chinese_query_inside_long_memory(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    store = AssistantMemoryStore(home)
    store.upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_cjk",
            title="用户偏好",
            summary="以后默认用简短中文回答",
            body="- 以后默认用简短中文回答",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )

    rows = store.search_lexical(user_id=1001, query_text="简短中文")

    assert len(rows) == 1
    assert rows[0].summary == "以后默认用简短中文回答"


def test_search_lexical_matches_two_char_chinese_query(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    store = AssistantMemoryStore(home)
    store.upsert(
        MemoryRecordInput(
            user_id=1001,
            scope="user",
            kind="semantic",
            source_type="test",
            source_ref="case_default",
            title="用户偏好",
            summary="以后默认用简短中文回答",
            body="- 以后默认用简短中文回答",
            tags=["preference"],
            entity_keys=["user:1001"],
        )
    )

    rows = store.search_lexical(user_id=1001, query_text="默认")

    assert len(rows) == 1
    assert rows[0].title == "用户偏好"
