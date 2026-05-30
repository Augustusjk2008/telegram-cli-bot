from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.plugins.registry import PluginRegistry


def _deep_merge(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    extensions: list[str] | None = None,
    payload_overrides: dict | None = None,
) -> None:
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
    if payload_overrides:
        payload = _deep_merge(payload, payload_overrides)
    (plugin_dir / "plugin.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_load_plugin_manifest_defaults_view_mode_to_snapshot(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, "vivado-waveform")

    manifest = PluginRegistry(plugins_root).discover()["vivado-waveform"]

    assert manifest.views[0].view_mode == "snapshot"
    assert manifest.views[0].data_profile == "light"


