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


def test_build_claude_done_session_returns_original_prompt_when_disabled():
    from bot.claude_done import build_claude_done_session

    session = build_claude_done_session(
        "hello",
        cli_type="claude",
        enabled=False,
        quiet_seconds=2.0,
        sentinel_mode="nonce",
    )

    assert session.enabled is False
    assert session.sentinel is None
    assert session.prompt_text == "hello"


def test_strip_claude_done_sentinel_removes_only_exact_matching_line():
    from bot.claude_done import strip_claude_done_sentinel

    sentinel = "__TCB_DONE_test__"
    text = f"line 1\n{sentinel}\nline 2\n__TCB_DONE_other__"

    assert strip_claude_done_sentinel(text, sentinel) == "line 1\nline 2\n__TCB_DONE_other__"


def test_detector_completes_after_quiet_window():
    from bot.claude_done import ClaudeDoneDetector

    detector = ClaudeDoneDetector("__TCB_DONE_test__", quiet_seconds=0.2)

    detector.observe_text("hello\n__TCB_DONE_test__", now=1.0)

    assert detector.state == "done_pending"
    assert detector.poll(now=1.1) is False
    assert detector.poll(now=1.3) is True
    assert detector.state == "completed"


def test_detector_cancels_pending_when_new_nonempty_text_arrives():
    from bot.claude_done import ClaudeDoneDetector

    detector = ClaudeDoneDetector("__TCB_DONE_test__", quiet_seconds=0.2)

    detector.observe_text("hello\n__TCB_DONE_test__", now=1.0)
    detector.observe_text("hello\n__TCB_DONE_test__\nmore", now=1.1)

    assert detector.state == "idle"
    assert detector.poll(now=1.4) is False


def test_collector_detects_split_sentinel_and_strips_preview_and_final_text():
    from bot.claude_done import ClaudeDoneCollector, build_claude_done_session

    done_session = build_claude_done_session(
        "hello",
        cli_type="claude",
        enabled=True,
        quiet_seconds=0.2,
        sentinel_mode="nonce",
        nonce="abc123",
    )
    collector = ClaudeDoneCollector(done_session)

    collector.consume_chunk(
        '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"你好\\n__TCB_"}}}\n',
        now=1.0,
    )
    collector.consume_chunk(
        '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"DONE_abc123__"}}}\n',
        now=1.1,
    )
    collector.consume_chunk(
        '{"type":"result","subtype":"success","session_id":"sess-1","result":"你好\\n__TCB_DONE_abc123__"}\n',
        now=1.1,
    )

    assert collector.session_id == "sess-1"
    assert collector.preview_text == "你好"
    assert collector.final_text == "你好"
    assert collector.detector is not None
    assert collector.detector.state == "done_pending"
    assert collector.detector.poll(now=1.4) is True
