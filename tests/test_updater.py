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


def test_detect_update_package_kind_returns_macos_on_darwin(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CLI_BRIDGE_UPDATE_PACKAGE_KIND", raising=False)
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(updater.os, "name", "posix")

    assert updater.detect_update_package_kind(tmp_path) == "macos"


def test_macos_release_asset_selection_and_platform_label():
    asset = updater._select_release_asset(_windows_release_assets(), "macos")

    assert asset["browser_download_url"] == "https://example.invalid/macos.tar.gz"
    assert updater._pending_update_platform("macos") == "macos-universal"
    assert updater._expected_distribution_platform("macos") == "macos-universal"
    assert updater._format_update_package_kind("macos") == "macOS"


def test_download_latest_update_marks_macos_pending_bundle(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda repo_root=None: "macos")
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
        target.write_bytes(b"tar-bytes")

    monkeypatch.setattr(updater, "_download_file", fake_download)
    _mock_sha256_download(
        monkeypatch,
        {"orbit-safe-claw-macos-universal-1.2.0.tar.gz": b"tar-bytes"},
    )

    status = updater.download_latest_update(repo_root=tmp_path)

    assert status["pending_update_platform"] == "macos-universal"
    assert status["pending_update_package_kind"] == "macos"
    assert downloaded["url"] == "https://example.invalid/macos.tar.gz"
    assert str(downloaded["target"]).endswith("orbit-safe-claw-macos-universal-1.2.0.tar.gz")


def test_download_latest_update_replaces_unusable_repo_cache_path(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    blocked_cache_path = tmp_path / ".updates"
    blocked_cache_path.write_text("blocked", encoding="utf-8")
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

    cache_dir = tmp_path / ".updates"
    blocked_backups = list(tmp_path.glob(".updates.blocked-*"))
    assert cache_dir.is_dir()
    assert len(blocked_backups) == 1
    assert blocked_backups[0].read_text(encoding="utf-8") == "blocked"
    assert downloaded["url"] == "https://example.invalid/installer.zip"
    assert downloaded["target"] == cache_dir / "orbit-safe-claw-windows-x64-installer-1.2.0.zip"
    assert Path(status["pending_update_path"]).parent == cache_dir


def test_prepare_update_cache_dir_falls_back_when_repo_cache_cannot_be_repaired(monkeypatch, tmp_path: Path):
    repo_cache = tmp_path / ".updates"
    fallback_cache = tmp_path / "fallback-cache"
    progress_events: list[dict[str, object]] = []

    def fake_ensure(path: Path) -> None:
        if path == repo_cache:
            raise PermissionError(f"[Errno 13] Permission denied: '{path}'")
        path.mkdir(parents=True, exist_ok=True)

    def fake_reset(cache_root: Path, error: OSError, *, progress_callback=None) -> Path | None:
        return None

    monkeypatch.setattr(updater, "_ensure_writable_directory", fake_ensure)
    monkeypatch.setattr(updater, "_reset_blocked_cache_dir", fake_reset)
    monkeypatch.setattr(updater, "_fallback_update_cache_dir", lambda repo_root: fallback_cache)

    result = updater._prepare_update_cache_dir(tmp_path, progress_callback=progress_events.append)

    assert result == fallback_cache
    assert fallback_cache.exists()
    assert any("改用备用目录" in str(event.get("message") or "") for event in progress_events)


def test_fetch_latest_release_uses_git_proxy_port(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    app_settings.update_git_proxy_port("7897")

    payload = {
        "tag_name": "v1.0.1",
        "html_url": "https://github.com/owner/repo/releases/tag/v1.0.1",
        "body": "Bugfixes",
        "assets": [],
    }
    captured: dict[str, object] = {}

    class FakeResponse:
        headers: dict[str, str] = {}

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=20):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(handler):
        captured["proxies"] = dict(getattr(handler, "proxies", {}))
        return FakeOpener()

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("should use opener instead of urllib.request.urlopen")

    monkeypatch.setattr(updater.urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fail_urlopen)

    release = updater._fetch_latest_release()

    assert release["tag_name"] == "v1.0.1"
    assert captured["url"] == "https://api.github.com/repos/owner/repo/releases/latest"
    assert captured["timeout"] == 20
    assert captured["proxies"] == {
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    }


def test_download_file_rejects_invalid_zip_archive(monkeypatch, tmp_path: Path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", "# updated\n")
    invalid_zip_bytes = buffer.getvalue()[:-22]

    class FakeResponse:
        headers = {"Content-Length": str(len(invalid_zip_bytes))}

        def __init__(self):
            self._chunks = [invalid_zip_bytes[:7], invalid_zip_bytes[7:], b""]

        def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=60):
            return FakeResponse()

    monkeypatch.setattr(updater, "_build_url_opener", lambda: FakeOpener())

    target = tmp_path / "release.zip"
    with pytest.raises(RuntimeError, match="更新包已损坏"):
        updater._download_file("https://example.invalid/release.zip", target)

    assert not target.exists()


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


def test_apply_pending_update_preserves_legacy_announcement_reads(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    (repo_root / ".web_announcements.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-05-26T14:18:08+08:00",
                "items": [{"id": "old"}],
                "reads": {
                    "local-admin": {
                        "last_seen_id": "old",
                        "seen_at": "2026-05-26T14:18:08+08:00",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive)
        archive.writestr(
            ".web_announcements.json",
            json.dumps(
                {
                    "version": 1,
                    "updated_at": "2026-05-27T09:00:00+08:00",
                    "items": [{"id": "new"}],
                },
                ensure_ascii=False,
            ),
        )

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is True
    content_after = json.loads((repo_root / ".web_announcements.json").read_text(encoding="utf-8"))
    reads_after = json.loads((repo_root / ".web_announcement_reads.json").read_text(encoding="utf-8"))
    assert "reads" not in content_after
    assert content_after["items"] == [{"id": "new"}]
    assert reads_after == {
        "version": 1,
        "updated_at": "2026-05-26T14:18:08+08:00",
        "reads": {
            "local-admin": {
                "last_seen_id": "old",
                "seen_at": "2026-05-26T14:18:08+08:00",
            },
        },
    }


def test_apply_pending_update_builds_frontend_before_clearing_pending(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive)
        archive.writestr("front/src/app.ts", "export const x = 1;\n")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    build_calls: list[Path] = []

    def fake_build_frontend(path: Path):
        build_calls.append(path)
        return True, "build ok"

    monkeypatch.setattr(updater, "_build_updated_frontend", fake_build_frontend)

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is True
    assert result["frontend_built"] is True
    assert build_calls == [repo_root]
    assert app_settings._load_settings()["pending_update_version"] == ""


def test_apply_pending_update_skips_frontend_build_when_frontend_unchanged(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    (repo_root / "front").mkdir()
    (repo_root / "front" / "dist").mkdir(parents=True)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive)
        archive.writestr("README.md", "# updated\n")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(
        updater,
        "_build_updated_frontend",
        lambda path: (_ for _ in ()).throw(AssertionError("should skip frontend build")),
    )

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is True
    assert result["frontend_built"] is False


def test_apply_pending_update_keeps_pending_update_when_frontend_build_fails(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive)
        archive.writestr("front/src/app.ts", "export const x = 1;\n")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(updater, "_build_updated_frontend", lambda path: (False, "npm run build failed"))

    result = updater.apply_pending_update(repo_root)
    saved_settings = app_settings._load_settings()

    assert result["applied"] is False
    assert result["reason"] == "frontend_build_failed"
    assert saved_settings["pending_update_version"] == "1.0.1"
    assert "npm run build failed" in saved_settings["update_last_error"]


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


def test_apply_pending_update_rolls_back_new_file_written_from_stream(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    (repo_root / "front").mkdir()

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive, version="2.0.0")
        archive.writestr("front/src/version.ts", "export const VERSION = 'new'\n")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "2.0.0"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(updater, "_build_updated_frontend", lambda path: (False, "npm run build failed"))

    result = updater.apply_pending_update(repo_root)

    assert result["applied"] is False
    assert not (repo_root / "front" / "src" / "version.ts").exists()


def test_apply_pending_update_recovers_interrupted_journal_before_pending_check(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    target = repo_root / "bot" / "version.py"
    target.parent.mkdir(parents=True)
    target.write_text("VERSION = 'new'\n", encoding="utf-8")
    temp_root = repo_root / ".update-apply-crashed"
    temp_root.mkdir()
    backup = temp_root / "backup-0000"
    backup.write_text("VERSION = 'old'\n", encoding="utf-8")
    staged = target.parent / ".version.py.update-leftover.tmp"
    staged.write_text("partial\n", encoding="utf-8")
    journal = temp_root / "journal.jsonl"
    journal.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "backup",
                        "target_path": str(target),
                        "relative_path": "bot/version.py",
                        "backup_path": str(backup),
                        "write_path": "",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event": "stage",
                        "target_path": str(target),
                        "relative_path": "bot/version.py",
                        "backup_path": str(backup),
                        "write_path": str(staged),
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = updater.apply_pending_update(repo_root)

    assert result["reason"] == "no_pending_update"
    assert target.read_text(encoding="utf-8") == "VERSION = 'old'\n"
    assert not staged.exists()
    assert not temp_root.exists()


def test_apply_pending_update_handles_invalid_package(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    package_path.write_bytes(b"PK\x03\x04not-a-real-zip")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(
        updater,
        "_build_updated_frontend",
        lambda path: (_ for _ in ()).throw(AssertionError("should not build frontend for invalid package")),
    )

    log_lines: list[str] = []
    result = updater.apply_pending_update(repo_root, log_callback=log_lines.append)
    saved_settings = app_settings._load_settings()

    assert result["applied"] is False
    assert result["reason"] == "invalid_package"
    assert "更新包已损坏" in saved_settings["update_last_error"]
    assert any("更新包已损坏" in line for line in log_lines)


def test_apply_pending_update_rejects_checksum_mismatch(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    package_path.write_bytes(b"changed")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    current_settings["pending_update_sha256"] = hashlib.sha256(b"original").hexdigest()
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(
        updater,
        "_build_updated_frontend",
        lambda path: (_ for _ in ()).throw(AssertionError("should not build frontend for checksum mismatch")),
    )

    result = updater.apply_pending_update(repo_root)
    saved_settings = app_settings._load_settings()

    assert result["applied"] is False
    assert result["reason"] == "checksum_mismatch"
    assert saved_settings["pending_update_version"] == "1.0.1"
    assert saved_settings["pending_update_path"] == str(package_path)
    assert "SHA256" in saved_settings["update_last_error"]


def test_apply_pending_update_handles_package_path_listing_failure(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        _write_distribution_marker(archive)
        archive.writestr("bot/version.py", "VERSION = 'new'\n")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(
        updater,
        "_list_package_entry_paths",
        lambda _path: (_ for _ in ()).throw(updater._PackageStreamError("更新包已损坏，请重新下载: release.zip")),
    )

    result = updater.apply_pending_update(repo_root)
    saved_settings = app_settings._load_settings()

    assert result["applied"] is False
    assert result["reason"] == "invalid_package"
    assert saved_settings["pending_update_version"] == ""
    assert "更新包已损坏" in saved_settings["update_last_error"]


def test_apply_pending_update_skips_when_current_version_matches_pending(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = APP_VERSION
    current_settings["pending_update_path"] = str(tmp_path / "missing.zip")
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    monkeypatch.setattr(
        updater,
        "_build_updated_frontend",
        lambda path: (_ for _ in ()).throw(AssertionError("should not build frontend when version already matches")),
    )

    log_lines: list[str] = []
    result = updater.apply_pending_update(repo_root, log_callback=log_lines.append)
    saved_settings = app_settings._load_settings()

    assert result == {
        "applied": False,
        "skipped": True,
        "reason": "already_current_version",
        "version": APP_VERSION,
    }
    assert saved_settings["pending_update_version"] == ""
    assert saved_settings["pending_update_path"] == ""
    assert any(f"当前版本已是 {APP_VERSION}" in line for line in log_lines)


def test_updater_main_treats_matching_pending_version_as_success(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = APP_VERSION
    current_settings["pending_update_path"] = str(tmp_path / "missing.zip")
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    assert updater.main(["apply-pending", "--repo-root", str(repo_root)]) == 0


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


def test_read_package_distribution_from_zip_reads_only_marker(monkeypatch, tmp_path: Path):
    package = tmp_path / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("large.bin", b"x" * 1024)
        _write_distribution_marker(archive, version="1.2.3")

    original_read = zipfile.ZipFile.read
    read_names: list[str] = []

    def tracking_read(self, name, *args, **kwargs):
        read_names.append(getattr(name, "filename", str(name)))
        return original_read(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", tracking_read)

    distribution = updater._read_package_distribution_from_package(package)

    assert distribution["version"] == "1.2.3"
    assert read_names == [".distribution.json"]


def test_prepare_offline_update_rejects_wrong_package_kind(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    package = tmp_path / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            ".distribution.json",
            json.dumps({"packageKind": "portable", "platform": "windows-x64"}, ensure_ascii=False),
        )
        archive.writestr("bot/version.py", "APP_VERSION = '1.2.3'\n")

    monkeypatch.setattr(updater, "detect_update_package_kind", lambda root=None: "installer")

    with pytest.raises(RuntimeError, match="包类型"):
        updater.prepare_offline_update(repo_root, package, version="1.2.3")


def test_prepare_offline_update_accepts_macos_tar_package(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda root=None: "macos")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    package = tmp_path / "offline.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        distribution = json.dumps(
            {"packageKind": "macos", "platform": "macos-universal", "version": "1.2.3"},
            ensure_ascii=False,
        ).encode("utf-8")
        marker_info = tarfile.TarInfo(".distribution.json")
        marker_info.size = len(distribution)
        archive.addfile(marker_info, io.BytesIO(distribution))
        version_bytes = b"APP_VERSION = '1.2.3'\n"
        version_info = tarfile.TarInfo("bot/version.py")
        version_info.size = len(version_bytes)
        archive.addfile(version_info, io.BytesIO(version_bytes))

    status = updater.prepare_offline_update(repo_root, package, version="1.2.3")

    assert status["pending_update_package_kind"] == "macos"
    assert status["pending_update_platform"] == "macos-universal"
