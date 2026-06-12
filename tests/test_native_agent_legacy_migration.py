from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.native_agent.legacy_migration import migrate_native_agent_payload, resolve_pi_agent_env
from bot.web.chat_store import ChatStore
from bot.web.server import WebApiServer


@pytest.fixture
def legacy_web_manager(tmp_path: Path) -> MultiBotManager:
    storage_file = tmp_path / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        main_profile=BotProfile(
            alias="main",
            token="dummy-token",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
            enabled=True,
            supported_execution_modes=["cli", "native_agent"],
        ),
        storage_file=str(storage_file),
    )


def test_legacy_native_agent_payload_and_env_migrate_to_pi_agent() -> None:
    payload = migrate_native_agent_payload(
        {
            "opencode_agent": "reviewer",
            "model": "jojocode/gpt-5.4",
        }
    )

    assert payload == {
        "pi_agent": "reviewer",
        "model": "jojocode/gpt-5.4",
    }
    assert resolve_pi_agent_env(lambda key, default="": {"NATIVE_AGENT_OPENCODE_AGENT": "planner"}.get(key, default)) == "planner"
    assert resolve_pi_agent_env(
        lambda key, default="": {
            "NATIVE_AGENT_PI_AGENT": "main",
            "NATIVE_AGENT_OPENCODE_AGENT": "planner",
        }.get(key, default)
    ) == "main"


def test_chat_store_migrates_legacy_native_session_meta_to_pi_agent(monkeypatch, tmp_path: Path):
    import bot.runtime_paths as runtime_paths

    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    store = ChatStore(workspace)
    conversation_id = store.create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(workspace),
        session_epoch=1,
        native_provider="native_agent",
        title="Native",
    )

    store.set_conversation_native_session(
        conversation_id,
        "sess-1",
        {"cwd": str(workspace), "model_id": "anthropic/sonnet", "opencode_agent": "reviewer"},
    )

    assert store.get_conversation(conversation_id)["native_session_meta"] == {
        "cwd": str(workspace),
        "model_id": "anthropic/sonnet",
        "pi_agent": "reviewer",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path_template", "json_body", "query"),
    [
        ("POST", "/api/bots/main/chat", {"message": "hi", "execution_mode": "opencode"}, None),
        ("POST", "/api/bots/main/chat/stream", {"message": "hi", "execution_mode": "opencode"}, None),
        ("GET", "/api/bots/main/history", None, {"execution_mode": "opencode"}),
        ("GET", "/api/bots/main/conversations", None, {"execution_mode": "opencode"}),
        ("POST", "/api/bots/main/conversations", {"title": "新会话", "execution_mode": "opencode"}, None),
        ("POST", "/api/bots/main/plans/execute", {"content": "# 方案", "execution_mode": "opencode"}, None),
        ("POST", "/api/bots/main/conversations/{conversation_id}/select", {"execution_mode": "opencode"}, None),
        ("DELETE", "/api/bots/main/conversations/{conversation_id}", None, {"execution_mode": "opencode"}),
        ("DELETE", "/api/bots/main/conversations", {"execution_mode": "opencode"}, None),
    ],
)
async def test_web_routes_reject_legacy_execution_mode(
    legacy_web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path_template: str,
    json_body: dict[str, object] | None,
    query: dict[str, str] | None,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    conversation_id = ChatStore(Path(legacy_web_manager.main_profile.working_dir)).create_conversation(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        bot_mode="cli",
        cli_type="codex",
        working_dir=legacy_web_manager.main_profile.working_dir,
        session_epoch=1,
        native_provider="codex",
        title="已存在",
    )
    path = path_template.format(conversation_id=conversation_id)

    app = WebApiServer(legacy_web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.request(method, path, json=json_body, params=query)
            payload = await response.json()

    assert response.status == 400
    assert payload["error"]["code"] == "invalid_execution_mode"
