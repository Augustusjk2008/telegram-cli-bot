from __future__ import annotations

from bot.native_agent import context_usage


def test_native_agent_context_usage_counts_cache_tokens(monkeypatch) -> None:
    monkeypatch.setattr(context_usage, "find_configured_model", lambda model_id: {
        "id": model_id,
        "context_window": 1_000,
    })

    usage = context_usage.resolve_native_agent_context_usage(
        session_id="sess-1",
        model_id="jojocode/gpt-5.4",
        messages=[
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "tokens": {
                    "input": 100,
                    "cache": {"read": 200, "write": 50},
                    "output": 30,
                    "reasoning": 20,
                },
            },
        ],
    )

    assert usage is not None
    assert usage["context_used"] == 350
    assert usage["used_tokens"] == 350
    assert usage["context_window"] == 1_000
    assert usage["context_used_percent"] == 35
    assert usage["context_left_percent"] == 65
    assert usage["input_tokens"] == 100
    assert usage["cache_read_tokens"] == 200
    assert usage["cache_write_tokens"] == 50
    assert usage["output_tokens"] == 30
    assert usage["reasoning_tokens"] == 20


def test_native_agent_context_usage_prefers_session_aggregate(monkeypatch) -> None:
    monkeypatch.setattr(context_usage, "find_configured_model", lambda model_id: {
        "id": model_id,
        "context_window": 2_000,
    })

    usage = context_usage.resolve_native_agent_context_usage(
        session_id="sess-1",
        model_id="jojocode/gpt-5.4",
        session_payload={
            "tokens": {
                "input": 500,
                "cache_read": 200,
                "cache_write": 100,
                "output": 40,
            },
        },
        messages=[
            {"role": "assistant", "tokens": {"input": 10, "cache_read": 5}},
        ],
    )

    assert usage is not None
    assert usage["source"] == "native_agent_session_tokens"
    assert usage["scope"] == "session"
    assert usage["context_used"] == 800
    assert usage["context_used_percent"] == 40


def test_native_agent_context_usage_unknown_window_keeps_details(monkeypatch) -> None:
    monkeypatch.setattr(context_usage, "find_configured_model", lambda _model_id: None)

    usage = context_usage.resolve_native_agent_context_usage(
        session_id="sess-1",
        model_id="missing/model",
        messages=[{"role": "assistant", "usage": {"input_tokens": 10, "cache_read": 5}}],
    )

    assert usage is not None
    assert usage["context_used"] == 15
    assert "context_window" not in usage
    assert "context_used_percent" not in usage
