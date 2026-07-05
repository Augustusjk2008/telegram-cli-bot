from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi, PluginHostContext
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.manifest_payloads import build_manifest_payload, build_manifest_signature
from bot.plugins.models import (
    PluginFileHandlerSpec,
    PluginManifest,
    PluginPermissions,
    PluginRuntimeSpec,
    PluginViewSpec,
)
from bot.plugins import models as plugin_models
from bot.plugins.runtime import PluginRuntime


def _limits(**kwargs):
    limits_cls = getattr(plugin_models, "PluginHostLimits", None)
    assert limits_cls is not None, "PluginHostLimits should exist"
    return limits_cls(**kwargs)


def _manifest(root: Path, *, limits) -> PluginManifest:
    return PluginManifest(
        root=root,
        plugin_id="limited",
        schema_version=2,
        name="Limited",
        version="1.0.0",
        description="",
        enabled=True,
        config={},
        runtime=PluginRuntimeSpec(
            runtime_type="python",
            entry="main.py",
            protocol="jsonrpc-stdio",
            permissions=PluginPermissions(
                workspace_read=True,
                workspace_list=True,
                temp_artifacts=True,
            ),
            limits=limits,
        ),
        views=(PluginViewSpec(id="main", title="Main", renderer="document"),),
        file_handlers=(PluginFileHandlerSpec(id="txt", label="Text", extensions=(".txt",), view_id="main"),),
    )


def _context(workspace: Path) -> PluginHostContext:
    return PluginHostContext(bot_alias="main", plugin_id="limited", workspace_root=workspace)


def test_manifest_parses_runtime_limits_separately_from_permissions(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "id": "limited",
                "name": "Limited",
                "version": "1.0.0",
                "runtime": {
                    "type": "python",
                    "entry": "main.py",
                    "protocol": "jsonrpc-stdio",
                    "permissions": {
                        "workspaceRead": True,
                        "workspaceList": True,
                        "tempArtifacts": True,
                    },
                    "limits": {
                        "readBytes": 1024,
                        "directoryEntries": 3,
                        "artifactBytes": 2048,
                        "artifactCount": 2,
                        "totalArtifactBytes": 4096,
                    },
                },
                "views": [{"id": "main", "title": "Main", "renderer": "document"}],
                "fileHandlers": [{"id": "txt", "label": "Text", "extensions": [".txt"], "viewId": "main"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = load_plugin_manifest(plugin_dir / "plugin.json")
    payload = build_manifest_payload(manifest)

    assert manifest.runtime.permissions.workspace_read is True
    assert manifest.runtime.limits.read_bytes == 1024
    assert payload["runtime"]["limits"]["readBytes"] == 1024


def test_manifest_signature_changes_when_runtime_limits_change(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text("{}", encoding="utf-8")
    manifest_a = _manifest(plugin_dir, limits=_limits(read_bytes=1024))
    manifest_b = _manifest(plugin_dir, limits=_limits(read_bytes=2048))

    assert build_manifest_signature(manifest_a) != build_manifest_signature(manifest_b)


@pytest.mark.asyncio
async def test_host_read_text_rejects_files_over_read_limit(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")
    manifest = _manifest(tmp_path, limits=_limits(read_bytes=4))
    api = PluginHostApi(ArtifactStore(tmp_path))

    with pytest.raises(ValueError, match="读取限额"):
        await api.dispatch(_context(tmp_path), manifest, "host.workspace.read_text", {"path": "large.txt"})


@pytest.mark.asyncio
async def test_host_list_dir_truncates_at_entry_limit(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text(str(index), encoding="utf-8")
    manifest = _manifest(tmp_path, limits=_limits(directory_entries=2))
    api = PluginHostApi(ArtifactStore(tmp_path))

    result = await api.dispatch(_context(tmp_path), manifest, "host.workspace.list_dir", {"path": "."})

    assert len(result["entries"]) == 2
    assert result["truncated"] is True
    assert result["entryLimit"] == 2


@pytest.mark.asyncio
async def test_write_artifact_rejects_oversize_base64_before_record_created(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, limits=_limits(artifact_bytes=4))
    store = ArtifactStore(tmp_path)
    api = PluginHostApi(store)

    with pytest.raises(ValueError, match="产物大小"):
        await api.dispatch(
            _context(tmp_path),
            manifest,
            "host.temp.write_artifact",
            {
                "filename": "large.bin",
                "contentBase64": base64.b64encode(b"12345").decode("ascii"),
            },
        )

    assert store._records == {}
    assert not (tmp_path / ".plugins" / "artifacts").exists()


@pytest.mark.asyncio
async def test_artifact_store_enforces_count_and_total_limits(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, limits=_limits(artifact_count=1, total_artifact_bytes=8))
    store = ArtifactStore(tmp_path)
    api = PluginHostApi(store)

    first = await api.dispatch(
        _context(tmp_path),
        manifest,
        "host.temp.write_artifact",
        {"filename": "first.txt", "text": "1234"},
    )
    with pytest.raises(ValueError, match="产物数量"):
        await api.dispatch(
            _context(tmp_path),
            manifest,
            "host.temp.write_artifact",
            {"filename": "second.txt", "text": "5678"},
        )

    assert list(store._records) == [first["artifactId"]]


def test_runtime_context_payload_exposes_effective_limits(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, limits=_limits(read_bytes=1024, directory_entries=3))
    runtime = PluginRuntime(workspace_root_for=lambda _alias: tmp_path)

    payload = runtime._context_payload("main", manifest)

    assert payload["host"]["limits"]["readBytes"] == 1024
    assert payload["host"]["limits"]["directoryEntries"] == 3
