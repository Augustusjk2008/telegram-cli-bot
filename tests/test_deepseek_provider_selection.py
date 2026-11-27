from __future__ import annotations

import pytest

from bot.chat_identity import chat_session_user_id
from bot.cli_params import CliParamsConfig, normalize_deepseek_selection
from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession
from bot.sessions import create_web_chat_session, unload_bot_sessions
from bot.web import api_service
from bot.web.api_common import WebApiError, resolve_session_bot_id
from bot.web.api_service import build_cluster_cli_params_override, get_cli_params_payload
from bot.web.chat_store import ChatStore
from bot.web.chat_targets import resolve_named_chat_target


def _manager_with_deepseek(tmp_path, alias: str = "worker") -> MultiBotManager:
    manager = MultiBotManager(
        BotProfile(alias="main", working_dir=str(tmp_path)),
        str(tmp_path / "bots.json"),
    )
    manager.managed_profiles[alias] = BotProfile(
        alias=alias,
        cli_type="deepseek",
        cli_path="dsh",
        working_dir=str(tmp_path),
    )
    return manager


def _catalog(*, selected_provider: str = "official") -> dict:
    return {
        "providers": [
            {
                "id": "official",
                "label": "DeepSeek Official",
                "modelOptions": [
                    {"id": "deepseek-flash", "label": "deepseek-flash"},
                    {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro"},
                ],
            },
            {
                "id": "account",
                "label": "Account Provider",
                "modelOptions": [{"id": "account-model", "label": "account-model"}],
            },
        ],
        "selectedProvider": selected_provider,
        "selectedModel": "deepseek-flash",
        "modelOptionsByProvider": {
            "official": [
                {"id": "deepseek-flash", "label": "deepseek-flash"},
                {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro"},
            ],
            "account": [{"id": "account-model", "label": "account-model"}],
        },
        "reasoningEfforts": ["low", "high"],
        "status": "ready",
        "diagnostic": "credentials: api_key=should-not-leak",
    }


def test_deepseek_selection_normalization() -> None:
    config = CliParamsConfig.from_dict(
        {
            "deepseek": {
                "provider": " none ",
                "model": " custom-model ",
                "reasoning_effort": " none ",
            }
        }
    )
    assert config.deepseek["provider"] is None
    assert config.deepseek["model"] == "custom-model"
    assert config.deepseek["reasoning_effort"] is None
    assert normalize_deepseek_selection(" account ", " model ", " high ") == {
        "provider": "account",
        "model": "model",
        "reasoning_effort": "high",
    }


def test_deepseek_catalog_payload_is_provider_scoped_and_redacted(tmp_path, monkeypatch) -> None:
    manager = _manager_with_deepseek(tmp_path)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "dsh")
    monkeypatch.setattr(
        api_service,
        "discover_deepseek_catalog",
        lambda resolved_cli, working_dir, params: _catalog(),
    )

    payload = get_cli_params_payload(manager, "worker", "deepseek")

    assert payload["catalog_status"] == "ready"
    assert payload["selected_provider"] == "official"
    assert payload["provider_options"][0]["id"] == "official"
    assert payload["model_options_by_provider"] == {
        "official": ["deepseek-flash", "deepseek-v4-pro"],
        "account": ["account-model"],
    }
    assert payload["schema"]["model"]["enum"] == [
        "deepseek-flash",
        "deepseek-v4-pro",
        "none",
    ]
    assert "should-not-leak" not in repr(payload)
    assert "api_key" not in repr(payload)


@pytest.mark.asyncio
async def test_deepseek_selection_is_atomic_and_provider_switch_invalidates_target_session(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager_with_deepseek(tmp_path)
    profile = manager.managed_profiles["worker"]
    session = UserSession(
        bot_id=-1,
        bot_alias="worker",
        user_id=1,
        agent_id="reviewer",
        working_dir=str(tmp_path),
        deepseek_session_id="old-provider-session",
        _persist_enabled=False,
    )
    monkeypatch.setattr("bot.sessions.get_bot_sessions", lambda alias: [session])
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "dsh")
    monkeypatch.setattr(
        api_service,
        "discover_deepseek_catalog",
        lambda resolved_cli, working_dir, params: _catalog(),
    )

    result = await api_service.update_deepseek_selection(
        manager,
        "worker",
        1,
        provider="account",
        model=None,
        reasoning_effort="high",
        agent_id="reviewer",
    )

    assert result["params"]["provider"] == "account"
    assert result["params"]["model"] == "account-model"
    assert result["params"]["reasoning_effort"] == "high"
    assert result["provider_changed"] is True
    assert result["session_reset"] is True
    assert profile.cli_params.deepseek["provider"] == "account"
    assert session.deepseek_session_id is None
    restored = MultiBotManager(
        BotProfile(alias="main", working_dir=str(tmp_path)),
        str(tmp_path / "bots.json"),
    )
    assert restored.managed_profiles["worker"].cli_params.deepseek["provider"] == "account"
    assert restored.managed_profiles["worker"].cli_params.deepseek["model"] == "account-model"

    session.deepseek_session_id = "same-provider-session"
    await manager.update_deepseek_selection(
        "worker",
        "account",
        "account-model",
        "high",
        user_id=1,
        agent_id="reviewer",
        allowed_providers=["official", "account"],
        allowed_models_by_provider={"account": ["account-model"]},
        allowed_reasoning_efforts_by_provider={"account": ["high"]},
    )
    assert session.deepseek_session_id == "same-provider-session"

    with pytest.raises(WebApiError, match="provider"):
        await api_service.update_deepseek_selection(
            manager,
            "worker",
            1,
            provider="unknown",
            model="model",
            reasoning_effort="high",
            agent_id="reviewer",
        )
    assert profile.cli_params.deepseek["provider"] == "account"


@pytest.mark.asyncio
async def test_bot_wide_provider_selection_requires_a_deepseek_default_and_an_agent_id(tmp_path):
    manager = _manager_with_deepseek(tmp_path)
    profile = manager.managed_profiles["worker"]
    profile.cli_type = "codex"
    with pytest.raises(WebApiError) as wrong_tool:
        await api_service.update_deepseek_selection(manager, "worker", 1, provider="account")
    assert wrong_tool.value.code == "invalid_cli_type"
    with pytest.raises(ValueError, match="agent ID"):
        await manager.update_deepseek_selection("worker", "account", None, None, agent_id="@ses_invalid")
    assert profile.cli_params.deepseek["provider"] is None


def test_deepseek_catalog_fallback_preserves_saved_provider_and_model(tmp_path, monkeypatch) -> None:
    manager = _manager_with_deepseek(tmp_path)
    manager.managed_profiles["worker"].cli_params.deepseek.update(
        {"provider": "legacy", "model": "legacy-model"}
    )
    monkeypatch.setattr(api_service, "discover_deepseek_catalog", None)

    payload = get_cli_params_payload(manager, "worker", "deepseek")

    assert payload["catalog_status"] == "fallback"
    assert payload["selected_provider"] == "legacy"
    assert payload["selected_model"] == "legacy-model"
    assert "legacy-model" in payload["schema"]["model"]["enum"]
    assert "deepseek-flash" in payload["schema"]["model"]["enum"]
    assert payload["provider_options"] == [
        {
            "id": "legacy",
            "label": "legacy",
            "model_options": [],
            "reasoning_efforts": [],
            "default_model": None,
            "default_reasoning_effort": None,
        }
    ]


def test_deepseek_cluster_override_inherits_provider(tmp_path) -> None:
    profile = BotProfile(alias="main", cli_type="deepseek", working_dir=str(tmp_path))
    profile.cli_params.deepseek["provider"] = "account"
    profile.cluster.model_tiers["high"] = "account-model"
    profile.cluster.reasoning_efforts["high"] = "high"

    override = build_cluster_cli_params_override(profile, "high")

    assert override.get_param("deepseek", "provider") == "account"
    assert override.get_param("deepseek", "model") == "account-model"
    assert override.get_param("deepseek", "reasoning_effort") == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["selection", "parameter", "reset", "reset_all"])
async def test_provider_transition_labels_legacy_threads_before_cold_reopen(tmp_path, change):
    manager = _manager_with_deepseek(tmp_path)
    profile = manager.managed_profiles["worker"]
    previous = None if change == "selection" else "old"
    profile.cli_params.deepseek["provider"] = previous
    bot_id = resolve_session_bot_id(manager, "worker")
    user_id = chat_session_user_id()
    workspace = profile.working_dir
    store = ChatStore(workspace)
    named = create_web_chat_session(bot_id, "worker", user_id, workspace, "Harness", selected_cli_type="deepseek")
    sibling = create_web_chat_session(bot_id, "worker", user_id, workspace, "Other")

    def thread(scope, native_id, meta=None, **overrides):
        owner = dict(bot_id=bot_id, bot_alias="worker", user_id=user_id, working_dir=workspace)
        owner.update(overrides)
        cid = store.create_conversation(
            agent_id=scope, session_epoch=0, cli_type="deepseek", native_provider="deepseek", **owner,
        )
        store.set_conversation_native_session(cid, native_id, meta)
        return cid

    first = thread(named.storage_scope, "native-1", {"existing": 1})
    inactive = thread(named.storage_scope, None)
    legacy_turn = store.begin_turn(
        bot_id=bot_id, bot_alias="worker", user_id=user_id, working_dir=workspace, agent_id=named.storage_scope,
        conversation_id=inactive, session_epoch=0, cli_type="deepseek", native_provider="deepseek", user_text="Old turn",
    )
    store.complete_turn(legacy_turn, content="Reply", completion_state="completed", native_session_id="native-inactive")
    other = thread(sibling.storage_scope, "native-other")
    main = thread("main", "main-native")
    recorded = thread(named.storage_scope, "known", {"deepseek_provider": None, "existing": 2})

    async def select(cid):
        target = resolve_named_chat_target(manager, "worker", user_id, named.web_session_id)
        await api_service.select_conversation(manager, "worker", user_id, cid, target=target)
        return target.session.deepseek_session_id

    await manager.set_bot_cli_param("worker", "deepseek", "model", "new-model")
    assert await select(first) == "native-1"
    assert store.get_conversation_native_session(first)["meta"] == {"existing": 1}
    excluded = [
        thread(named.storage_scope, "different-bot", bot_alias="neighbor"),
        thread("@ses_" + "2" * 32, "different-account", user_id=user_id + 1),
        thread(named.storage_scope, "different-workspace", working_dir=workspace + "-old"),
        thread("cluster-slot-1", "cluster-native", cluster_parent_conversation_id=main),
        thread(named.storage_scope, None),
    ]
    if change == "selection":
        await manager.update_deepseek_selection("worker", "new", None, None)
    elif change == "parameter":
        await manager.set_bot_cli_param("worker", "deepseek", "provider", "new")
    else:
        await manager.reset_bot_cli_params("worker", "deepseek" if change == "reset" else None)
    # Check the transition itself before opening a chat runs legacy user migration.
    assert all(store.get_conversation_native_session(cid)["meta"] == {} for cid in excluded)
    assert await select(first) is None
    unload_bot_sessions("worker")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=workspace), str(tmp_path / "bots.json"))
    assert await select(inactive) is None
    assert store.get_conversation_native_session(first) == {
        "session_id": "native-1", "meta": {"existing": 1, "deepseek_provider": previous},
    }
    for cid in (inactive, other, main):
        assert store.get_conversation_native_session(cid)["meta"] == {"deepseek_provider": previous}
    assert store.get_conversation_native_session(recorded)["meta"] == {"deepseek_provider": None, "existing": 2}
    await manager.set_bot_cli_param("worker", "deepseek", "provider", previous)
    assert await select(inactive) == "native-inactive"


@pytest.mark.asyncio
async def test_legacy_binding_write_failure_retains_previous_provider(tmp_path, monkeypatch):
    manager = _manager_with_deepseek(tmp_path)
    await manager.set_bot_cli_param("worker", "deepseek", "provider", "previous")

    def unavailable(*args, **kwargs):
        raise OSError("history unavailable")

    monkeypatch.setattr(ChatStore, "record_legacy_deepseek_provider", unavailable)
    with pytest.raises(OSError, match="history unavailable"):
        await manager.update_deepseek_selection("worker", "next", None, None)
    assert manager.managed_profiles["worker"].cli_params.deepseek["provider"] == "previous"
    reopened = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(tmp_path / "bots.json"))
    assert reopened.managed_profiles["worker"].cli_params.deepseek["provider"] == "previous"
