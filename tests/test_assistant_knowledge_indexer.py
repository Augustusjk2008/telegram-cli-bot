from pathlib import Path

from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.memory.knowledge_indexer import index_knowledge_memories
from bot.assistant.memory.recall import recall_assistant_memories


def test_index_knowledge_memories_makes_markdown_recallable(tmp_path: Path):
    home = bootstrap_assistant_home(tmp_path)
    knowledge_dir = home.root / "memory" / "knowledge" / "vivado"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    (knowledge_dir / "clock-debug.md").write_text(
        "# Vivado clock debug\n\n- 检查 create_clock 和 generated_clock 约束。\n",
        encoding="utf-8",
    )

    result = index_knowledge_memories(home)

    assert result.indexed_count == 1
    recall = recall_assistant_memories(home, user_id=1001, user_text="Vivado generated_clock 怎么查")
    assert "Vivado clock debug" in recall.prompt_block
    assert "generated_clock" in recall.prompt_block
