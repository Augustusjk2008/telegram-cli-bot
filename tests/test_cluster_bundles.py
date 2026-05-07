from __future__ import annotations

from pathlib import Path

import pytest

from bot.cluster.bundles import (
    ClusterBundleError,
    build_cluster_bundle_diff,
    build_cluster_bundle_schema,
    get_cluster_template,
    load_cluster_template_catalog,
    normalize_cluster_bundle,
)
from bot.manager import MultiBotManager
from bot.models import BotProfile


def test_load_default_cluster_template_catalog():
    catalog = load_cluster_template_catalog()
    ids = [item["id"] for item in catalog["templates"]]
    first = catalog["templates"][0]
    assert ids == ["full_test", "code_review", "feature_dev", "research_plan"]
    assert first["name"] == "全量测试集群"


def test_load_cluster_template_catalog_from_custom_file(tmp_path: Path):
    config_path = tmp_path / "cluster_templates.json"
    config_path.write_text(
        """
{
  "version": 1,
  "templates": [
    {
      "id": "custom_review",
      "name": "自定义审查",
      "description": "说明",
      "cluster": {
        "enabled": true,
        "write_policy": "main_only",
        "conflict_policy": "snapshot_diff",
        "max_parallel_agents": 2,
        "default_timeout_seconds": 600,
        "model_tiers": { "low": "", "medium": "", "high": "" }
      },
      "agents": [
        {
          "id": "reviewer",
          "name": "代码审查",
          "system_prompt": "先审查",
          "enabled": true,
          "cluster": {
            "allow_cluster": true,
            "allow_write": false,
            "session_policy": "ephemeral",
            "timeout_seconds": 600
          }
        }
      ]
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    catalog = load_cluster_template_catalog(config_path)
    assert [item["id"] for item in catalog["templates"]] == ["custom_review"]


def test_normalize_cluster_bundle_rejects_duplicate_agents():
    with pytest.raises(ClusterBundleError) as exc_info:
        normalize_cluster_bundle({
            "cluster": {"enabled": True},
            "agents": [
                {"id": "tester", "name": "测试", "system_prompt": "a", "cluster": {}},
                {"id": "tester", "name": "测试2", "system_prompt": "b", "cluster": {}},
            ],
        })
    assert exc_info.value.code == "cluster_bundle_agent_id_duplicate"


def test_normalize_cluster_bundle_rejects_write_agent_with_main_only_policy():
    with pytest.raises(ClusterBundleError) as exc_info:
        normalize_cluster_bundle({
            "cluster": {"enabled": True, "write_policy": "main_only"},
            "agents": [
                {
                    "id": "implementer",
                    "name": "实现",
                    "system_prompt": "写代码",
                    "cluster": {"allow_write": True},
                }
            ],
        })
    assert exc_info.value.code == "cluster_bundle_write_policy_conflict"


def test_get_cluster_template_returns_full_bundle():
    bundle = get_cluster_template("code_review")
    assert bundle["id"] == "code_review"
    assert bundle["cluster"]["enabled"] is True
    assert {agent["id"] for agent in bundle["agents"]} == {"reviewer", "security-reviewer", "test-planner"}


def test_cluster_bundle_schema_contains_llm_instructions():
    schema = build_cluster_bundle_schema()
    assert schema["version"] == 1
    assert "只输出 JSON bundle" in schema["instructions"]
    assert schema["schema"]["properties"]["agents"]["maxItems"] == 8


def test_build_cluster_bundle_diff_reports_destructive_changes():
    profile = BotProfile.from_dict(
        {
            "alias": "main",
            "agents": [
                {
                    "id": "legacy",
                    "name": "旧 agent",
                    "system_prompt": "旧提示",
                    "enabled": True,
                    "cluster": {"allow_cluster": True, "allow_write": False, "session_policy": "persistent", "timeout_seconds": 600},
                }
            ],
        }
    )
    bundle = normalize_cluster_bundle({
        "id": "custom_review",
        "name": "自定义",
        "cluster": {"enabled": True, "write_policy": "main_only"},
        "agents": [
            {
                "id": "tester",
                "name": "测试",
                "system_prompt": "跑测试",
                "enabled": True,
                "cluster": {"allow_cluster": True, "allow_write": False, "session_policy": "ephemeral", "timeout_seconds": 600},
            }
        ],
    })
    diff = build_cluster_bundle_diff(profile, bundle)
    assert diff["delete_agents"] == ["legacy"]
    assert diff["create_agents"] == ["tester"]
    assert diff["overwrites_agents"] is True


@pytest.mark.asyncio
async def test_replace_bot_cluster_bundle_overwrites_child_agents(temp_dir: Path):
    storage = temp_dir / "managed_bots.json"
    storage.write_text('{"bots":[]}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(temp_dir)), str(storage))
    await manager.create_bot_agent("main", {"id": "legacy", "name": "旧 agent", "system_prompt": "旧提示"})
    result = await manager.replace_bot_cluster_bundle(
        "main",
        {
            "enabled": True,
            "write_policy": "main_only",
            "conflict_policy": "snapshot_diff",
            "max_parallel_agents": 2,
            "default_timeout_seconds": 600,
            "model_tiers": {"low": "", "medium": "", "high": ""},
        },
        [
            {
                "id": "tester",
                "name": "测试专家",
                "system_prompt": "跑测试",
                "enabled": True,
                "cluster": {"allow_cluster": True, "allow_write": False, "session_policy": "ephemeral", "timeout_seconds": 600},
            }
        ],
    )
    assert result["cluster"]["enabled"] is True
    assert [item["id"] for item in result["agents"]] == ["tester"]
    assert [item["id"] for item in manager.list_bot_agents("main")] == ["main", "tester"]
