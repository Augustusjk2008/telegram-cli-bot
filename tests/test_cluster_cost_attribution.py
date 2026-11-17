from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.cluster.config import normalize_bot_cluster_config
from bot.cluster.runtime import ClusterRuntime
from bot.cluster.team_service import _run_request
from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile
from bot.web import api_service


class _Stdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)

    def readline(self, _size: int = -1) -> str:
        return next(self._lines, "")

    def close(self) -> None:
        pass


class _ClaudeProcess:
    def __init__(self) -> None:
        result = {
            "type": "result", "result": "done", "session_id": "child-session", "result_index": 0,
            "total_cost_usd": 9.0, "usage": {"input_tokens": 1, "output_tokens": 1},
            "modelUsage": {"claude-opus-5-5": {"costUSD": 9.0}},
            "model_usage_since_last_result": {"claude-opus-5-5": {"costUSD": 1.5}},
        }
        self.stdout = _Stdout([
            json.dumps({"type": "system", "subtype": "init", "session_id": "child-session"}) + "\n",
            json.dumps(result) + "\n",
        ])
        self.stdin = None
        self.returncode = None
        self.pid = 4321

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _start_run(profile: BotProfile, actor: dict) -> object:
    return api_service._start_cluster_run_if_requested(
        profile=profile,
        alias="main",
        shared_user_id=1001,
        cluster=False,
        execution_mode="cli",
        mentions=[],
        allow_unsafe_cli=False,
        main_conversation_id="conv_main",
        team_state={"cluster_team_revision": 0, "cluster_team": {"version": 1, "assignments": [{
            "agent_id": "worker", "name": "Reviewer", "responsibility": "Review", "assignment_revision": 1,
        }]}},
        cost_user=api_service._cost_stats_user_from_actor(actor),
    )


@pytest.mark.asyncio
async def test_cluster_child_cost_is_attributed_to_the_account_that_queued_it(tmp_path: Path, monkeypatch):
    import bot.cost_stats as cost_stats
    from bot.cost_stats.service import CostStatsService

    stats = CostStatsService(db_path=tmp_path / "cost-stats" / "cost.sqlite3")
    monkeypatch.setattr(cost_stats, "_service", stats)
    await stats.set_enabled("claude", True)
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(tmp_path),
        enabled=True,
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=normalize_bot_cluster_config({"enabled": True}),
    )
    manager = MultiBotManager(profile, str(storage))
    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "_CLUSTER_RUN_CONTROLS", {})
    monkeypatch.setattr(api_service, "_ensure_cluster_child_conversation", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "claude")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["claude"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service, "_reconcile_native_trace_before_completion", AsyncMock())
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: _ClaudeProcess())

    run = _start_run(profile, {"user_id": 7, "account_id": "acc-alice", "username": "alice"})
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "worker", "message": "review"})
    task = runtime.create_agent_task(run.run_id, request)
    # A later main turn by another account re-attributes only tasks queued after it.
    _start_run(profile, {"user_id": 8, "account_id": "acc-bob"})

    await api_service._run_cluster_agent_task(manager, run.run_id, task.task_id)

    assert task.status == "completed", task.error
    with sqlite3.connect(stats.db_path) as connection:
        rows = connection.execute("SELECT provider, bot_alias, agent_id, user, amount FROM cost_events").fetchall()
    assert rows == [("claude", "main", "worker", "alice", 1.5)]
    assert run.cost_user == "acc-bob"
    assert _run_request(run, profile=profile, team=run.team, team_revision=1).cost_user == "acc-bob"


@pytest.mark.asyncio
async def test_parent_wakeup_cost_is_attributed_to_the_account_behind_the_finished_task(tmp_path: Path, monkeypatch):
    import bot.cost_stats as cost_stats
    from bot.cost_stats.service import CostStatsService

    stats = CostStatsService(db_path=tmp_path / "cost-stats" / "cost.sqlite3")
    monkeypatch.setattr(cost_stats, "_service", stats)
    await stats.set_enabled("claude", True)
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(tmp_path),
        enabled=True,
        agents=[AgentProfile(id="worker", name="Worker")],
        cluster=normalize_bot_cluster_config({"enabled": True}),
    )
    manager = MultiBotManager(profile, str(storage))
    runtime = ClusterRuntime()
    monkeypatch.setattr(api_service, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api_service, "_CLUSTER_RUN_CONTROLS", {})
    monkeypatch.setattr(api_service, "_require_current_cluster_team", lambda *_args: None)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "claude")
    monkeypatch.setattr(api_service, "build_cli_command", lambda **_kwargs: (["claude"], False))
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_service, "_reconcile_native_trace_before_completion", AsyncMock())
    monkeypatch.setattr(api_service.subprocess, "Popen", lambda *_args, **_kwargs: _ClaudeProcess())
    conversation_id, _team_state = await api_service._ensure_cluster_main_conversation(
        manager, profile, "main", 1001, "cli",
    )
    run = api_service._start_cluster_run_if_requested(
        profile=profile,
        alias="main",
        shared_user_id=1001,
        cluster=False,
        execution_mode="cli",
        mentions=[],
        allow_unsafe_cli=False,
        main_conversation_id=conversation_id,
        team_state={"cluster_team_revision": 0, "cluster_team": {"version": 1, "assignments": [{
            "agent_id": "worker", "name": "Reviewer", "responsibility": "Review", "assignment_revision": 1,
        }]}},
        cost_user="alice",
    )
    request = runtime.validate_ask_agent(run.run_id, {"agent_id": "worker", "message": "review"})
    task = runtime.create_agent_task(run.run_id, request, parent_conversation_id=conversation_id)
    runtime.mark_agent_task_running(run.run_id, task.task_id)
    runtime.complete_agent_task(run.run_id, task.task_id, "done")
    task.wakeup_pending = True
    run.pending_parent_wakeup_task_ids.add(task.task_id)
    # The account of the latest main turn differs; the wake-up reads alice's work.
    run.cost_user = "bob"

    assert await api_service._run_cluster_parent_wakeup(manager, run.run_id) is True

    with sqlite3.connect(stats.db_path) as connection:
        rows = connection.execute("SELECT agent_id, user, conversation_id FROM cost_events").fetchall()
    assert rows == [("main", "alice", conversation_id)]
    _profile, _agent, session = api_service.get_chat_session_for_alias(manager, "main", 1001, "main")
    chat_db = api_service._get_chat_store(session).db_path
    with sqlite3.connect(chat_db) as connection:
        authors = connection.execute(
            "SELECT author_user_id, author_account_id, author_username FROM messages "
            "WHERE role = 'user' AND content LIKE '[TCB cluster completion]%'"
        ).fetchall()
    assert authors == [(None, None, None)]
