from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home


def test_compile_assistant_prompt_includes_user_request_and_approved_knowledge(tmp_path: Path):
    from bot.assistant_context import compile_assistant_prompt, rebuild_assistant_index

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    knowledge_file = home.root / "memory" / "knowledge" / "scope.md"
    knowledge_file.write_text(
        "---\nstatus: approved\n---\nassistant 是本机唯一长期助手。\n",
        encoding="utf-8",
    )
    rebuild_assistant_index(home)

    prompt = compile_assistant_prompt(home, user_id=1001, user_text="assistant 是什么？")

    assert "[LOCAL_ASSISTANT_CONTEXT]" in prompt
    assert "本机唯一长期助手" in prompt
    assert "[USER_REQUEST]" in prompt
    assert "assistant 是什么？" in prompt
