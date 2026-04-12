from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_state import save_assistant_runtime_state


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


def test_compile_assistant_prompt_uses_structured_working_memory_sections(tmp_path: Path):
    from bot.assistant_context import compile_assistant_prompt, rebuild_assistant_index

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "维护本机唯一 assistant 的升级路径。\n",
        encoding="utf-8",
    )
    (home.root / "memory" / "working" / "open_loops.md").write_text(
        "- 定义 working memory 压缩策略\n- 避免与 Codex 原生会话重复\n",
        encoding="utf-8",
    )
    (home.root / "memory" / "working" / "user_prefs.md").write_text(
        "- 回答尽量精简\n- 不要用浏览器\n",
        encoding="utf-8",
    )
    (home.root / "memory" / "working" / "recent_summary.md").write_text(
        "- assistant 是本机全局助手，不属于当前项目\n",
        encoding="utf-8",
    )
    save_assistant_runtime_state(
        home,
        1001,
        {
            "history": [
                {
                    "timestamp": "2026-04-12T11:00:00",
                    "role": "user",
                    "content": "这是一段不该直接原样注入 prompt 的近期原文",
                }
            ]
        },
    )
    knowledge_file = home.root / "memory" / "knowledge" / "scope.md"
    knowledge_file.write_text(
        "---\nstatus: approved\n---\nassistant 是本机唯一长期助手。\n",
        encoding="utf-8",
    )
    rebuild_assistant_index(home)

    prompt = compile_assistant_prompt(home, user_id=1001, user_text="现在怎么设计？")

    assert "current_goal:" in prompt
    assert "open_loops:" in prompt
    assert "user_preferences:" in prompt
    assert "recent_summary:" in prompt
    assert "retrieved_knowledge:" in prompt
    assert "维护本机唯一 assistant 的升级路径" in prompt
    assert "回答尽量精简" in prompt
    assert "assistant 是本机全局助手，不属于当前项目" in prompt
    assert "这是一段不该直接原样注入 prompt 的近期原文" not in prompt


def test_compile_assistant_prompt_falls_back_to_short_history_summary_without_native_session(tmp_path: Path):
    from bot.assistant_context import compile_assistant_prompt

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    save_assistant_runtime_state(
        home,
        1001,
        {
            "history": [
                {
                    "timestamp": "2026-04-12T11:00:00",
                    "role": "user",
                    "content": "先把 assistant 设计成全局的、本机唯一的。",
                },
                {
                    "timestamp": "2026-04-12T11:01:00",
                    "role": "assistant",
                    "content": "已经收敛为全局 assistant，不属于当前项目。",
                },
            ]
        },
    )

    prompt = compile_assistant_prompt(
        home,
        user_id=1001,
        user_text="继续。",
        has_native_session=False,
    )

    assert "current_goal:" in prompt
    assert "recent_summary:" in prompt
    assert "先把 assistant 设计成全局的、本机唯一的" in prompt
    assert "已经收敛为全局 assistant" in prompt


def test_compile_assistant_prompt_omits_history_fallback_when_native_session_exists(tmp_path: Path):
    from bot.assistant_context import compile_assistant_prompt

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    save_assistant_runtime_state(
        home,
        1001,
        {
            "history": [
                {
                    "timestamp": "2026-04-12T11:00:00",
                    "role": "user",
                    "content": "这段近期历史已经在 Codex 原生会话里了。",
                },
                {
                    "timestamp": "2026-04-12T11:01:00",
                    "role": "assistant",
                    "content": "所以本地 prompt 不该再重复塞一份。",
                },
            ]
        },
    )

    prompt = compile_assistant_prompt(
        home,
        user_id=1001,
        user_text="继续。",
        has_native_session=True,
    )

    assert "这段近期历史已经在 Codex 原生会话里了" not in prompt
    assert "所以本地 prompt 不该再重复塞一份" not in prompt
    assert "recent_summary:" not in prompt
    assert "current_goal:" not in prompt
