import json
import zipfile
from pathlib import Path

from bot import app_settings, updater
from bot.version import APP_VERSION


def test_get_update_status_defaults_to_current_version(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    status = updater.get_update_status()

    assert status["current_version"] == APP_VERSION
    assert status["update_enabled"] is True
    assert status["update_channel"] == "release"
    assert status["pending_update_version"] == ""


def test_check_for_updates_persists_latest_release_metadata(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.1",
            "body": "Bugfixes",
            "assets": [],
        },
    )

    status = updater.check_for_updates()

    assert status["last_available_version"] == "1.0.1"
    assert status["last_available_release_url"].endswith("v1.0.1")
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["last_available_version"] == "1.0.1"


def test_download_latest_update_marks_pending_bundle(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    cache_dir = tmp_path / ".updates"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "UPDATE_CACHE_DIR_NAME", ".updates")
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.1",
            "body": "Bugfixes",
            "assets": [
                {
                    "name": "cli-bridge-windows-x64.zip",
                    "browser_download_url": "https://example.invalid/cli-bridge-windows-x64.zip",
                }
            ],
        },
    )
    monkeypatch.setattr(
        updater,
        "_download_file",
        lambda url, target: target.write_bytes(b"zip-bytes"),
    )

    status = updater.download_latest_update(repo_root=tmp_path)

    assert status["pending_update_version"] == "1.0.1"
    assert Path(status["pending_update_path"]).exists()
    assert Path(status["pending_update_path"]).parent == cache_dir


def test_apply_pending_update_skips_local_state_files(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    (repo_root / ".env").write_text("WEB_API_TOKEN=keep-me\n", encoding="utf-8")
    settings_file.write_text(json.dumps({"pending_update_version": "1.0.1"}), encoding="utf-8")

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("README.md", "# updated\n")
        archive.writestr(".env", "WEB_API_TOKEN=replace-me\n")
        archive.writestr(".web_admin_settings.json", "{\"bad\":true}")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is True
    assert (repo_root / "README.md").read_text(encoding="utf-8") == "# updated\n"
    assert (repo_root / ".env").read_text(encoding="utf-8") == "WEB_API_TOKEN=keep-me\n"
    assert app_settings._load_settings()["pending_update_version"] == ""
