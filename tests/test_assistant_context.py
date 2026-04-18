from pathlib import Path

from bot.assistant_home import bootstrap_assistant_home


def test_compile_assistant_prompt_returns_plain_user_text_for_new_session(tmp_path: Path):
    from bot.assistant_context import compile_assistant_prompt

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    result = compile_assistant_prompt(
        home,
        user_id=1001,
        user_text="assistant 是什么？",
    )

    assert result.prompt_text == "assistant 是什么？"
    assert result.managed_prompt_hash_seen is None


def test_compile_assistant_prompt_adds_reread_notice_for_resumed_session_when_hash_changes(
    tmp_path: Path,
):
    from bot.assistant_context import compile_assistant_prompt

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    result = compile_assistant_prompt(
        home,
        user_id=1001,
        user_text="继续处理",
        has_native_session=True,
        managed_prompt_hash="hash-v2",
        seen_managed_prompt_hash="hash-v1",
    )

    assert result.prompt_text == "AGENTS.md 和 CLAUDE.md 已更新，请重新读取。\n\n继续处理"
    assert result.managed_prompt_hash_seen == "hash-v2"


def test_compile_assistant_prompt_keeps_plain_text_when_hash_is_unchanged(tmp_path: Path):
    from bot.assistant_context import compile_assistant_prompt

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    result = compile_assistant_prompt(
        home,
        user_id=1001,
        user_text="继续处理",
        has_native_session=True,
        managed_prompt_hash="hash-v1",
        seen_managed_prompt_hash="hash-v1",
    )

    assert result.prompt_text == "继续处理"
    assert result.managed_prompt_hash_seen == "hash-v1"
