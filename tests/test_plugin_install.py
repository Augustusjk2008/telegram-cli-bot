from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bot.plugins.service import PluginService


def _write_plugin(root: Path, folder: str, plugin_id: str) -> Path:
    plugin_dir = root / folder
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "id": plugin_id,
                "name": plugin_id,
                "version": "1.0.0",
                "runtime": {
                    "type": "python",
                    "entry": "backend/main.py",
                    "protocol": "jsonrpc-stdio",
                    "permissions": {},
                },
                "views": [],
                "fileHandlers": [],
            }
        ),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.parametrize("runtime_state", ["matching", "changed", "missing"])
def test_bundled_manifest_sync_requires_matching_runtime_files(tmp_path: Path, runtime_state: str) -> None:
    source_root = tmp_path / "bundled"
    source = _write_plugin(source_root, "document", "document")
    backend = source / "backend"
    backend.mkdir()
    (backend / "main.py").write_text("from helper import render\n", encoding="utf-8")
    (backend / "helper.py").write_text("def render(): return {}\n", encoding="utf-8")
    plugins_root = tmp_path / "installed"
    installed = plugins_root / source.name
    shutil.copytree(source, installed)
    installed_raw = json.loads((installed / "plugin.json").read_text(encoding="utf-8"))
    installed_raw.update(enabled=False, config={"theme": "dark"})
    (installed / "plugin.json").write_text(json.dumps(installed_raw), encoding="utf-8")
    source_raw = {
        **installed_raw,
        "enabled": True,
        "config": {"theme": "light", "pageSize": 20},
        "views": [{"id": "document", "renderer": "document", "viewMode": "session", "dataProfile": "light"}],
    }
    (source / "plugin.json").write_text(json.dumps(source_raw), encoding="utf-8")
    dependency = installed / "backend" / "helper.py"
    if runtime_state == "changed":
        dependency.write_text("def render(): return {'payload': {}}\n", encoding="utf-8")
    elif runtime_state == "missing":
        dependency.unlink()

    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=source_root)
    service.list_plugins(refresh=True)

    actual = json.loads((installed / "plugin.json").read_text(encoding="utf-8"))
    expected = (
        {**source_raw, "enabled": False, "config": {"theme": "dark", "pageSize": 20}}
        if runtime_state == "matching" else installed_raw
    )
    assert actual == expected


@pytest.mark.asyncio
async def test_install_plugins_from_path_recursively_installs_nested_plugins(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    first = _write_plugin(source_root / "plugins", "first", "first-plugin")
    second = _write_plugin(source_root / "plugins" / "nested", "second", "second-plugin")
    plugins_root = tmp_path / "installed"
    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=tmp_path / "bundled")

    try:
        result = await service.install_plugins_from_path(source_root, force=True)
    finally:
        await service.shutdown()

    assert result["sourcePath"] == str(source_root.resolve())
    assert result["discovered"] == 2
    assert [item["id"] for item in result["installed"]] == ["first-plugin", "second-plugin"]
    assert (plugins_root / first.name / "plugin.json").is_file()
    assert (plugins_root / second.name / "plugin.json").is_file()


@pytest.mark.asyncio
async def test_install_plugins_from_path_rejects_duplicate_ids_before_copying(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    _write_plugin(source_root, "first", "duplicate")
    _write_plugin(source_root / "nested", "second", "duplicate")
    plugins_root = tmp_path / "installed"
    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=tmp_path / "bundled")

    try:
        with pytest.raises(ValueError, match="插件 ID 重复"):
            await service.install_plugins_from_path(source_root, force=True)
    finally:
        await service.shutdown()

    assert not plugins_root.exists()
