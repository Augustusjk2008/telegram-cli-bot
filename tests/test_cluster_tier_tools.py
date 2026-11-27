from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from bot.cli_params import CliParamsConfig
from bot.cluster.config import MODEL_TIER_KEYS, normalize_bot_cluster_config
from bot.cluster.runtime import ClusterRuntime
from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile
from bot.web import api_service as api
from bot.web.api_common import WebApiError


@pytest_asyncio.fixture
async def cluster(tmp_path, monkeypatch):
    profile = BotProfile(
        alias="main", cli_type="codex", cli_path="/trusted/main", working_dir=str(tmp_path),
        agents=[AgentProfile(id="worker", name="Worker")],
        cli_params=CliParamsConfig.from_dict({
            "codex": {"model": "base", "reasoning_effort": "medium"},
            "claude": {"model": "balanced", "effort": "low", "extra_args": ["private-argument"]},
        }),
        cluster=normalize_bot_cluster_config({
            "enabled": True, "max_parallel_agents": 1,
            "model_tiers": {"high": "fast", "professional": "special"},
            "tier_configs": {"high": {"cli_path": "/trusted/high"}},
        }),
    )
    manager = MultiBotManager(profile, str(tmp_path / "bots.json"))
    runtime = ClusterRuntime()
    monkeypatch.setattr(api, "_CLUSTER_RUNTIME", runtime)
    monkeypatch.setattr(api, "_CLUSTER_RUN_CONTROLS", {})
    monkeypatch.setattr(api, "_run_cluster_agent_task", AsyncMock())
    monkeypatch.setattr(api, "resolve_cli_executable", lambda path, cwd: path)
    monkeypatch.setattr(api, "CLI_MODEL_OPTIONS", {
        "codex": ["base", "fast"], "codex_server": ["server"], "claude": ["balanced", "strong"],
        "antigravity": ["gemini-high", "gemini"], "deepseek": ["ds"],
    })
    conversation, team = await api._ensure_cluster_main_conversation(manager, profile, "main", 1, "cli")
    run = api._start_cluster_run_if_requested(
        profile=profile, alias="main", shared_user_id=1, cluster=True, execution_mode="cli", mentions=[],
        allow_unsafe_cli=False, allow_cluster_tier_edit=True, main_conversation_id=conversation, team_state=team,
    )
    await api.handle_cluster_mcp_tool(manager, run.run_id, "configure_team", {
        "mode": "extend", "roles": [{"name": "Reviewer", "responsibility": "Review"}],
    })
    _, _, session = api.get_chat_session_for_alias(manager, "main", 1, "main")
    session.is_processing = True
    session._execution_id = "active-main-turn"
    async def call(name, **payload):
        response = await api.handle_cluster_mcp_tool(
            manager, run.run_id, name, payload, tier_editor=runtime.tier_editor(run.run_id),
        )
        return response["data"]
    return manager, run, runtime, call


@pytest.mark.asyncio
async def test_query_edit_reload_and_enqueue_use_one_tier_selection(cluster):
    manager, run, runtime, call = cluster
    catalog = await call("get_agent_tiers")
    assert set(catalog["tiers"]) == set(MODEL_TIER_KEYS)
    assert catalog["tiers"]["low"]["configured"]["cli_type"] == ""
    assert catalog["tiers"]["low"]["effective"]["model"] == "base"
    revision = catalog["tiers"]["high"]["revision"]
    queued = await call("ask_agent", agent_id="worker", message="first", model_tier="high", expected_revision=revision)
    assert queued["cli_type"] == "codex"
    preview = await call("get_agent_tiers", model_tier="high", cli_type="claude")
    assert preview["options"]["models"] == ["balanced", "strong"]
    assert preview["effective"]["model"] == "fast"
    assert all(private not in json.dumps([catalog, preview]) for private in ("/trusted", "private-argument", runtime.tier_editor(run.run_id)))

    with pytest.raises(WebApiError) as wrong_target:
        await call("update_agent_tier", model_tier="high", expected_revision=preview["revision"], reasoning_effort="low")
    assert wrong_target.value.code == "cluster_tier_changed"
    changed = await call("update_agent_tier", model_tier="high", expected_revision=preview["revision"],
                         cli_type="claude", model="strong", reasoning_effort="high")
    assert changed["changed"] and changed["run_id"] == run.run_id
    assert changed["effective"] == {"cli_type": "claude", "provider": "", "model": "strong", "reasoning_effort": "high"}
    with pytest.raises(WebApiError, match="changed") as stale:
        await call("ask_agent", agent_id="worker", message="stale", model_tier="high", expected_revision=revision)
    assert stale.value.code == "cluster_tier_changed"
    second = await call("ask_agent", agent_id="worker", message="second", model_tier="high", expected_revision=changed["revision"])
    first_task, second_task = (run.tasks[item["task_id"]] for item in (queued, second))
    assert first_task.execution.cli_path == "/trusted/high"
    assert second_task.execution.cli_type == "claude" and second_task.execution.cli_path != first_task.execution.cli_path
    assert second_task.execution.params_config.claude["effort"] == "high"

    restored = MultiBotManager(BotProfile(alias="main"), str(manager.storage_file)).main_profile
    assert restored.cluster.tier_configs["high"].model == "strong"
    assert restored.cluster.model_tiers["professional"] == "special"
    assert restored.cli_type == "codex" and restored.cli_params.claude["model"] == "balanced"

    reset = await call("update_agent_tier", model_tier="high", expected_revision=changed["revision"],
                       model="", reasoning_effort="")
    assert reset["effective"]["model"] == "balanced" and reset["effective"]["reasoning_effort"] == "low"
    assert manager.main_profile.cluster.model_tiers["high"] == manager.main_profile.cluster.reasoning_efforts["high"] == ""
    noop = await call("update_agent_tier", model_tier="high", expected_revision=reset["revision"], model="")
    assert noop["changed"] is False and noop["revision"] == reset["revision"]
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_invalid_edits_do_not_save_or_fall_back(cluster, monkeypatch):
    manager, run, _, call = cluster
    original = manager.main_profile.cluster.to_dict()
    before = await call("get_agent_tiers", model_tier="low")
    claude = await call("get_agent_tiers", model_tier="low", cli_type="claude")
    for patch in [
        {"cli_type": "shell"}, {"cli_type": "claude", "model": "fast"},
        {"cli_type": "claude", "reasoning_effort": "ultra"}, {"model": ["fast"]},
        {"cli_path": "/untrusted"}, {"provider": "other"}, {"enabled": False}, {},
    ]:
        with pytest.raises(WebApiError) as error:
            revision = claude["revision"] if patch.get("cli_type") == "claude" else before["revision"]
            await call("update_agent_tier", model_tier="low", expected_revision=revision, **patch)
        assert error.value.code == "cluster_tier_invalid"
    for bad in [{"model_tier": "expert"}, {"model": "fast"}, {"cli_type": "codex"}]:
        with pytest.raises(WebApiError):
            await call("ask_agent", agent_id="worker", message="should never start", **bad)
    assert not run.tasks
    monkeypatch.setattr(api, "resolve_cli_executable", lambda *_args: None)
    with pytest.raises(WebApiError) as missing:
        await call("update_agent_tier", model_tier="low", expected_revision=claude["revision"], cli_type="claude")
    assert missing.value.code == "cluster_cli_unavailable"
    assert manager.main_profile.cluster.to_dict() == original


@pytest.mark.asyncio
async def test_deepseek_validates_the_tier_executables_provider_and_model_efforts(cluster, monkeypatch):
    manager, _, _, call = cluster
    manager.main_profile.cluster = normalize_bot_cluster_config({
        "enabled": True, "tier_configs": {
            "low": {"cli_type": "deepseek", "cli_path": "/trusted/special-dsh", "provider": "alternate"},
            "high": {"cli_type": "deepseek", "cli_path": "/trusted/different-dsh"},
        },
    })
    def discover(resolved_cli, working_dir, params):
        assert resolved_cli == "/trusted/special-dsh" and not params.get("model")
        return {"providers": [
            {"id": "main", "models": ["main-only"]},
            {"id": "alternate", "models": [{"id": "fast", "reasoningEfforts": ["low"]}, {"id": "slow"}],
             "reasoningEfforts": ["high"]},
        ], "selectedProvider": "main"}
    monkeypatch.setattr(api, "discover_deepseek_catalog", discover)
    preview = await call("get_agent_tiers", model_tier="low")
    assert preview["options"]["models"] == ["fast", "slow"]
    assert preview["options"]["reasoning_efforts_by_model"] == {"fast": ["low"]}
    args = {"model_tier": "low", "expected_revision": preview["revision"]}
    for model, effort in [("main-only", "low"), ("fast", "high")]:
        with pytest.raises(WebApiError) as error:
            await call("update_agent_tier", **args, model=model, reasoning_effort=effort)
        assert error.value.code == "cluster_tier_invalid"
    result = await call("update_agent_tier", **args, model="fast", reasoning_effort="low")
    assert result["effective"]["provider"] == "alternate"
    assert manager.main_profile.cluster.tier_configs["low"].cli_path == "/trusted/special-dsh"


@pytest.mark.asyncio
async def test_antigravity_reports_actual_effort_and_rejects_ignored_settings(cluster):
    manager, _, _, call = cluster
    preview = await call("get_agent_tiers", model_tier="low", cli_type="antigravity")
    args = {"model_tier": "low", "cli_type": "antigravity", "expected_revision": preview["revision"]}
    assert preview["options"]["reasoning_efforts_by_model"] == {"gemini-high": ["high"], "gemini": []}
    for model in ("gemini", "gemini-high"):
        with pytest.raises(WebApiError) as invalid:
            await call("update_agent_tier", **args, model=model, reasoning_effort="medium")
        assert invalid.value.code == "cluster_tier_invalid"
    chosen = await call("update_agent_tier", **args, model="gemini-high")
    assert chosen["effective"]["reasoning_effort"] == "high" and chosen["configured"]["reasoning_effort"] == ""
    manager.main_profile.remote_workspace = {"connection_id": "test"}
    for cli_type in ("antigravity", "deepseek"):
        preview = await call("get_agent_tiers", model_tier="low", cli_type=cli_type)
        assert preview["options"]["availability"] == "unsupported"
        with pytest.raises(WebApiError):
            await call("update_agent_tier", model_tier="low", expected_revision=preview["revision"], cli_type=cli_type)


@pytest.mark.asyncio
async def test_failed_deepseek_lookup_does_not_offer_static_models_under_a_custom_provider(cluster, monkeypatch):
    manager, _, _, call = cluster
    manager.main_profile.cli_params.deepseek.update(provider="private", model="configured")
    monkeypatch.setattr(api, "discover_deepseek_catalog", lambda **kwargs: {
        "status": "fallback", "selectedProvider": "private",
        "providers": [{"id": "private", "models": ["guessed"]}],
    })
    preview = await call("get_agent_tiers", model_tier="medium", cli_type="deepseek")
    assert preview["options"]["catalog_status"] == "fallback"
    assert preview["options"]["models"] == ["configured"]
    with pytest.raises(WebApiError) as invalid:
        await call("update_agent_tier", model_tier="medium", cli_type="deepseek",
                   expected_revision=preview["revision"], model="guessed")
    assert invalid.value.code == "cluster_tier_invalid"


@pytest.mark.asyncio
async def test_concurrent_writes_and_persistence_failure_keep_settings_consistent(cluster, monkeypatch):
    manager, _, _, call = cluster
    before = await call("get_agent_tiers", model_tier="low")
    args = {"model_tier": "low", "expected_revision": before["revision"]}
    results = await asyncio.gather(*(call("update_agent_tier", **args, model=model) for model in ("fast", "base")),
                                   return_exceptions=True)
    assert len([r for r in results if isinstance(r, WebApiError) and r.code == "cluster_tier_changed"]) == 1
    [saved] = [r for r in results if isinstance(r, dict)]
    saved_bytes = manager.app_settings_file.read_bytes()
    replace_file = Path.replace
    def fail_save(path, destination):
        if destination == manager.app_settings_file:
            raise OSError("disk full")
        return replace_file(path, destination)
    monkeypatch.setattr(Path, "replace", fail_save)
    with pytest.raises(WebApiError) as failed:
        await call("update_agent_tier", model_tier="low", expected_revision=saved["revision"], model="")
    assert failed.value.code == "cluster_tier_save_failed" and manager.app_settings_file.read_bytes() == saved_bytes
    assert (await call("get_agent_tiers", model_tier="low"))["configured"] == saved["configured"]


@pytest.mark.asyncio
async def test_update_requires_current_run_and_authorized_active_main(cluster):
    manager, run, runtime, call = cluster
    payload = {"model_tier": "medium", "model": "fast", "expected_revision": (await call("get_agent_tiers", model_tier="medium"))["revision"]}
    editor = runtime.tier_editor(run.run_id)
    assert editor
    old_id = api.derive_cluster_run_id(run.main_conversation_id, 0)
    for run_id, key, code in [(run.run_id, "", "cluster_tier_edit_forbidden"), (old_id, editor, "cluster_run_changed")]:
        with pytest.raises(WebApiError) as error:
            await api.handle_cluster_mcp_tool(manager, run_id, "update_agent_tier", payload, tier_editor=key)
        assert error.value.code == code
    _, _, session = api.get_chat_session_for_alias(manager, "main", 1, "main")
    session.is_processing = False
    with pytest.raises(WebApiError) as idle:
        await call("update_agent_tier", **payload)
    assert idle.value.code == "cluster_tier_edit_inactive"
    session.is_processing = True
    runtime.begin_parent_request(run.main_conversation_id, "other-user", allow_tier_edit=False)
    with pytest.raises(WebApiError) as denied:
        await api.handle_cluster_mcp_tool(manager, run.run_id, "update_agent_tier", payload, tier_editor=editor)
    assert denied.value.status == 403


@pytest.mark.asyncio
async def test_edit_waiting_on_discovery_cannot_commit_in_another_main_turn(cluster, monkeypatch):
    manager, _, _, call = cluster
    preview = await call("get_agent_tiers", model_tier="professional", cli_type="codex_server")
    assert preview["options"]["models"] == ["server"]
    args = {"model_tier": "professional", "cli_type": "codex_server", "model": "server",
            "expected_revision": preview["revision"]}
    discover = api._cluster_tier_options
    started, release = threading.Event(), threading.Event()
    def paused(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return discover(*args, **kwargs)
    monkeypatch.setattr(api, "_cluster_tier_options", paused)
    task = asyncio.create_task(call("update_agent_tier", **args))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        session = api.get_chat_session_for_alias(manager, "main", 1, "main")[2]
        session._execution_id = "following-turn"
    finally:
        release.set()
    with pytest.raises(WebApiError) as stale:
        await task
    assert stale.value.code == "cluster_tier_edit_inactive"
    assert manager.main_profile.cluster.model_tiers["professional"] == "special"
    saved = await call("update_agent_tier", **args)
    assert saved["effective"]["cli_type"] == "codex_server"
    assert manager.main_profile.cli_params.codex["model"] == "base"
