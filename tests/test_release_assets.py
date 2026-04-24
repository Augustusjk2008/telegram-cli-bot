import json
from pathlib import Path


def test_agents_and_claude_guides_stay_in_sync():
    assert Path("AGENTS.md").read_text(encoding="utf-8") == Path("CLAUDE.md").read_text(encoding="utf-8")


def test_repo_ignores_runtime_state_and_tracks_example_bot_config():
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "managed_bots.json" in ignore
    assert ".web_admin_settings.json" in ignore
    assert ".updates/" in ignore
    assert ".release-local/" in ignore

    example = json.loads(Path("managed_bots.example.json").read_text(encoding="utf-8"))
    assert isinstance(example["bots"], list)


def test_readme_mentions_linux_entrypoints_and_update_flow():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "install.sh" in readme
    assert "start.sh" in readme
    assert "GitHub Release" in readme
    assert "重启后生效" in readme
    assert "releases/latest" in readme
    assert "archive/refs/heads/master" in readme
    assert "相关文档：" not in readme


def test_local_release_script_supports_version_bump_and_publish():
    content = Path(".release-local/publish-release.ps1").read_text(encoding="utf-8")

    assert '[string]$Version' in content
    assert 'ValidateSet("BuildAndPublish", "BuildOnly", "PublishOnly")' in content
    assert '$Mode = "BuildAndPublish"' in content
    assert '$RunChecks' in content
    assert "AllowDirtyWorktree" in content
    assert "AutoConfirmDirtyWorktree" in content
    assert "Read-Host" in content
    assert 'Set-Content -LiteralPath $script:VersionFile' in content
    assert "Commit-ReleaseChanges" in content
    assert 'git" -Arguments @("add", "-A")' in content
    assert 'git" -Arguments @("add", "--", "VERSION")' not in content
    assert '"{0}-windows-x64-{1}.zip"' in content
    assert '"{0}-windows-x64-installer-{1}.zip"' in content
    assert '"{0}-linux-x64-{1}.tar.gz"' in content
    assert "WindowsInstallerArchive" in content
    assert "portable-win\\build-portable.ps1" in content


def test_agent_guides_document_the_release_command():
    content = Path("AGENTS.md").read_text(encoding="utf-8")

    assert ".release-local/publish-release.ps1" in content
    assert "-Version <version>" in content
    assert "-RunChecks" in content


def test_windows_frontend_rebuild_script_installs_dependencies_before_build():
    content = Path("scripts/build_web_frontend.bat").read_text(encoding="utf-8").lower()

    install_index = content.find("npm install")
    build_index = content.find("npm run build")

    assert install_index != -1
    assert build_index != -1
    assert install_index < build_index
