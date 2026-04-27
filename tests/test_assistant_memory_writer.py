from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_recall import recall_assistant_memories
from bot.assistant_memory_writer import DreamMemoryInput, extract_hot_path_memories, write_dream_memories, write_hot_path_memories


def test_extract_hot_path_memories_from_explicit_preference():
    records = extract_hot_path_memories(user_id=1001, user_text="请记住默认中文", assistant_text="好的", source_ref="cap_1")
    assert records
    assert records[0].kind == "semantic"
    assert "默认中文" in records[0].summary


def test_hot_path_memory_does_not_extract_from_assistant_reply():
    records = extract_hot_path_memories(
        user_id=1001,
        user_text="我想知道你的记忆系统生效没",
        assistant_text="当前能看到“凯”“默认中文”“7897”等记忆。",
        source_ref="cap_pollution",
    )

    assert records == []


def test_hot_path_memory_extracts_explicit_user_preference_only():
    records = extract_hot_path_memories(
        user_id=1001,
        user_text="请记住以后默认用简短中文回答",
        assistant_text="已记录。",
        source_ref="cap_preference",
    )

    assert len(records) == 1
    assert records[0].summary == "以后默认用简短中文回答"
    assert records[0].source_ref == "cap_preference"


def test_hot_path_and_dream_memory_writes_are_recallable(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path / "assistant-root")
    write_hot_path_memories(home, user_id=1001, user_text="请记住默认中文", assistant_text="好的", source_ref="cap_1")
    write_dream_memories(home, user_id=1001, source_ref="dream_1", memories=[DreamMemoryInput(
        title="邮件 cron 根因", summary="pending_run_id 残留", body="- pending_run_id 残留", tags=["cron"], entity_keys=["incident:cron"],
    )])
    assert "默认中文" in recall_assistant_memories(home, user_id=1001, user_text="默认中文").prompt_block
    assert "pending_run_id" in recall_assistant_memories(home, user_id=1001, user_text="pending_run_id").prompt_block
