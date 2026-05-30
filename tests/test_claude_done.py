import pytest


def test_build_claude_done_session_appends_nonce_sentinel_to_prompt():
    from bot.claude_done import build_claude_done_session

    session = build_claude_done_session(
        "hello",
        cli_type="claude",
        enabled=True,
        quiet_seconds=2.0,
        sentinel_mode="nonce",
        nonce="abc123",
    )

    assert session.enabled is True
    assert session.sentinel == "__TCB_DONE_abc123__"
    assert session.quiet_seconds == pytest.approx(2.0)
    assert session.prompt_text.startswith("hello")
    assert "__TCB_DONE_abc123__" in session.prompt_text


def test_detector_completes_after_quiet_window():
    from bot.claude_done import ClaudeDoneDetector

    detector = ClaudeDoneDetector("__TCB_DONE_test__", quiet_seconds=0.2)

    detector.observe_text("hello\n__TCB_DONE_test__", now=1.0)

    assert detector.state == "done_pending"
    assert detector.poll(now=1.1) is False
    assert detector.poll(now=1.3) is True
    assert detector.state == "completed"


