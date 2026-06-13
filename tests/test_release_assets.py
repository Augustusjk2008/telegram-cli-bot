import json
import re
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


def test_portable_build_script_only_copies_tracked_files():
    content = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert 'ls-files' in content
    assert '-o --exclude-standard' not in content
    assert 'Write-Step "复制 tracked 文件"' in content
    assert ".distribution.json" in content
    assert "packageKind" in content
    assert 'Write-DistributionMarker -Root $packageRoot -PackageKind "portable" -Platform "windows-x64"' in content


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


def test_publish_release_restores_local_front_build_after_portable_package():
    ps1_content = Path(".release-local/publish-release.ps1").read_text(encoding="utf-8")
    sh_content = Path(".release-local/publish-release.sh").read_text(encoding="utf-8")

    assert "function Invoke-PostPortableFrontBuild" in ps1_content
    assert 'Invoke-FrontBuild -StepMessage "恢复本机前端构建产物"' in ps1_content
    ps1_archives = ps1_content[
        ps1_content.index("function New-ReleaseArchives"):
        ps1_content.index("function Get-ReleaseArchivePaths")
    ]
    assert ps1_archives.index('Write-Step "创建 Windows 绿色版包"') < ps1_archives.index(
        "Invoke-PostPortableFrontBuild"
    ) < ps1_archives.index('Write-Step "创建 Windows 安装版包"')

    assert "restore_front_build_after_portable()" in sh_content
    assert 'write_step "恢复本机前端构建产物"' in sh_content
    sh_archives = sh_content[
        sh_content.index("new_release_archives()"):
        sh_content.index("set_release_archive_paths()")
    ]
    assert sh_archives.index('write_step "创建 Windows 绿色版包"') < sh_archives.index(
        "restore_front_build_after_portable"
    ) < sh_archives.index('write_step "创建 Windows 安装版包"')


def test_publish_release_scripts_reference_existing_release_check_files():
    script_paths = [
        Path(".release-local/publish-release.ps1"),
        Path(".release-local/publish-release.sh"),
        Path(".release-local/portable-win/build-portable.ps1"),
    ]

    for script_path in script_paths:
        content = script_path.read_text(encoding="utf-8")
        referenced_paths = set(re.findall(r"(?:tests|src/test)/[-A-Za-z0-9_./]+", content))
        missing = []
        for referenced_path in referenced_paths:
            root = Path("front") if referenced_path.startswith("src/test/") else Path(".")
            if not (root / referenced_path).exists():
                missing.append(referenced_path)

        assert not missing, f"{script_path} references missing release check files: {sorted(missing)}"


