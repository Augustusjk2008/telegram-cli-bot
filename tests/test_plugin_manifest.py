from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.plugins.registry import PluginRegistry


def _write_plugin(root: Path, plugin_id: str, *, extensions: list[str] | None = None) -> None:
    plugin_dir = root / plugin_id
    (plugin_dir / "backend").mkdir(parents=True)
    (plugin_dir / "backend" / "main.py").write_text("print('plugin')\n", encoding="utf-8")
    payload = {
        "schemaVersion": 1,
        "id": plugin_id,
        "name": f"{plugin_id} name",
        "version": "0.1.0",
        "description": "test plugin",
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
        },
        "views": [
            {"id": "waveform", "title": "波形预览", "renderer": "waveform"},
        ],
        "fileHandlers": [
            {
                "id": "waveform-vcd",
                "label": "VCD 波形预览",
                "extensions": extensions or [".vcd"],
                "viewId": "waveform",
            }
        ],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_registry_discovers_repo_local_plugins_and_matches_vcd_extension(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, "vivado-waveform")

    registry = PluginRegistry(plugins_root)
    manifests = registry.discover()

    assert "vivado-waveform" in manifests
    resolved = registry.resolve_file_handler("trace/run.vcd")
    assert resolved is not None
    assert resolved.plugin_id == "vivado-waveform"
    assert resolved.view_id == "waveform"


def test_registry_rejects_duplicate_plugin_ids(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, "plugin-a")
    _write_plugin(plugins_root, "plugin-b")

    first = json.loads((plugins_root / "plugin-a" / "plugin.json").read_text(encoding="utf-8"))
    first["id"] = "duplicated"
    (plugins_root / "plugin-a" / "plugin.json").write_text(
        json.dumps(first, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    second = json.loads((plugins_root / "plugin-b" / "plugin.json").read_text(encoding="utf-8"))
    second["id"] = "duplicated"
    (plugins_root / "plugin-b" / "plugin.json").write_text(
        json.dumps(second, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    registry = PluginRegistry(plugins_root)
    with pytest.raises(ValueError, match="duplicated"):
        registry.discover()


def test_load_plugin_manifest_defaults_view_mode_to_snapshot(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, "vivado-waveform")

    manifest = PluginRegistry(plugins_root).discover()["vivado-waveform"]

    assert manifest.views[0].view_mode == "snapshot"
    assert manifest.views[0].data_profile == "light"


def test_load_plugin_manifest_accepts_session_heavy_view(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, "vivado-waveform")
    manifest_path = plugins_root / "vivado-waveform" / "plugin.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["views"][0]["viewMode"] = "session"
    payload["views"][0]["dataProfile"] = "heavy"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = PluginRegistry(plugins_root).discover()["vivado-waveform"]

    assert manifest.views[0].view_mode == "session"
    assert manifest.views[0].data_profile == "heavy"


def test_manifest_tracks_enabled_state_and_config_and_registry_skips_disabled_handlers(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, "vivado-waveform")
    manifest_path = plugins_root / "vivado-waveform" / "plugin.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["enabled"] = False
    payload["config"] = {"lodEnabled": False}
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    registry = PluginRegistry(plugins_root)
    manifest = registry.discover()["vivado-waveform"]

    assert manifest.enabled is False
    assert manifest.config["lodEnabled"] is False
    assert registry.resolve_file_handler("trace/run.vcd") is None
