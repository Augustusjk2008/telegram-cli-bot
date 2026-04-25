from __future__ import annotations

from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from bot.plugins.service import PluginService


def _write_zip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("docs/readme.txt", "hello")
        archive.writestr("src/main.py", "print('hi')\n")
        archive.writestr("assets/logo.bin", bytes([0, 1, 2, 3]))


@pytest.mark.asyncio
async def test_zip_preview_plugin_renders_archive_tree(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/zip-preview"), plugins_root / "zip-preview")
    _write_zip(repo_root / "dist" / "bundle.zip")

    service = PluginService(repo_root, plugins_root=plugins_root)
    resolved = service.resolve_file_target("dist/bundle.zip")

    assert resolved["kind"] == "plugin_view"
    assert resolved["pluginId"] == "zip-preview"
    assert resolved["viewId"] == "archive-tree"

    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="zip-preview",
        view_id="archive-tree",
        input_payload={"path": "dist/bundle.zip"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["renderer"] == "tree"
    assert rendered["mode"] == "snapshot"
    assert rendered["payload"]["statsText"] == "3 文件 · 3 文件夹"
    root_labels = [node["label"] for node in rendered["payload"]["roots"]]
    assert root_labels == ["assets", "docs", "src"]
    docs = next(node for node in rendered["payload"]["roots"] if node["label"] == "docs")
    assert docs["children"][0]["label"] == "readme.txt"
    assert docs["children"][0]["badges"][0]["text"] == "5 B"

    await service.shutdown()


@pytest.mark.asyncio
async def test_zip_preview_plugin_rejects_invalid_zip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/zip-preview"), plugins_root / "zip-preview")
    target = repo_root / "dist" / "broken.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not zip")

    service = PluginService(repo_root, plugins_root=plugins_root)

    with pytest.raises(RuntimeError, match="ZIP 文件损坏或格式不支持"):
        await service.render_view(
            bot_alias="main",
            plugin_id="zip-preview",
            view_id="archive-tree",
            input_payload={"path": "dist/broken.zip"},
            audit_context={"account_id": "u1", "bot_alias": "main"},
        )

    await service.shutdown()
