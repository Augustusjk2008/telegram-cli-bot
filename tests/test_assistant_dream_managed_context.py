from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot.assistant_dream_managed_context import collect_managed_bot_dream_context
from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession


class _FakeHistoryService:
    def __init__(self, items_by_alias: dict[str, list[dict]]):
        self.items_by_alias = items_by_alias

    def list_history(self, profile, session, limit=50):
        return list(self.items_by_alias.get(profile.alias, []))[:limit]


def _session_for_alias(alias: str, user_id: int, working_dir: str) -> UserSession:
    return UserSession(
        bot_id=-100,
        bot_alias=alias,
        user_id=user_id,
        working_dir=working_dir,
        _persist_enabled=False,
    )


def test_collect_managed_bot_dream_context_reads_other_bot_history_and_captures(temp_dir: Path):
    root = temp_dir / "workspace"
    root.mkdir()
    assistant_dir = root / "assistant"
    team_dir = root / "team2"
    host_dir = root / "host"
    assistant_dir.mkdir()
    team_dir.mkdir()
    host_dir.mkdir()
    capture_dir = team_dir / ".assistant" / "inbox" / "captures"
    capture_dir.mkdir(parents=True)

    recent_time = datetime.now(UTC).isoformat()
    old_time = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    (capture_dir / "cap-1.json").write_text(
        json.dumps(
            {
                "id": "cap-1",
                "created_at": recent_time,
                "user_text": "team2 用户要求看板联动",
                "assistant_text": "team2 已记录联动设计",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (capture_dir / "cap-old.json").write_text(
        json.dumps(
            {
                "id": "cap-old",
                "created_at": old_time,
                "user_text": "旧 capture",
                "assistant_text": "不应进入上下文",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manager = MultiBotManager(
        BotProfile(alias="main", working_dir=str(host_dir)),
        str(root / "bots.json"),
    )
    manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(assistant_dir),
        enabled=True,
        bot_mode="assistant",
    )
    manager.managed_profiles["team2"] = BotProfile(
        alias="team2",
        token="",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(team_dir),
        enabled=True,
        bot_mode="cli",
    )
    history_service = _FakeHistoryService(
        {
            "team2": [
                {"role": "user", "content": "team2 最近修了 UI", "created_at": recent_time},
                {"role": "assistant", "content": "旧消息", "created_at": old_time},
            ]
        }
    )

    result = collect_managed_bot_dream_context(
        manager,
        current_alias="assistant1",
        context_user_id=1001,
        lookback_hours=24,
        history_limit=10,
        capture_limit=5,
        session_resolver=lambda alias, user_id: _session_for_alias(alias, user_id, str(team_dir)),
        history_service_factory=lambda session: history_service,
    )

    assert "### team2" in result.text
    assert "team2 最近修了 UI" in result.text
    assert "team2 用户要求看板联动" in result.text
    assert "旧消息" not in result.text
    assert "旧 capture" not in result.text
    assert "### assistant1" not in result.text
    assert result.stats["managed_bot_count"] == 1
    assert result.stats["managed_history_count"] == 1
    assert result.stats["managed_capture_count"] == 1
    assert result.stats["managed_error_count"] == 0


def test_collect_managed_bot_dream_context_keeps_errors_per_bot(temp_dir: Path):
    root = temp_dir / "workspace"
    root.mkdir()
    assistant_dir = root / "assistant"
    broken_dir = root / "broken"
    host_dir = root / "host"
    assistant_dir.mkdir()
    broken_dir.mkdir()
    host_dir.mkdir()
    manager = MultiBotManager(
        BotProfile(alias="main", working_dir=str(host_dir)),
        str(root / "bots.json"),
    )
    manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        working_dir=str(assistant_dir),
        bot_mode="assistant",
    )
    manager.managed_profiles["broken"] = BotProfile(
        alias="broken",
        working_dir=str(broken_dir),
        bot_mode="cli",
    )

    def _raise_session(alias: str, user_id: int):
        raise RuntimeError("session unavailable")

    result = collect_managed_bot_dream_context(
        manager,
        current_alias="assistant1",
        context_user_id=1001,
        lookback_hours=24,
        history_limit=10,
        capture_limit=5,
        session_resolver=_raise_session,
        history_service_factory=lambda session: _FakeHistoryService({}),
    )

    assert "### broken" in result.text
    assert "error: session unavailable" in result.text
    assert result.stats["managed_bot_count"] == 1
    assert result.stats["managed_history_count"] == 0
    assert result.stats["managed_capture_count"] == 0
    assert result.stats["managed_error_count"] == 1
