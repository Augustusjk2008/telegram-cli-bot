import io
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from bot import app_settings, updater
from bot.version import APP_VERSION


def _windows_release_assets() -> list[dict[str, str]]:
    package_assets = [
        {
            "name": "orbit-safe-claw-windows-x64-1.2.0.zip",
            "browser_download_url": "https://example.invalid/portable.zip",
        },
        {
            "name": "orbit-safe-claw-windows-x64-installer-1.2.0.zip",
            "browser_download_url": "https://example.invalid/installer.zip",
        },
        {
            "name": "orbit-safe-claw-linux-x64-1.2.0.tar.gz",
            "browser_download_url": "https://example.invalid/linux.tar.gz",
        },
        {
            "name": "orbit-safe-claw-macos-universal-1.2.0.tar.gz",
            "browser_download_url": "https://example.invalid/macos.tar.gz",
        },
    ]
    return [
        item
        for asset in package_assets
        for item in (
            asset,
            {
                "name": f"{asset['name']}.sha256",
                "browser_download_url": f"{asset['browser_download_url']}.sha256",
            },
        )
    ]


def _sha256_text(data: bytes, package_name: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()}  {package_name}\n"


def _mock_sha256_download(monkeypatch, payloads: dict[str, bytes]) -> None:
    def fake_download_text(url, target):
        package_name = Path(str(target)).name.removesuffix(".sha256")
        target.write_text(_sha256_text(payloads[package_name], package_name), encoding="utf-8")

    monkeypatch.setattr(updater, "_download_text_file", fake_download_text)


def _write_distribution_marker(
    archive: zipfile.ZipFile,
    *,
    package_kind: str = "installer",
    platform: str = "windows-x64",
    version: str = "1.0.1",
) -> None:
    archive.writestr(
        ".distribution.json",
        json.dumps(
            {
                "packageKind": package_kind,
                "platform": platform,
                "version": version,
            },
            ensure_ascii=False,
        ),
    )


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
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda repo_root=None: "installer")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.1",
            "body": "Bugfixes",
            "assets": _windows_release_assets(),
        },
    )
    downloaded: dict[str, object] = {}

    def fake_download(url, target, progress_callback=None):
        downloaded["url"] = url
        downloaded["target"] = target
        target.write_bytes(b"zip-bytes")

    monkeypatch.setattr(updater, "_download_file", fake_download)
    _mock_sha256_download(
        monkeypatch,
        {"orbit-safe-claw-windows-x64-installer-1.2.0.zip": b"zip-bytes"},
    )

    status = updater.download_latest_update(repo_root=tmp_path)

    assert status["pending_update_version"] == "1.0.1"
    assert status["pending_update_platform"] == "windows-x64-installer"
    assert status["pending_update_package_kind"] == "installer"
    assert downloaded["url"] == "https://example.invalid/installer.zip"
    assert Path(status["pending_update_path"]).exists()
    assert Path(status["pending_update_path"]).parent == cache_dir
    assert status["pending_update_sha256"] == hashlib.sha256(b"zip-bytes").hexdigest()


def test_download_latest_update_rejects_checksum_mismatch(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda repo_root=None: "installer")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.1",
            "body": "Bugfixes",
            "assets": _windows_release_assets(),
        },
    )

    def fake_download(url, target, progress_callback=None):
        target.write_bytes(b"zip-bytes")

    monkeypatch.setattr(updater, "_download_file", fake_download)
    _mock_sha256_download(
        monkeypatch,
        {"orbit-safe-claw-windows-x64-installer-1.2.0.zip": b"other-bytes"},
    )

    with pytest.raises(RuntimeError, match="SHA256"):
        updater.download_latest_update(repo_root=tmp_path)

    saved = app_settings._load_settings()
    assert saved["pending_update_version"] == ""
    assert "SHA256" in saved["update_last_error"]


def test_apply_pending_update_skips_local_state_files(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    (repo_root / ".env").write_text("WEB_API_TOKEN=keep-me\n", encoding="utf-8")
    (repo_root / ".web_tunnel_state.json").write_text(
        json.dumps({"public_url": "https://keep.trycloudflare.com"}),
        encoding="utf-8",
    )
    (repo_root / ".web_lan_chat.json").write_text(json.dumps({"mode": "host"}), encoding="utf-8")
    (repo_root / ".web_lan_chat_messages.json").write_text(json.dumps({"messages": [{"text": "keep"}]}), encoding="utf-8")
    settings_file.write_text(json.dumps({"pending_update_version": "1.0.1"}), encoding="utf-8")

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive)
        archive.writestr("README.md", "# updated\n")
        archive.writestr(".env", "WEB_API_TOKEN=replace-me\n")
        archive.writestr(".web_admin_settings.json", "{\"bad\":true}")
        archive.writestr(".web_tunnel_state.json", "{\"public_url\":\"https://replace.trycloudflare.com\"}")
        archive.writestr(".web_lan_chat.json", "{\"mode\":\"off\"}")
        archive.writestr(".web_lan_chat_messages.json", "{\"messages\":[]}")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is True
    assert (repo_root / "README.md").read_text(encoding="utf-8") == "# updated\n"
    assert (repo_root / ".env").read_text(encoding="utf-8") == "WEB_API_TOKEN=keep-me\n"
    assert json.loads((repo_root / ".web_tunnel_state.json").read_text(encoding="utf-8")) == {
        "public_url": "https://keep.trycloudflare.com"
    }
    assert json.loads((repo_root / ".web_lan_chat.json").read_text(encoding="utf-8")) == {"mode": "host"}
    assert json.loads((repo_root / ".web_lan_chat_messages.json").read_text(encoding="utf-8")) == {
        "messages": [{"text": "keep"}]
    }
    assert app_settings._load_settings()["pending_update_version"] == ""


def test_apply_pending_update_rolls_back_files_when_frontend_build_fails(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    target = repo_root / "bot" / "version.py"
    target.parent.mkdir(parents=True)
    target.write_text("VERSION = 'old'\n", encoding="utf-8")

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive, version="2.0.0")
        archive.writestr("bot/version.py", "VERSION = 'new'\n")
        archive.writestr("front/src/app.ts", "export const x = 1;\n")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "2.0.0"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(updater, "_build_updated_frontend", lambda path: (False, "npm run build failed"))

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is False
    assert result["reason"] == "frontend_build_failed"
    assert target.read_text(encoding="utf-8") == "VERSION = 'old'\n"
    saved_settings = app_settings._load_settings()
    assert saved_settings["pending_update_version"] == "2.0.0"
    assert saved_settings["pending_update_path"] == str(package_path)


def test_prepare_offline_update_sets_pending_update(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    package = tmp_path / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        _write_distribution_marker(archive, version="1.2.3")
        archive.writestr("bot/version.py", "APP_VERSION = '1.2.3'\n")

    status = updater.prepare_offline_update(repo_root, package, version="1.2.3", log_callback=lambda _line: None)

    assert status["pending_update_version"] == "1.2.3"
    assert status["pending_update_path"] == str(package)
    assert status["pending_update_package_kind"] == updater.detect_update_package_kind(repo_root)


