from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import app_settings
from bot.cluster.config import normalize_bot_cluster_config
from bot.manager import MultiBotManager
from bot.models import BotProfile


def test_cluster_config_migrates_write_policy_and_serializes_version_two() -> None:
    missing = normalize_bot_cluster_config({})
    selected = normalize_bot_cluster_config({"write_policy": "selected_agents"})
    writable = normalize_bot_cluster_config({"write_policy": "all_agents"})

    assert missing.write_policy == "all_agents"
    assert missing.max_parallel_agents == 3
    assert missing.default_timeout_seconds == 1800
    assert selected.write_policy == "main_only"
    assert writable.write_policy == "all_agents"
    assert missing.to_dict()["orchestration_version"] == 2


def test_enabled_cluster_profile_normalizes_slots_idempotently() -> None:
    profile = BotProfile.from_dict(
        {
            "alias": "main",
            "cluster": {"enabled": True, "max_parallel_agents": 3},
            "agents": [
                {"id": "reviewer", "name": "审查"},
                {"id": "cluster-slot-1", "name": "旧槽位"},
            ],
        }
    )

    first = profile.to_dict()
    second = profile.to_dict()

    assert [agent.id for agent in profile.agents] == [
        "reviewer",
        "cluster-slot-1",
        "cluster-slot-2",
    ]
    assert first == second


@pytest.mark.asyncio
async def test_cluster_resize_keeps_tail_slots_and_restores_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", tmp_path / "settings.json")
    profile = BotProfile.from_dict(
        {
            "alias": "main",
            "working_dir": str(tmp_path),
            "cluster": {"enabled": True, "max_parallel_agents": 3},
            "agents": [
                {"id": "one", "name": "一"},
                {"id": "two", "name": "二"},
                {"id": "three", "name": "三"},
            ],
        }
    )
    manager = MultiBotManager(profile, str(storage))

    await manager.update_bot_cluster("main", {"enabled": True, "max_parallel_agents": 1})
    after_shrink = [agent.id for agent in profile.agents]
    await manager.update_bot_cluster("main", {"enabled": True, "max_parallel_agents": 4})

    assert after_shrink == ["one", "two", "three"]
    assert [agent.id for agent in profile.agents] == ["one", "two", "three", "cluster-slot-1"]


@pytest.mark.asyncio
async def test_enabled_cluster_rejects_legacy_agent_and_bundle_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", tmp_path / "settings.json")
    profile = BotProfile.from_dict(
        {
            "alias": "main",
            "working_dir": str(tmp_path),
            "cluster": {"enabled": True, "max_parallel_agents": 1},
            "agents": [{"id": "slot", "name": "旧名称"}],
        }
    )
    manager = MultiBotManager(profile, str(storage))

    with pytest.raises(ValueError, match="集群已启用"):
        await manager.create_bot_agent("main", {"id": "new", "name": "新"})
    with pytest.raises(ValueError, match="集群已启用"):
        await manager.update_bot_agent("main", "slot", {"name": "变化"})
    with pytest.raises(ValueError, match="集群已启用"):
        await manager.delete_bot_agent("main", "slot")
    with pytest.raises(ValueError, match="集群已启用"):
        await manager.replace_bot_cluster_bundle(
            "main",
            {"enabled": True, "max_parallel_agents": 1},
            [{"id": "replacement", "name": "替代"}],
        )
