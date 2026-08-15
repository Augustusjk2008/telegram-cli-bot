import ast
import logging
from pathlib import Path

import pytest


def _logger_calls(path: str) -> list[tuple[str, str]]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    calls: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            continue
        calls.append((node.func.attr, node.args[0].value))
    return calls


def test_startup_summary_is_compact() -> None:
    import bot.main as main_module

    class Messages:
        @staticmethod
        def get(section: str, key: str) -> str:
            assert (section, key) == ("startup", "title")
            return "  🤖 CLI Bridge Bot"

    lines = main_module._startup_summary_lines(Messages())

    assert lines == (
        f"🤖 CLI Bridge Bot · {main_module.APP_VERSION} · {main_module.CLI_TYPE}",
        f"工作目录: {main_module.WORKING_DIR}",
    )


def test_session_restore_details_are_debug_only(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    temp_dir: Path,
) -> None:
    import bot.sessions as session_module

    monkeypatch.setattr(session_module, "migrate_sessions_to_shared", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        session_module,
        "load_session",
        lambda *_args, **_kwargs: {
            "codex_session_id": "restored-session",
            "working_dir": str(temp_dir),
            "local_history_backend": session_module.LOCAL_HISTORY_BACKEND,
        },
    )
    caplog.set_level(logging.DEBUG, logger="bot.sessions")

    session_module.get_or_create_session(9010, "quiet", 100, str(temp_dir))

    records = [record for record in caplog.records if record.message.startswith("已恢复会话:")]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG


def test_routine_web_connection_logs_are_debug_only() -> None:
    calls = _logger_calls("bot/web/server.py")
    expected_fragments = (
        "Web SSE 客户端已断开",
        "终端 WebSocket 请求到达",
        "终端 WebSocket attach 成功",
        "Web API 已启动",
    )

    for fragment in expected_fragments:
        levels = {level for level, message in calls if fragment in message}
        assert levels == {"debug"}
