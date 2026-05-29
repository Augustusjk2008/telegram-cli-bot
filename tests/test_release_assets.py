import json
from pathlib import Path

from bot import updater


def test_repo_ignores_runtime_state_and_tracks_example_bot_config():
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "managed_bots.json" in ignore
    assert ".web_admin_settings.json" in ignore
    assert ".web_announcement_reads.json" in ignore
    assert ".web_tunnel_state.json" in ignore
    assert ".updates/" in ignore
    assert ".release-local/" in ignore
    assert "!.release-local/portable-win/" in ignore
    assert ".release-local/portable-win/*" in ignore
    assert "!.release-local/portable-win/build-portable.ps1" in ignore

    example = json.loads(Path("managed_bots.example.json").read_text(encoding="utf-8"))
    assert isinstance(example["bots"], list)


def test_lan_chat_runtime_files_are_protected_during_update():
    assert ".web_announcement_reads.json" in updater.PROTECTED_UPDATE_PATHS
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


def test_publish_release_shell_builds_and_publishes_macos_archive():
    content = Path(".release-local/publish-release.sh").read_text(encoding="utf-8")

    assert '${package_base_name}-macos-universal-${normalized_version}.tar.gz' in content
    assert 'write_distribution_marker "$stage_dir" "macos" "macos-universal"' in content
    assert "macos_archive" in content
    assert "未找到 macOS 包" in content
    assert '"$windows_installer_archive" "$linux_archive" "$macos_archive"' in content


def test_publish_release_shell_generates_and_publishes_checksum_assets():
    content = Path(".release-local/publish-release.sh").read_text(encoding="utf-8")

    assert "checksum_archives=()" in content
    assert "new_sha256_file()" in content
    assert 'if [[ -z "${path//[[:space:]]/}" || ! -f "$path" ]]; then' in content
    assert 'local checksum_path="${path}.sha256"' in content
    assert 'printf \'%s  %s\\n\' "$hash" "$filename" > "$checksum_path"' in content
    assert "new_archive_checksum_files()" in content
    assert 'for archive in "${windows_archive:-}" "${windows_installer_archive:-}" "${linux_archive:-}" "${macos_archive:-}"; do' in content
    assert 'checksum_archives+=("$checksum")' in content
    assert 'release_assets+=("${checksum_archives[@]}")' in content
    assert 'windows_archive=""' in content
    assert content.index('  new_archive_checksum_files\n\n  if [[ "$should_publish" == "1" ]]; then') < content.index(
        'publish_github_release "$release_tag"'
    )


def test_publish_release_scripts_commit_before_archiving_and_validate_branch():
    powershell = Path(".release-local/publish-release.ps1").read_text(encoding="utf-8")
    shell = Path(".release-local/publish-release.sh").read_text(encoding="utf-8")

    assert "Assert-ReleaseBranch -ExpectedBranch $normalizedReleaseBranch" in powershell
    assert "Assert-OriginMatchesRepository -ExpectedRepository $ExpectedRepository" in powershell
    assert "HEAD:refs/heads/{0}" in powershell
    assert "PublishOnly 模式复用现有产物，不支持 dirty worktree" in powershell
    assert powershell.index("Commit-ReleaseChanges -NormalizedVersion $normalizedVersion") < powershell.index(
        "$archives = New-ReleaseArchives -NormalizedVersion $normalizedVersion"
    )

    assert 'assert_release_branch "$normalized_release_branch"' in shell
    assert 'assert_origin_matches_repository "$expected_repository"' in shell
    assert 'HEAD:refs/heads/$target_branch' in shell
    assert "PublishOnly 模式复用现有产物，不支持 dirty worktree" in shell
    assert shell.index('commit_release_changes "$normalized_version"') < shell.index(
        'new_release_archives "$normalized_version"'
    )
