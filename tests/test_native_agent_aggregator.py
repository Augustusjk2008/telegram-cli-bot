from bot.native_agent.aggregator import NativeAgentAggregator
from bot.native_agent.events import unwrap_event
from bot.native_agent.pi_events import pi_json_to_events


def apply_pi(aggregator, raw):
    results = []
    for item in pi_json_to_events(raw, fallback_session_id="session-1", assistant_message_id="assistant-1"):
        event = unwrap_event(item)
        assert event is not None
        results.append(aggregator.apply(event))
    return results


def test_pi_final_message_does_not_duplicate_streamed_text_with_different_part_id():
    aggregator = NativeAgentAggregator(user_message_id="user-1")

    apply_pi(aggregator, {
        "type": "message_update",
        "message_id": "assistant-1",
        "part_id": "stream-part",
        "delta": "答案",
    })
    results = apply_pi(aggregator, {
        "type": "message",
        "id": "assistant-1",
        "part_id": "final-part",
        "role": "assistant",
        "content": "答案",
        "finish_reason": "stop",
    })

    assert aggregator.text() == "答案"
    assert all(not result.delta and not result.snapshot for result in results)

    repeated_results = apply_pi(aggregator, {
        "type": "message",
        "id": "assistant-1",
        "part_id": "final-part-replayed",
        "role": "assistant",
        "content": "答案",
        "finish_reason": "stop",
    })

    assert aggregator.text() == "答案"
    assert all(not result.delta and not result.snapshot for result in repeated_results)


def test_pi_final_message_only_emits_unseen_suffix_after_streaming():
    aggregator = NativeAgentAggregator(user_message_id="user-1")

    apply_pi(aggregator, {
        "type": "message_update",
        "message_id": "assistant-1",
        "part_id": "stream-part",
        "delta": "答",
    })
    results = apply_pi(aggregator, {
        "type": "message",
        "id": "assistant-1",
        "part_id": "final-part",
        "role": "assistant",
        "content": "答案",
        "finish_reason": "stop",
    })

    assert aggregator.text() == "答案"
    assert [result.delta for result in results if result.delta] == ["案"]


