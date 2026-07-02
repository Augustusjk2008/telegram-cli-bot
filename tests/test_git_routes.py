from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.server import WebApiServer


class DummyTunnelService:
    def should_autostart(self) -> bool:
        return False

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    async def restart(self) -> dict[str, object]:
        return self.snapshot()

    def preserve_for_restart(self) -> dict[str, object]:
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "disabled",
            "status": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": None,
        }


def _build_manager(tmp_path: Path) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            token="main_tok",
            cli_type="codex",
            cli_path="codex",
            working_dir=str(tmp_path),
        ),
        str(storage),
    )


def _build_server(manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch) -> WebApiServer:
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    return WebApiServer(manager, host="127.0.0.1", port=8765, tunnel_service=DummyTunnelService())


@pytest.mark.asyncio
async def test_git_commit_message_config_patch_params_survive_get_and_manager_reload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.manager.resolve_cli_executable", lambda cli_path, _cwd=None: str(cli_path))
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            patch_response = await client.patch(
                "/api/bots/main/git/commit-message/config",
                json={
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "params": {
                        "reasoning_effort": "low",
                        "json_output": False,
                        "model": "gpt-5.1-codex",
                        "extra_args": ["--profile", "commit"],
                    },
                },
            )
            patch_payload = await patch_response.json()
            get_response = await client.get("/api/bots/main/git/commit-message/config")
            get_payload = await get_response.json()

    assert patch_response.status == 200, patch_payload
    assert get_response.status == 200, get_payload
    assert patch_payload["data"]["params"]["reasoning_effort"] == "low"
    assert patch_payload["data"]["params"]["json_output"] is False
    assert patch_payload["data"]["params"]["model"] == "gpt-5.1-codex"
    assert patch_payload["data"]["params"]["extra_args"] == ["--profile", "commit"]
    assert get_payload["data"]["params"] == patch_payload["data"]["params"]

    persisted = json.loads((tmp_path / ".git_commit_cli_config.json").read_text(encoding="utf-8"))
    assert persisted["global"]["cli_params"]["codex"]["reasoning_effort"] == "low"
    assert persisted["global"]["cli_params"]["codex"]["json_output"] is False

    restored = _build_manager(tmp_path)
    restored_config = restored.get_git_commit_cli_config("main")
    assert restored_config.cli_params.get_param("codex", "reasoning_effort") == "low"
    assert restored_config.cli_params.get_param("codex", "json_output") is False
    assert restored_config.cli_params.get_param("codex", "model") == "gpt-5.1-codex"
    assert restored_config.cli_params.get_param("codex", "extra_args") == ["--profile", "commit"]


@pytest.mark.asyncio
async def test_git_commit_message_config_patch_key_value_still_updates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.manager.resolve_cli_executable", lambda cli_path, _cwd=None: str(cli_path))
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.patch(
                "/api/bots/main/git/commit-message/config",
                json={
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "key": "reasoning_effort",
                    "value": "medium",
                },
            )
            payload = await response.json()

    assert response.status == 200, payload
    assert payload["data"]["params"]["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_git_commit_message_config_patch_rejects_non_object_params(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("bot.manager.resolve_cli_executable", lambda cli_path, _cwd=None: str(cli_path))
    manager = _build_manager(tmp_path)
    server = _build_server(manager, monkeypatch)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.patch(
                "/api/bots/main/git/commit-message/config",
                json={
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "params": ["reasoning_effort", "low"],
                },
            )
            payload = await response.json()

    assert response.status == 400
    assert payload["error"]["code"] == "invalid_params"
