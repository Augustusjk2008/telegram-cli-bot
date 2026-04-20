def test_compile_assistant_prompt_returns_plain_user_text_for_new_session():
    from bot.assistant_context import compile_assistant_prompt

    result = compile_assistant_prompt(
        "assistant 是什么？",
    )

    assert result.prompt_text == "assistant 是什么？"
    assert result.managed_prompt_hash_seen is None


def test_compile_assistant_prompt_keeps_plain_text_for_resumed_session_when_hash_changes():
    from bot.assistant_context import compile_assistant_prompt

    result = compile_assistant_prompt(
        "继续处理",
        managed_prompt_hash="hash-v2",
        seen_managed_prompt_hash="hash-v1",
    )

    assert result.prompt_text == "继续处理"
    assert result.managed_prompt_hash_seen == "hash-v2"


def test_compile_assistant_prompt_keeps_plain_text_when_hash_is_unchanged():
    from bot.assistant_context import compile_assistant_prompt

    result = compile_assistant_prompt(
        "继续处理",
        managed_prompt_hash="hash-v1",
        seen_managed_prompt_hash="hash-v1",
    )

    assert result.prompt_text == "继续处理"
    assert result.managed_prompt_hash_seen == "hash-v1"
