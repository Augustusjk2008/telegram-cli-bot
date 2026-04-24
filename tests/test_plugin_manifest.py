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


def test_load_plugin_manifest_accepts_schema_v2_table_tree_and_permissions(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "report-viewer",
        payload_overrides={
            "schemaVersion": 2,
            "runtime": {
                "type": "python",
                "entry": "backend/main.py",
                "protocol": "jsonrpc-stdio",
                "permissions": {
                    "workspaceRead": True,
                    "workspaceList": True,
                    "tempArtifacts": True,
                },
            },
            "configSchema": {
                "title": "Report Settings",
                "sections": [
                    {
                        "id": "display",
                        "title": "显示",
                        "fields": [
                            {
                                "key": "pageSize",
                                "label": "每页",
                                "type": "integer",
                                "default": 100,
                                "minimum": 20,
                            }
                        ],
                    }
                ],
            },
            "catalogActions": [
                {"id": "clear-cache", "label": "清缓存", "target": "plugin", "location": "catalog"},
            ],
            "views": [
                {"id": "table", "title": "Timing", "renderer": "table", "viewMode": "session"},
                {"id": "tree", "title": "Hierarchy", "renderer": "tree"},
            ],
            "fileHandlers": [
                {"id": "timing-rpt", "label": "Timing", "extensions": [".rpt"], "viewId": "table"},
            ],
        },
    )

    manifest = PluginRegistry(plugins_root).discover()["report-viewer"]

    assert manifest.schema_version == 2
    assert manifest.runtime.permissions.workspace_read is True
    assert manifest.runtime.permissions.workspace_list is True
    assert manifest.runtime.permissions.temp_artifacts is True
    assert manifest.views[0].renderer == "table"
    assert manifest.views[1].renderer == "tree"
    assert manifest.config_schema is not None
    assert manifest.config_schema.sections[0].fields[0].key == "pageSize"
    assert manifest.catalog_actions[0].location == "catalog"


def test_load_plugin_manifest_accepts_schema_v2_document_renderer(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "docx-preview",
        payload_overrides={
            "schemaVersion": 2,
            "runtime": {
                "type": "python",
                "entry": "backend/main.py",
                "protocol": "jsonrpc-stdio",
                "permissions": {"workspaceRead": True},
            },
            "views": [
                {
                    "id": "document",
                    "title": "文档预览",
                    "renderer": "document",
                    "viewMode": "snapshot",
                    "dataProfile": "light",
                }
            ],
            "fileHandlers": [
                {
                    "id": "docx-file",
                    "label": "Word 文档预览",
                    "extensions": [".docx"],
                    "viewId": "document",
                }
            ],
        },
    )

    manifest = PluginRegistry(plugins_root).discover()["docx-preview"]

    assert manifest.schema_version == 2
    assert manifest.views[0].renderer == "document"
    assert manifest.views[0].view_mode == "snapshot"
    assert manifest.file_handlers[0].extensions == (".docx",)


def test_load_plugin_manifest_rejects_v1_table_renderer(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "legacy-viewer",
        payload_overrides={
            "schemaVersion": 1,
            "views": [{"id": "table", "title": "Timing", "renderer": "table"}],
            "fileHandlers": [],
        },
    )

    with pytest.raises(ValueError, match="renderer"):
        PluginRegistry(plugins_root).discover()


def test_load_plugin_manifest_rejects_unknown_permission_key(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "bad-permissions",
        payload_overrides={
            "schemaVersion": 2,
            "runtime": {
                "type": "python",
                "entry": "backend/main.py",
                "protocol": "jsonrpc-stdio",
                "permissions": {"workspaceRead": True, "workspaceWrite": True},
            },
        },
    )

    with pytest.raises(ValueError, match="permissions"):
        PluginRegistry(plugins_root).discover()


def test_load_plugin_manifest_rejects_v1_config_schema(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "legacy-config",
        payload_overrides={
            "schemaVersion": 1,
            "configSchema": {
                "sections": [
                    {
                        "id": "display",
                        "fields": [{"key": "lodEnabled", "label": "启用 LOD", "type": "boolean"}],
                    }
                ]
            },
        },
    )

    with pytest.raises(ValueError, match="configSchema"):
        PluginRegistry(plugins_root).discover()
