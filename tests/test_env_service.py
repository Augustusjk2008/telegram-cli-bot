import os
import json
from pathlib import Path

import pytest

from bot import config
from bot.web.env_service import EnvConfigService, EnvValidationError


def _write_env(root: Path, text: str) -> None:
    (root / ".env").write_text(text, encoding="utf-8")
    (root / ".env.example").write_text("", encoding="utf-8")


def test_cli_model_options_accepts_independent_json_rows(tmp_path: Path) -> None:
    _write_env(tmp_path, "")
    service = EnvConfigService(tmp_path)
    table = {
        "codex": ["codex-model"],
        "codex_server": ["server-model"],
        "claude": ["claude-model"],
        "antigravity": ["agy-model"],
        "deepseek": ["dsh-model"],
    }

    preview = service.reload_preview({"values": {"CLI_MODEL_OPTIONS": json.dumps(table)}})

    assert preview["changedKeys"] == ["CLI_MODEL_OPTIONS"]
    assert preview["restartRequiredKeys"] == ["CLI_MODEL_OPTIONS"]

    with pytest.raises(EnvValidationError):
        service.reload_preview({"values": {"CLI_MODEL_OPTIONS": "[\"codex-model\"]"}})

    parsed = config._parse_cli_model_options(json.dumps(table))
    assert parsed["codex"] == ["codex-model", "none"]
    assert parsed["deepseek"] == ["dsh-model", "none"]
    assert config._parse_cli_model_options("legacy-a,legacy-b") == ["legacy-a", "legacy-b", "none"]


def test_env_service_masks_telegram_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("TELEGRAM_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_BROADCAST_COMPLETIONS"):
        monkeypatch.delenv(key, raising=False)
    _write_env(tmp_path, "")
    service = EnvConfigService(tmp_path)

    service.patch({
        "values": {
            "TELEGRAM_ENABLED": True,
            "TELEGRAM_BOT_TOKEN": "123456:secret",
            "TELEGRAM_ALLOWED_USER_IDS": "42, 43",
            "TELEGRAM_BROADCAST_COMPLETIONS": True,
        }
    })
    snapshot = {item["key"]: item for item in service.snapshot()["items"]}
    assert snapshot["TELEGRAM_ENABLED"]["value"] == "true"
    assert snapshot["TELEGRAM_ALLOWED_USER_IDS"]["value"] == "42,43"
    assert snapshot["TELEGRAM_BROADCAST_COMPLETIONS"]["value"] == "true"
    assert snapshot["TELEGRAM_BOT_TOKEN"]["value"] == ""
    assert snapshot["TELEGRAM_BOT_TOKEN"]["masked"] is True
    assert "TELEGRAM_BOT_TOKEN=123456:secret" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_windows_registry_environment_merges_path_and_expands_values() -> None:
    class FakeKey:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeRegistry:
        HKEY_LOCAL_MACHINE = "machine"
        HKEY_CURRENT_USER = "user"

        def __init__(self):
            self.data = {
                (self.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"): [
                    ("SystemRoot", r"C:\Windows", 1),
                    ("Path", r"%SystemRoot%\System32", 2),
                ],
                (self.HKEY_CURRENT_USER, "Environment"): [
                    ("Path", r"C:\Tools", 1),
                    ("ToolHome", r"%SystemRoot%\Tools", 2),
                ],
            }

        def OpenKey(self, root, subkey):
            return FakeKey(self.data[(root, subkey)])

        def QueryInfoKey(self, key):
            return (0, len(key.values), None)

        def EnumValue(self, key, index):
            return key.values[index]

    values = config._read_windows_environment(FakeRegistry())

    assert values is not None
    assert values["Path"] == os.pathsep.join([r"C:\Windows\System32", r"C:\Tools"])
    assert values["ToolHome"] == r"C:\Windows\Tools"


def test_project_float_config_rejects_non_finite_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_FINITE_FLOAT", "nan")

    assert config._get_project_float("TEST_FINITE_FLOAT", 7.5) == 7.5


def test_env_service_fills_empty_key_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_PUBLIC_URL", raising=False)
    _write_env(tmp_path, "# hub\nWEB_PUBLIC_URL=\nPUSHPLUS_TOPIC=\n")
    service = EnvConfigService(tmp_path)

    service.patch({"values": {"WEB_PUBLIC_URL": "https://hub.example/node/a"}})
    service.patch({"values": {"WEB_PUBLIC_URL": "https://hub.example/node/b"}})

    text = (tmp_path / ".env").read_bytes().decode("utf-8")
    assert text == "# hub\nWEB_PUBLIC_URL=https://hub.example/node/b\nPUSHPLUS_TOPIC=\n"
    items = {item["key"]: item for item in service.snapshot()["items"]}
    assert items["WEB_PUBLIC_URL"]["value"] == "https://hub.example/node/b"


def test_env_service_accepts_fixed_public_forward_config(tmp_path: Path) -> None:
    _write_env(
        tmp_path,
        "\n".join(
            [
                "TCB_NODE_ID=nanjing-laptop",
                "WEB_BASE_PATH=/node/nanjing-laptop",
                "WEB_FIXED_PUBLIC_FORWARD_ENABLED=false",
                "WEB_TUNNEL_MODE=disabled",
            ]
        ),
    )

    result = EnvConfigService(tmp_path).reload_preview(
        {
            "values": {
                "WEB_FIXED_PUBLIC_FORWARD_ENABLED": True,
                "WEB_FIXED_PUBLIC_FORWARD_URL": "http://124.221.226.63:18088/node/nanjing-laptop",
                "TCB_HUB_FRPS_PORT": 7000,
                "TCB_HUB_NODE_TOKEN": "secret",
                "TCB_HUB_FRPS_TOKEN": "frps-secret",
            }
        }
    )

    assert result["changedKeys"] == [
        "WEB_FIXED_PUBLIC_FORWARD_ENABLED",
        "WEB_FIXED_PUBLIC_FORWARD_URL",
        "TCB_HUB_FRPS_PORT",
        "TCB_HUB_NODE_TOKEN",
        "TCB_HUB_FRPS_TOKEN",
    ]


def test_env_service_endless_retry_delay_is_hot_reloadable_and_non_negative(tmp_path: Path) -> None:
    _write_env(tmp_path, "")
    service = EnvConfigService(tmp_path)

    item = next(item for item in service.snapshot()["items"] if item["key"] == "ENDLESS_CONTINUE_DELAY_SECONDS")
    assert item["default"] == "120"

    preview = service.reload_preview({"values": {"ENDLESS_CONTINUE_DELAY_SECONDS": 15.5}})
    assert preview["changedKeys"] == ["ENDLESS_CONTINUE_DELAY_SECONDS"]
    assert preview["restartRequiredKeys"] == []

    with pytest.raises(EnvValidationError):
        service.reload_preview({"values": {"ENDLESS_CONTINUE_DELAY_SECONDS": -1}})


def test_env_service_reload_runtime_reports_reload_and_restart_impact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_env(tmp_path, "")
    service = EnvConfigService(tmp_path)
    monkeypatch.setattr(
        config,
        "reload_project_env",
        lambda path: {"changed_keys": ["PUSHPLUS_TOKEN", "VITE_BASE_PATH"]},
    )

    result = service.reload_runtime()

    assert result["changedKeys"] == ["VITE_BASE_PATH", "PUSHPLUS_TOKEN"]
    assert result["reloadedKeys"] == result["changedKeys"]
    assert result["restartRequiredKeys"] == ["VITE_BASE_PATH", "PUSHPLUS_TOKEN"]
    assert result["rebuildRequiredKeys"] == ["VITE_BASE_PATH"]
    assert result["projectEnvReloaded"] is True
    assert result["systemEnvironmentReloaded"] is False


def test_env_service_system_reload_reports_windows_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_env(tmp_path, "")
    service = EnvConfigService(tmp_path)
    monkeypatch.setattr(
        config,
        "reload_system_environment",
        lambda path: {"supported": True, "changed_keys": ["PUSHPLUS_TOKEN", "WEB_API_TOKEN"]},
    )

    result = service.reload_system_runtime()

    assert result["changedKeys"] == ["WEB_API_TOKEN", "PUSHPLUS_TOKEN"]
    assert result["reloadedKeys"] == result["changedKeys"]
    assert result["projectEnvReloaded"] is True
    assert result["systemEnvironmentReloaded"] is True
    assert result["systemEnvironmentSupported"] is True


def test_env_service_rejects_fixed_forward_and_quick_tunnel(tmp_path: Path) -> None:
    _write_env(
        tmp_path,
        "\n".join(
            [
                "TCB_NODE_ID=nanjing-laptop",
                "WEB_BASE_PATH=/node/nanjing-laptop",
                "WEB_FIXED_PUBLIC_FORWARD_ENABLED=false",
                "WEB_TUNNEL_MODE=disabled",
            ]
        ),
    )

    with pytest.raises(EnvValidationError) as exc_info:
        EnvConfigService(tmp_path).reload_preview(
            {
                "values": {
                    "WEB_FIXED_PUBLIC_FORWARD_ENABLED": True,
                    "WEB_FIXED_PUBLIC_FORWARD_URL": "http://124.221.226.63:18088/node/nanjing-laptop",
                    "TCB_HUB_FRPS_PORT": 7000,
                    "TCB_HUB_NODE_TOKEN": "secret",
                    "TCB_HUB_FRPS_TOKEN": "frps-secret",
                    "WEB_TUNNEL_MODE": "cloudflare_quick",
                }
            }
        )

    assert exc_info.value.code == "invalid_env_value"


def test_env_service_requires_frps_port_for_fixed_forward(tmp_path: Path) -> None:
    _write_env(tmp_path, "TCB_NODE_ID=nanjing-laptop\nWEB_BASE_PATH=/node/nanjing-laptop\nWEB_TUNNEL_MODE=disabled\n")

    with pytest.raises(EnvValidationError) as exc_info:
        EnvConfigService(tmp_path).reload_preview(
            {
                "values": {
                    "WEB_FIXED_PUBLIC_FORWARD_ENABLED": True,
                    "WEB_FIXED_PUBLIC_FORWARD_URL": "http://124.221.226.63:18088/node/nanjing-laptop",
                    "TCB_HUB_NODE_TOKEN": "secret",
                }
            }
        )

    assert exc_info.value.data["key"] == "TCB_HUB_FRPS_PORT"


def test_env_service_requires_frps_token_for_fixed_forward(tmp_path: Path) -> None:
    _write_env(
        tmp_path,
        "TCB_NODE_ID=nanjing-laptop\n"
        "WEB_BASE_PATH=/node/nanjing-laptop\n"
        "WEB_TUNNEL_MODE=disabled\n"
        "TCB_HUB_FRPS_PORT=7000\n"
        "TCB_HUB_NODE_TOKEN=secret\n",
    )

    with pytest.raises(EnvValidationError) as exc_info:
        EnvConfigService(tmp_path).reload_preview(
            {
                "values": {
                    "WEB_FIXED_PUBLIC_FORWARD_ENABLED": True,
                    "WEB_FIXED_PUBLIC_FORWARD_URL": "http://124.221.226.63:18088/node/nanjing-laptop",
                }
            }
        )

    assert exc_info.value.data["key"] == "TCB_HUB_FRPS_TOKEN"


def test_env_service_rejects_base_path_mismatch(tmp_path: Path) -> None:
    _write_env(tmp_path, "TCB_NODE_ID=nanjing-laptop\nWEB_BASE_PATH=\n")

    with pytest.raises(EnvValidationError) as exc_info:
        EnvConfigService(tmp_path).reload_preview({"values": {"WEB_BASE_PATH": "/node/other"}})

    assert exc_info.value.data["key"] == "WEB_BASE_PATH"


def test_env_service_rejects_vite_path_mismatch(tmp_path: Path) -> None:
    _write_env(tmp_path, "TCB_NODE_ID=nanjing-laptop\nWEB_BASE_PATH=/node/nanjing-laptop\n")

    with pytest.raises(EnvValidationError) as exc_info:
        EnvConfigService(tmp_path).reload_preview({"values": {"VITE_BASE_PATH": "/node/other"}})

    assert exc_info.value.data["key"] == "VITE_BASE_PATH"
