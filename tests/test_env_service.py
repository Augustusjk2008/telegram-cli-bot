from pathlib import Path

import pytest

from bot.web.env_service import EnvConfigService, EnvValidationError


def _write_env(root: Path, text: str) -> None:
    (root / ".env").write_text(text, encoding="utf-8")
    (root / ".env.example").write_text("", encoding="utf-8")


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


def test_env_service_exposes_fixed_forward_hub_fields(tmp_path: Path) -> None:
    _write_env(tmp_path, "")

    snapshot = EnvConfigService(tmp_path).snapshot()
    items = {item["key"]: item for item in snapshot["items"]}

    assert items["TCB_HUB_NODE_TOKEN"]["category"] == "tunnel"
    assert items["TCB_HUB_NODE_TOKEN"]["type"] == "password"
    assert items["TCB_HUB_FRPS_TOKEN"]["category"] == "tunnel"
    assert items["TCB_HUB_FRPS_TOKEN"]["type"] == "password"
    assert items["TCB_HUB_FRPC_PATH"]["category"] == "tunnel"
    assert items["TCB_HUB_FRPC_PATH"]["type"] == "path"
    assert items["TCB_HUB_FRPS_PORT"]["category"] == "tunnel"
    assert items["TCB_HUB_FRPS_PORT"]["type"] == "number"


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
    assert "不能同时启用" in exc_info.value.message


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
