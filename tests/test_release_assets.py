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


def test_windows_portable_build_does_not_bundle_codex_by_default():
    content = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert "function Install-PortableCodex" not in content
    assert "Install-PortableCodex -PackageRoot" not in content
    assert "CLI_PATH=codex" in content
    assert "CLI_PATH=tools\\codex\\codex.exe" not in content
    assert 'Join-Path $scriptDir "tools\\codex"' not in content
    assert 'Join-Path $scriptDir "tools\\git\\cmd"' in content
    assert 'Join-Path $scriptDir "tools\\git\\bin"' in content
    assert 'Join-Path $scriptDir "tools\\git\\usr\\bin"' in content
    assert 'Join-Path $scriptDir "tools\\git\\mingw64\\bin"' in content
    assert 'Join-Path $PackageRoot "tools\\codex\\codex.exe"' not in content
    assert "$codexExe" not in content
    assert "包内 Codex 校验失败" not in content


def test_windows_portable_readme_does_not_claim_bundled_codex():
    content = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert "内置 Codex" not in content
    assert "Codex 来源" not in content
    assert "不内置 AI CLI" in content
    assert "codex --version / claude --version / kimi info" in content
    assert "CLI_TYPE / CLI_PATH" in content


def test_windows_portable_dependencies_include_tzdata():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "tzdata" in requirements


def test_publish_release_builds_and_publishes_macos_archive():
    content = Path(".release-local/publish-release.ps1").read_text(encoding="utf-8")

    assert '"{0}-macos-universal-{1}.tar.gz"' in content
    assert 'Write-DistributionMarker -Root $stageDir -PackageKind "macos" -Platform "macos-universal"' in content
    assert "MacOSArchive" in content
    assert "未找到 macOS 包" in content
    assert "$releaseAssets += @($WindowsInstallerArchive, $LinuxArchive, $MacOSArchive)" in content
