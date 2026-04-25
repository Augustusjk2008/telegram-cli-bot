from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_memory_recall import plan_memory_recall, recall_assistant_memories
from bot.assistant_memory_store import AssistantMemoryStore, MemoryRecordInput


def test_plan_memory_recall_classifies_preference_queries():
    plan = plan_memory_recall("我默认用什么语言？")
    assert plan.kinds == ["semantic"]
    assert "user" in plan.scopes


def test_recall_renders_block_and_audit(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path / "assistant-root")
    store = AssistantMemoryStore(home)
    store.upsert(MemoryRecordInput(
        user_id=1001, scope="user", kind="semantic", source_type="chat", source_ref="cap_1",
        title="语言偏好", summary="默认中文", body="- 默认中文\n- 输出短", tags=["preference"],
        entity_keys=["user:1001", "pref:language"], importance=0.9, confidence=1.0, freshness=0.9,
    ))
    result = recall_assistant_memories(home, user_id=1001, user_text="默认中文")
    assert "<ASSISTANT_MEMORY_RECALL>" in result.prompt_block
    assert "默认中文" in result.prompt_block
    assert result.audit_path and Path(result.audit_path).is_file()
