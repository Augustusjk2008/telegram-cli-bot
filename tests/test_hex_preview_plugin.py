from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from bot.plugins.service import PluginService


@pytest.mark.asyncio
async def test_hex_preview_plugin_renders_binary_preview(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/hex-preview"), plugins_root / "hex-preview")
    target = repo_root / "bin" / "firmware.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(bytes([0, 65, 66, 127, 128, 255, 32, 46, 72, 101, 120, 33]))

    service = PluginService(repo_root, plugins_root=plugins_root)
    resolved = service.resolve_file_target("bin/firmware.bin")

    assert resolved["kind"] == "plugin_view"
    assert resolved["pluginId"] == "hex-preview"
    assert resolved["viewId"] == "hex"

    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="hex-preview",
        view_id="hex",
        input_payload={"path": "bin/firmware.bin"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["renderer"] == "hex"
    assert rendered["mode"] == "snapshot"
    assert rendered["payload"]["fileSizeBytes"] == 12
    assert rendered["payload"]["previewBytes"] == 12
    assert rendered["payload"]["rows"][0]["offset"] == 0
    assert rendered["payload"]["rows"][0]["hex"][:4] == ["00", "41", "42", "7F"]
    assert rendered["payload"]["rows"][0]["ascii"] == ".AB... .Hex!"
    assert rendered["payload"]["entropyBuckets"]

    await service.shutdown()


@pytest.mark.asyncio
async def test_hex_preview_plugin_truncates_large_binary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/hex-preview"), plugins_root / "hex-preview")
    target = repo_root / "bin" / "large.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(bytes(range(256)) * 128)

    service = PluginService(repo_root, plugins_root=plugins_root)
    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="hex-preview",
        view_id="hex",
        input_payload={"path": "bin/large.bin"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["payload"]["fileSizeBytes"] == 32768
    assert rendered["payload"]["previewBytes"] == 16384
    assert rendered["payload"]["truncated"] is True
    assert rendered["payload"]["rows"][-1]["offset"] == 16368

    await service.shutdown()
