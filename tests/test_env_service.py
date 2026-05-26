from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext
from bot.web.env_service import EnvConfigService, EnvValidationError
from bot.web.server import WebApiServer


def _write_example(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Web AI CLI Bridge example config",
                "CLI_TYPE=codex",
                "CLI_PATH=codex",
                "WEB_PORT=8765",
                "WEB_API_TOKEN=change-this-password",
                "WEB_TUNNEL_MODE=disabled",
                "VITE_CHAT_TRACE_PREVIEW_MAX_LINES=5",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_env_service_reads_example_defaults_when_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_example(tmp_path / ".env.example")
    service = EnvConfigService(tmp_path)
    monkeypatch.delenv("CLI_TYPE", raising=False)

    data = service.snapshot()
    cli_type = next(item for item in data["items"] if item["key"] == "CLI_TYPE")

    assert data["envPath"] == str(tmp_path / ".env")
    assert cli_type["value"] == "codex"
    assert cli_type["source"] == "example"


def test_env_service_exposes_cli_global_extra_args_schema(tmp_path: Path):
    _write_example(tmp_path / ".env.example")
    service = EnvConfigService(tmp_path)

    data = service.snapshot()
    field = next(item for item in data["items"] if item["key"] == "CLI_GLOBAL_EXTRA_ARGS")

    assert field["type"] == "string"
    assert field["default"] == "{}"
    assert field["restartRequired"] is True


def test_env_service_masks_sensitive_values_and_preserves_unmodified_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write_example(tmp_path / ".env.example")
    env_path = tmp_path / ".env"
    env_path.write_text("WEB_API_TOKEN=old-secret\nCLI_TYPE=codex\n", encoding="utf-8")
    service = EnvConfigService(tmp_path)
    monkeypatch.delenv("WEB_API_TOKEN", raising=False)

    token_item = next(item for item in service.snapshot()["items"] if item["key"] == "WEB_API_TOKEN")
    result = service.patch({"values": {"WEB_API_TOKEN": {"masked": True}, "CLI_TYPE": "claude"}})

    assert token_item["masked"] is True
    assert token_item["value"] == ""
    assert "WEB_API_TOKEN=old-secret" in env_path.read_text(encoding="utf-8")
    assert "CLI_TYPE=claude" in env_path.read_text(encoding="utf-8")
    assert result["changedKeys"] == ["CLI_TYPE"]


def test_env_service_regenerates_sensitive_values_only(tmp_path: Path):
    _write_example(tmp_path / ".env.example")
    env_path = tmp_path / ".env"
    env_path.write_text("WEB_API_TOKEN=old-secret\nCLI_PATH=codex\n", encoding="utf-8")
    service = EnvConfigService(tmp_path)

    result = service.patch({"values": {"WEB_API_TOKEN": {"action": "regenerate"}}})
    updated = env_path.read_text(encoding="utf-8")

    assert result["changedKeys"] == ["WEB_API_TOKEN"]
    assert "WEB_API_TOKEN=old-secret" not in updated
    assert "WEB_API_TOKEN=" in updated

    with pytest.raises(EnvValidationError) as exc_info:
        service.patch({"values": {"CLI_PATH": {"action": "regenerate"}}})
    assert exc_info.value.code == "invalid_env_value"


def test_env_service_writes_backup_and_preserves_comments_and_unknown_keys(tmp_path: Path):
    _write_example(tmp_path / ".env.example")
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# keep me\nUNKNOWN_KEY=abc\nCLI_PATH=codex\n",
        encoding="utf-8",
    )
    service = EnvConfigService(tmp_path)

    result = service.patch({"values": {"CLI_PATH": r"C:\Program Files\Codex\codex.exe", "WEB_PORT": 9999}})
    updated = env_path.read_text(encoding="utf-8")

    assert result["changedKeys"] == ["CLI_PATH", "WEB_PORT"]
    assert Path(result["backupPath"]).exists()
    assert "# keep me" in updated
    assert "UNKNOWN_KEY=abc" in updated
    assert r"CLI_PATH=C:\Program Files\Codex\codex.exe" in updated
    assert "WEB_PORT=9999" in updated


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"values": {"BAD KEY": "x"}}, "invalid_env_key"),
        ({"values": {"WEB_PORT": "abc"}}, "invalid_env_value"),
        ({"values": {"WEB_TUNNEL_MODE": "ngrok"}}, "invalid_env_value"),
    ],
)
def test_env_service_rejects_invalid_patch(tmp_path: Path, payload: dict, code: str):
    _write_example(tmp_path / ".env.example")
    service = EnvConfigService(tmp_path)

    with pytest.raises(EnvValidationError) as exc_info:
        service.patch(payload)

    assert exc_info.value.code == code


def test_env_reload_preview_returns_validated_diff_without_writing(tmp_path: Path):
    _write_example(tmp_path / ".env.example")
    env_path = tmp_path / ".env"
    env_path.write_text("CLI_TYPE=codex\n", encoding="utf-8")
    service = EnvConfigService(tmp_path)

    preview = service.reload_preview({"values": {"CLI_TYPE": "claude", "WEB_PORT": "9000"}})

    assert preview["changedKeys"] == ["CLI_TYPE", "WEB_PORT"]
    assert env_path.read_text(encoding="utf-8") == "CLI_TYPE=codex\n"
    assert preview["restartRequiredKeys"] == ["CLI_TYPE", "WEB_PORT"]
    assert preview["backupPath"] == ""


def test_env_snapshot_reports_process_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_example(tmp_path / ".env.example")
    (tmp_path / ".env").write_text("WEB_PORT=8765\n", encoding="utf-8")
    monkeypatch.setenv("WEB_PORT", "9000")
    service = EnvConfigService(tmp_path)

    item = next(item for item in service.snapshot()["items"] if item["key"] == "WEB_PORT")

    assert item["value"] == "9000"
    assert item["source"] == "process"
    assert item["processOverridden"] is True
    assert item["processValue"] == "9000"


@pytest.mark.asyncio
async def test_admin_env_routes_require_admin_capability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_example(tmp_path / ".env.example")
    manager = MultiBotManager(
        main_profile=BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        storage_file=str(tmp_path / "managed_bots.json"),
    )
    server = WebApiServer(manager)
    server.env_config_service = EnvConfigService(tmp_path)

    def member_auth(_self, _request):
        return AuthContext(user_id=1001, token_used=True, capabilities={"git_ops"})

    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", member_auth)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/env")
            payload = await resp.json()

    assert resp.status == 403
    assert payload["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_admin_env_reload_preview_route_returns_diff_and_requires_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write_example(tmp_path / ".env.example")
    env_path = tmp_path / ".env"
    env_path.write_text("CLI_TYPE=codex\n", encoding="utf-8")
    manager = MultiBotManager(
        main_profile=BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        storage_file=str(tmp_path / "managed_bots.json"),
    )
    server = WebApiServer(manager)
    server.env_config_service = EnvConfigService(tmp_path)
    capability_sets = iter([{"git_ops"}, {"admin_ops"}, {"admin_ops"}])

    def auth(_self, _request):
        return AuthContext(user_id=1001, token_used=True, capabilities=next(capability_sets))

    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", auth)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            denied = await client.post("/api/admin/env/reload-preview", json={"values": {"CLI_TYPE": "claude"}})
            denied_payload = await denied.json()
            ok = await client.post("/api/admin/env/reload-preview", json={"values": {"CLI_TYPE": "claude"}})
            ok_payload = await ok.json()
            invalid = await client.post("/api/admin/env/reload-preview", json={"values": {"WEB_PORT": "bad"}})
            invalid_payload = await invalid.json()

    assert denied.status == 403
    assert denied_payload["error"]["code"] == "forbidden"
    assert ok.status == 200
    assert ok_payload["data"]["changedKeys"] == ["CLI_TYPE"]
    assert ok_payload["data"]["backupPath"] == ""
    assert env_path.read_text(encoding="utf-8") == "CLI_TYPE=codex\n"
    assert invalid.status == 400
    assert invalid_payload["error"]["code"] == "invalid_env_value"


@pytest.mark.asyncio
async def test_admin_env_patch_returns_change_impact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_example(tmp_path / ".env.example")
    manager = MultiBotManager(
        main_profile=BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        storage_file=str(tmp_path / "managed_bots.json"),
    )
    server = WebApiServer(manager)
    server.env_config_service = EnvConfigService(tmp_path)

    def admin_auth(_self, _request):
        return AuthContext(
            user_id=1001,
            token_used=True,
            account_id="local-admin",
            capabilities={"admin_ops"},
            is_local_admin=True,
        )

    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", admin_auth)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch("/api/admin/env", json={"values": {"WEB_PORT": 9000}})
            payload = await resp.json()

    assert resp.status == 200
    assert payload["data"]["changedKeys"] == ["WEB_PORT"]
    assert payload["data"]["restartRequiredKeys"] == ["WEB_PORT"]
    assert payload["data"]["rebuildRequiredKeys"] == []
    assert Path(payload["data"]["backupPath"]).exists()


@pytest.mark.asyncio
async def test_admin_env_patch_returns_400_for_invalid_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_example(tmp_path / ".env.example")
    manager = MultiBotManager(
        main_profile=BotProfile(alias="main", token="", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        storage_file=str(tmp_path / "managed_bots.json"),
    )
    server = WebApiServer(manager)
    server.env_config_service = EnvConfigService(tmp_path)

    def admin_auth(_self, _request):
        return AuthContext(user_id=1001, token_used=True, capabilities={"admin_ops"})

    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", admin_auth)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch("/api/admin/env", json={"values": {"WEB_PORT": "abc"}})
            payload = await resp.json()

    assert resp.status == 400
    assert payload["error"]["code"] == "invalid_env_value"
