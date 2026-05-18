import json
from pathlib import Path

from bot import updater


def test_repo_ignores_runtime_state_and_tracks_example_bot_config():
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "managed_bots.json" in ignore
    assert ".web_admin_settings.json" in ignore
    assert ".web_tunnel_state.json" in ignore
    assert ".updates/" in ignore
    assert ".release-local/" in ignore

    example = json.loads(Path("managed_bots.example.json").read_text(encoding="utf-8"))
    assert isinstance(example["bots"], list)


def test_lan_chat_runtime_files_are_protected_during_update():
    assert ".web_lan_chat.json" in updater.PROTECTED_UPDATE_PATHS
    assert ".web_lan_chat_messages.json" in updater.PROTECTED_UPDATE_PATHS


def test_portable_build_script_only_copies_tracked_files():
    content = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert 'ls-files' in content
    assert '-o --exclude-standard' not in content
    assert 'Write-Step "复制 tracked 文件"' in content
    assert ".distribution.json" in content
    assert "packageKind" in content
    assert 'Write-DistributionMarker -Root $packageRoot -PackageKind "portable" -Platform "windows-x64"' in content
