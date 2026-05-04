from bot.models import AgentProfile, BotProfile


def test_normalize_child_agent_id_accepts_slug():
    from bot.agents import normalize_agent_id

    assert normalize_agent_id("Reviewer_1") == "reviewer_1"


def test_normalize_child_agent_id_rejects_main():
    from bot.agents import normalize_agent_id

    try:
        normalize_agent_id("main", allow_main=False)
    except ValueError as exc:
        assert "main" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_normalize_agent_prompt_limits_size():
    from bot.agents import normalize_agent_prompt

    try:
        normalize_agent_prompt("x" * 12001)
    except ValueError as exc:
        assert "12000" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_agent_prompt_wrapper_keeps_visible_user_text_separate():
    from bot.agents import build_agent_prompt_input

    wrapped, prompt_hash = build_agent_prompt_input("改 tests", "你是审查 agent")

    assert prompt_hash
    assert "<tcbridge_agent_system_prompt>" in wrapped
    assert "你是审查 agent" in wrapped
    assert "<user_message>\n改 tests\n</user_message>" in wrapped


def test_bot_profile_round_trips_child_agents():
    profile = BotProfile(
        alias="repo",
        agents=[
            AgentProfile(
                id="reviewer",
                name="代码审查",
                system_prompt="先列风险",
                enabled=True,
                created_at="2026-05-04T10:00:00",
                updated_at="2026-05-04T10:00:00",
            )
        ],
    )

    restored = BotProfile.from_dict(profile.to_dict())

    assert restored.get_agent("main").name == "主 agent"
    assert restored.get_agent("reviewer").system_prompt == "先列风险"
    assert restored.to_dict()["agents"][0]["id"] == "reviewer"
