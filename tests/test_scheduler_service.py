from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot import config
from bot.models import BotProfile
from bot.scheduler import notify_bot_removed, notify_bot_renamed
from bot.scheduler.service import SchedulerService
from bot.scheduler.store import ScheduleStore
from bot.web import api_service
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_RUN_UNSAFE_CLI

NOW = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
ADMIN = {"account_id": "admin-1", "username": "admin", "can_allow_unsafe_cli": True}
LIMITED = {"account_id": "ops-1", "username": "ops", "can_allow_unsafe_cli": False}


def _profile(alias: str, *, enabled: bool = True, archived: bool = False) -> BotProfile:
    return BotProfile(alias=alias, enabled=enabled, archived=archived, cli_type="codex")


class FakeChat:
    """Stands in for the shared chat path used by the scheduler."""

    def __init__(self) -> None:
        self.phases: list[str] = []
        self.created: list[dict[str, Any]] = []
        self.streams: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] | None = None

    async def snapshot(self, _manager, alias, _user_id, *, agent_id="main"):
        return {"phase": self.phases.pop(0) if self.phases else "idle", "conversation_id": "conv_old"}

    async def create_conversation(self, _manager, alias, _user_id, title="", agent_id="main", **kwargs):
        conversation_id = f"conv_{len(self.created) + 1}"
        self.created.append({"alias": alias, "title": title, "agent_id": agent_id, **kwargs})
        return {"conversation": {"id": conversation_id}}

    def stream_chat(self, _manager, alias, _user_id, text, **kwargs):
        self.streams.append({"alias": alias, "text": text, **kwargs})
        conversation_id = kwargs["expected_conversation_id"]
        events = self.events if self.events is not None else [
            {"type": "meta", "turn_id": "turn_1", "assistant_message_id": "msg_1", "conversation_id": conversation_id},
            {"type": "status", "turn_id": "turn_1", "assistant_message_id": "msg_1"},
            {
                "type": "done",
                "turn_id": "turn_1",
                "assistant_message_id": "msg_1",
                "message": {"content": "巡检完成：一切正常", "meta": {"completion_state": "completed"}},
            },
        ]

        async def generate():
            for event in events:
                yield event

        return generate()


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> FakeChat:
    fake = FakeChat()
    monkeypatch.setattr(api_service, "get_conversation_control_snapshot", fake.snapshot)
    monkeypatch.setattr(api_service, "create_conversation", fake.create_conversation)
    monkeypatch.setattr(api_service, "stream_chat", fake.stream_chat)
    monkeypatch.setattr(config, "UPDATE_DRAINING", False)
    monkeypatch.setattr(config, "UPDATE_REQUESTED", False)
    monkeypatch.setattr(config, "RESTART_REQUESTED", False)
    return fake


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _service(tmp_path: Path, *, capabilities: dict[str, set[str]] | None = None, clock: Clock | None = None,
             profiles: list[BotProfile] | None = None) -> SchedulerService:
    items = profiles or [_profile("main"), _profile("dev")]
    manager = SimpleNamespace(main_profile=items[0], managed_profiles={p.alias: p for p in items[1:]})
    caps = capabilities if capabilities is not None else {"admin-1": {CAP_ADMIN_OPS, CAP_RUN_UNSAFE_CLI}}
    return SchedulerService(
        manager,
        ScheduleStore(tmp_path / "scheduler.sqlite3"),
        capability_resolver=lambda account_id: caps.get(account_id),
        busy_retry_seconds=0,
        clock=clock or Clock(NOW),
        default_timezone="Asia/Shanghai",
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "每日巡检",
        "bot_alias": "dev",
        "prompt": "检查仓库状态并汇报",
        "trigger": {"type": "daily", "time": "09:00", "weekdays": [1, 2, 3, 4, 5]},
        "timezone": "Asia/Shanghai",
    }
    payload.update(overrides)
    return payload


async def _drain(service: SchedulerService) -> None:
    while service._run_tasks:
        await asyncio.gather(*list(service._run_tasks.values()), return_exceptions=True)


async def _fire(service: SchedulerService, clock: Clock, schedule: dict[str, Any], *, late: timedelta = timedelta()) -> None:
    clock.value = datetime.fromisoformat(service.store.require_schedule(schedule["id"])["next_run_at"]) + late
    await service._tick()
    await _drain(service)


@pytest.mark.asyncio
async def test_due_schedule_runs_once_in_new_conversation(tmp_path: Path, chat: FakeChat) -> None:
    clock = Clock(NOW)
    service = _service(tmp_path, clock=clock)
    schedule = await service.create(_payload(), ADMIN)
    # Monday 2026-11-16 09:00 Asia/Shanghai.
    assert schedule["next_run_at"] == "2026-11-16T01:00:00+00:00"

    await _fire(service, clock, schedule)
    await service._tick()
    await _drain(service)

    assert len(chat.created) == 1
    assert chat.created[0]["follow_current_conversation"] is True
    assert chat.created[0]["title"].startswith("⏰ 每日巡检")
    stream = chat.streams[0]
    assert stream["text"] == "检查仓库状态并汇报"
    assert stream["expected_conversation_id"] == "conv_1"
    assert stream["source_channel"] == "schedule"
    assert stream["allow_unsafe_cli"] is False
    [run] = service.store.list_runs(schedule["id"])
    assert run["status"] == "completed"
    assert (run["conversation_id"], run["turn_id"], run["assistant_message_id"]) == ("conv_1", "turn_1", "msg_1")
    assert run["preview"] == "巡检完成：一切正常"
    assert service.store.require_schedule(schedule["id"])["next_run_at"] == "2026-11-17T01:00:00+00:00"


@pytest.mark.asyncio
async def test_misfire_beyond_grace_is_recorded_once_without_running(tmp_path: Path, chat: FakeChat) -> None:
    clock = Clock(NOW)
    service = _service(tmp_path, clock=clock)
    schedule = await service.create(_payload(misfire_grace_minutes=10), ADMIN)

    await _fire(service, clock, schedule, late=timedelta(hours=3))

    assert chat.created == []
    [run] = service.store.list_runs(schedule["id"])
    assert (run["status"], run["reason_code"]) == ("missed", "misfire")
    assert service.store.require_schedule(schedule["id"])["next_run_at"] == "2026-11-17T01:00:00+00:00"


@pytest.mark.asyncio
async def test_busy_policy_waits_for_idle_or_skips(tmp_path: Path, chat: FakeChat) -> None:
    clock = Clock(NOW)
    service = _service(tmp_path, clock=clock)
    waiting = await service.create(_payload(busy_policy="wait", max_wait_minutes=5), ADMIN)
    chat.phases = ["running", "idle"]
    await _fire(service, clock, waiting)
    assert service.store.list_runs(waiting["id"])[0]["status"] == "completed"

    skipping = await service.create(
        _payload(name="忙碌跳过", busy_policy="skip", trigger={"type": "daily", "time": "10:00"}), ADMIN,
    )
    chat.phases = ["running"]
    await _fire(service, clock, skipping)
    [run] = service.store.list_runs(skipping["id"])
    assert (run["status"], run["reason_code"]) == ("skipped", "target_busy")
    assert len(chat.created) == 1


@pytest.mark.asyncio
async def test_full_chat_pool_skips_before_switching_and_waits_until_a_slot_is_free(tmp_path: Path, chat: FakeChat):
    from dataclasses import replace

    clock = Clock(NOW)
    service = _service(tmp_path, clock=clock)
    profile = service.manager.managed_profiles["dev"]
    profile.cluster = replace(profile.cluster, max_parallel_agents=1)
    skip = await service.create(_payload(busy_policy="skip"), ADMIN)
    with api_service.reserve_bot_chat_slot(service.manager, profile, "@named"):
        await _fire(service, clock, skip)
    assert service.store.list_runs(skip["id"])[0]["reason_code"] == "target_busy"
    assert chat.created == []

    wait = await service.create(_payload(name="等待容量", busy_policy="wait"), ADMIN)
    with api_service.reserve_bot_chat_slot(service.manager, profile, "@named"):
        clock.value = datetime.fromisoformat(service.store.require_schedule(wait["id"])["next_run_at"])
        await service._tick()
        async def waiting():
            while service.store.list_runs(wait["id"])[0]["status"] != "waiting":
                await asyncio.sleep(0.01)
        await asyncio.wait_for(waiting(), 4)
        assert chat.created == []
    await _drain(service)
    assert service.store.list_runs(wait["id"])[0]["status"] == "completed"
    assert len(chat.created) == 1 and chat.streams[0]["reserved_slot"].scope == "main"


@pytest.mark.asyncio
async def test_unavailable_target_and_paused_host_do_not_run(
    tmp_path: Path, chat: FakeChat, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock(NOW)
    dev = _profile("dev")
    service = _service(tmp_path, clock=clock, profiles=[_profile("main"), dev])
    schedule = await service.create(_payload(), ADMIN)

    dev.archived = True
    await _fire(service, clock, schedule)
    assert service.store.list_runs(schedule["id"])[0]["reason_code"] == "target_unavailable"

    dev.archived = False
    monkeypatch.setattr(config, "UPDATE_DRAINING", True)
    before = service.store.require_schedule(schedule["id"])["next_run_at"]
    await _fire(service, clock, schedule)
    assert service.store.require_schedule(schedule["id"])["next_run_at"] == before
    with pytest.raises(WebApiError) as exc_info:
        await service.run_now(schedule["id"])
    assert exc_info.value.code == "scheduler_paused"
    assert chat.created == []


@pytest.mark.asyncio
async def test_stream_preempted_and_once_schedule_disables_itself(tmp_path: Path, chat: FakeChat) -> None:
    clock = Clock(NOW)
    service = _service(tmp_path, clock=clock)
    schedule = await service.create(
        _payload(trigger={"type": "once", "at": "2026-11-16T12:00:00+08:00"}), ADMIN,
    )
    chat.events = [{"type": "error", "code": "conversation_changed", "message": "当前会话已变化"}]

    await _fire(service, clock, schedule)

    [run] = service.store.list_runs(schedule["id"])
    assert (run["status"], run["reason_code"]) == ("failed", "preempted")
    stored = service.store.require_schedule(schedule["id"])
    assert (stored["enabled"], stored["disabled_reason"], stored["next_run_at"]) == (False, "once_finished", None)


@pytest.mark.asyncio
async def test_unsafe_flag_requires_capability_and_is_rechecked_at_run_time(tmp_path: Path, chat: FakeChat) -> None:
    capabilities = {"admin-1": {CAP_ADMIN_OPS, CAP_RUN_UNSAFE_CLI}}
    service = _service(tmp_path, capabilities=capabilities)

    with pytest.raises(WebApiError) as exc_info:
        await service.create(_payload(allow_unsafe_cli=True), LIMITED)
    assert exc_info.value.code == "schedule_unsafe_forbidden"

    schedule = await service.create(_payload(allow_unsafe_cli=True), ADMIN)
    # Editing what runs needs the capability; cosmetic edits do not.
    with pytest.raises(WebApiError):
        await service.update(schedule["id"], {"revision": schedule["revision"], "prompt": "rm -rf"}, LIMITED)
    renamed = await service.update(schedule["id"], {"revision": schedule["revision"], "name": "改名"}, LIMITED)
    assert renamed["name"] == "改名"

    await service.run_now(schedule["id"])
    await _drain(service)
    assert chat.streams[-1]["allow_unsafe_cli"] is True

    capabilities["admin-1"] = {CAP_ADMIN_OPS}
    await service.run_now(schedule["id"])
    await _drain(service)
    assert chat.streams[-1]["allow_unsafe_cli"] is False
    assert service.store.list_runs(schedule["id"])[0]["unsafe_downgraded"] is True


@pytest.mark.asyncio
async def test_revision_conflict_and_validation(tmp_path: Path, chat: FakeChat) -> None:
    service = _service(tmp_path)
    schedule = await service.create(_payload(), ADMIN)
    await service.update(schedule["id"], {"revision": schedule["revision"], "enabled": False}, ADMIN)

    with pytest.raises(WebApiError) as conflict:
        await service.update(schedule["id"], {"revision": schedule["revision"], "name": "x"}, ADMIN)
    assert conflict.value.status == 409 and conflict.value.code == "schedule_conflict"

    for payload in (_payload(bot_alias="missing"), _payload(prompt="  "), _payload(timezone="Nowhere/City"),
                    _payload(trigger={"type": "once", "at": "2026-01-01T00:00:00+00:00"})):
        with pytest.raises(WebApiError) as invalid:
            await service.create(payload, ADMIN)
        assert invalid.value.code == "invalid_schedule"


@pytest.mark.asyncio
async def test_restart_marks_unfinished_runs_interrupted(tmp_path: Path, chat: FakeChat) -> None:
    service = _service(tmp_path)
    schedule = await service.create(_payload(), ADMIN)
    stale = service.store.claim_run(schedule["id"], planned_at="2026-11-16T01:00:00+00:00",
                                    trigger="schedule", bot_alias="dev")
    service.store.update_run(stale["id"], status="running")

    restarted = _service(tmp_path)
    restarted._recover()

    run = restarted.store.get_run(stale["id"])
    assert (run["status"], run["reason_code"]) == ("interrupted", "host_restarted")


@pytest.mark.asyncio
async def test_bot_rename_and_removal_follow_schedules(tmp_path: Path, chat: FakeChat) -> None:
    service = _service(tmp_path)
    schedule = await service.create(_payload(), ADMIN)
    await service.start()
    try:
        notify_bot_renamed("dev", "ops")
        assert service.store.require_schedule(schedule["id"])["bot_alias"] == "ops"
        notify_bot_removed("ops")
        stored = service.store.require_schedule(schedule["id"])
        assert (stored["enabled"], stored["disabled_reason"]) == (False, "bot_removed")
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_admin_routes_require_admin_ops(tmp_path: Path, chat: FakeChat, monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.web.server import WebApiServer
    from tests.test_admin_bot_api import DummyTunnelService, _build_manager

    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(_build_manager(tmp_path), host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())
    service = _service(tmp_path)
    await service.start()
    granted: set[str] = set()

    async def with_capability(_request, capability: str) -> AuthContext:
        if capability not in granted:
            raise WebApiError(403, "forbidden", "无权限")
        return AuthContext(user_id=1, token_used=True, account_id="admin-1", username="admin",
                           capabilities=set(granted))

    monkeypatch.setattr(server, "_with_capability", with_capability)
    try:
        async with TestServer(server._build_app()) as test_server:
            async with TestClient(test_server) as client:
                denied = await client.get("/api/admin/schedules")
                granted.add(CAP_ADMIN_OPS)
                created = await client.post("/api/admin/schedules", json=_payload())
                listed = await client.get("/api/admin/schedules")
                listed_payload = await listed.json()
                forbidden_unsafe = await client.post("/api/admin/schedules", json=_payload(allow_unsafe_cli=True))
    finally:
        await service.stop()

    assert denied.status == 403
    assert created.status == 200
    assert [item["name"] for item in listed_payload["data"]["items"]] == ["每日巡检"]
    assert listed_payload["data"]["can_allow_unsafe_cli"] is False
    assert {"alias": "dev", "cli_type": "codex"} in listed_payload["data"]["targets"]
    assert forbidden_unsafe.status == 403
