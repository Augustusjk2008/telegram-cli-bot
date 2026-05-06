from bot.cluster_config import (
    AgentClusterConfig,
    BotClusterConfig,
    normalize_agent_cluster_config,
    normalize_bot_cluster_config,
)


def test_bot_cluster_config_defaults():
    config = normalize_bot_cluster_config(None)
    assert config == BotClusterConfig()
    assert config.enabled is False
    assert config.write_policy == "selected_agents"
    assert config.conflict_policy == "snapshot_diff"
    assert config.max_parallel_agents == 2
    assert config.model_tiers == {"low": "", "medium": "", "high": ""}


def test_bot_cluster_config_normalizes_invalid_values():
    config = normalize_bot_cluster_config(
        {
            "enabled": True,
            "write_policy": "invalid",
            "conflict_policy": "invalid",
            "max_parallel_agents": -1,
            "default_timeout_seconds": 0,
        }
    )
    assert config.enabled is True
    assert config.write_policy == "selected_agents"
    assert config.conflict_policy == "snapshot_diff"
    assert config.max_parallel_agents == 1
    assert config.default_timeout_seconds == 60


def test_agent_cluster_config_roundtrip():
    config = normalize_agent_cluster_config(
        {
            "allow_cluster": True,
            "allow_write": True,
            "session_policy": "persistent",
            "timeout_seconds": 120,
        }
    )
    assert config == AgentClusterConfig(
        allow_cluster=True,
        allow_write=True,
        session_policy="persistent",
        timeout_seconds=120,
    )
    assert config.to_dict() == {
        "allow_cluster": True,
        "allow_write": True,
        "session_policy": "persistent",
        "timeout_seconds": 120,
    }


def test_bot_cluster_config_model_tiers_roundtrip():
    config = normalize_bot_cluster_config(
        {
            "model_tiers": {
                "low": "gpt-5.4-mini",
                "medium": "gpt-5.4",
                "high": "gpt-5.5",
                "unused": "ignored",
            }
        }
    )
    assert config.model_tiers == {
        "low": "gpt-5.4-mini",
        "medium": "gpt-5.4",
        "high": "gpt-5.5",
    }
