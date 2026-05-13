import io
import json
import zipfile
from pathlib import Path

import pytest

from bot import app_settings, updater
from bot.version import APP_VERSION


def _windows_release_assets() -> list[dict[str, str]]:
    return [
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
    ]


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


def test_detect_update_package_kind_uses_distribution_marker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)
    (tmp_path / ".distribution.json").write_text(
        json.dumps({"packageKind": "portable", "platform": "windows-x64"}),
        encoding="utf-8",
    )

    assert updater.detect_update_package_kind(tmp_path) == "portable"


def test_detect_update_package_kind_ignores_windows_marker_on_linux(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: False)
    (tmp_path / ".distribution.json").write_text(
        json.dumps({"packageKind": "installer", "platform": "windows-x64"}),
        encoding="utf-8",
    )

    assert updater.detect_update_package_kind(tmp_path) == "linux"


def test_detect_update_package_kind_falls_back_to_portable_layout(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "portable_bootstrap.py").write_text("", encoding="utf-8")
    (tmp_path / "runtime" / "python").mkdir()
    (tmp_path / "runtime" / "python" / "python.exe").write_text("", encoding="utf-8")

    assert updater.detect_update_package_kind(tmp_path) == "portable"


def test_detect_update_package_kind_defaults_to_installer_on_windows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)

    assert updater.detect_update_package_kind(tmp_path) == "installer"


def test_select_release_asset_uses_installer_asset_on_windows(monkeypatch):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)

    asset = updater._select_release_asset(_windows_release_assets(), "installer")

    assert asset["name"] == "orbit-safe-claw-windows-x64-installer-1.2.0.zip"


def test_select_release_asset_uses_portable_asset_on_windows(monkeypatch):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)

    asset = updater._select_release_asset(_windows_release_assets(), "portable")

    assert asset["name"] == "orbit-safe-claw-windows-x64-1.2.0.zip"


def test_select_release_asset_uses_linux_asset_for_linux_package_kind(monkeypatch):
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)

    asset = updater._select_release_asset(_windows_release_assets(), "linux")

    assert asset["name"] == "orbit-safe-claw-linux-x64-1.2.0.tar.gz"


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

    status = updater.download_latest_update(repo_root=tmp_path)

    assert status["pending_update_version"] == "1.0.1"
    assert status["pending_update_platform"] == "windows-x64-installer"
    assert status["pending_update_package_kind"] == "installer"
    assert downloaded["url"] == "https://example.invalid/installer.zip"
    assert Path(status["pending_update_path"]).exists()
    assert Path(status["pending_update_path"]).parent == cache_dir


def test_download_latest_update_forwards_progress_callback(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda repo_root=None: "portable")
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

    progress_events: list[dict[str, object]] = []

    def fake_download(url, target, progress_callback=None):
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "starting",
                    "downloaded_bytes": 0,
                    "total_bytes": 1024,
                    "percent": 0,
                }
            )
        target.write_bytes(b"zip-bytes")
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "downloading",
                    "downloaded_bytes": 1024,
                    "total_bytes": 1024,
                    "percent": 100,
                }
            )

    monkeypatch.setattr(updater, "_download_file", fake_download)

    status = updater.download_latest_update(repo_root=tmp_path, progress_callback=progress_events.append)

    assert status["pending_update_version"] == "1.0.1"
    assert progress_events[0] == {
        "phase": "log",
        "downloaded_bytes": 0,
        "total_bytes": None,
        "percent": 0,
        "message": "正在检查最新版本信息",
    }
    assert progress_events[1] == {
        "phase": "log",
        "downloaded_bytes": 0,
        "total_bytes": None,
        "percent": 0,
        "message": "当前安装类型: Windows 绿色版",
    }
    assert progress_events[2] == {
        "phase": "log",
        "downloaded_bytes": 0,
        "total_bytes": None,
        "percent": 0,
        "message": "找到更新包: cli-bridge-windows-x64.zip",
    }
    assert progress_events[3:5] == [
        {
            "phase": "starting",
            "downloaded_bytes": 0,
            "total_bytes": 1024,
            "percent": 0,
        },
        {
            "phase": "downloading",
            "downloaded_bytes": 1024,
            "total_bytes": 1024,
            "percent": 100,
        },
    ]
    assert "更新包已保存到:" in str(progress_events[-1]["message"])


def test_download_latest_update_prints_progress_without_callback(monkeypatch, tmp_path: Path, capsys):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(updater, "APP_UPDATE_REPOSITORY", "owner/repo")
    monkeypatch.setattr(updater, "_is_windows_runtime", lambda: True)
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda repo_root=None: "portable")
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

    def fake_download(url, target, progress_callback=None):
        assert progress_callback is not None
        progress_callback(
            {
                "phase": "log",
                "downloaded_bytes": 0,
                "total_bytes": 1024,
                "percent": 0,
                "message": "开始下载更新包: cli-bridge-windows-x64.zip",
            }
        )
        target.write_bytes(b"zip-bytes")
        progress_callback(
            {
                "phase": "log",
                "downloaded_bytes": 1024,
                "total_bytes": 1024,
                "percent": 100,
                "message": "已下载 1024 / 1024 bytes (100%)",
            }
        )

    monkeypatch.setattr(updater, "_download_file", fake_download)

    status = updater.download_latest_update(repo_root=tmp_path)

    output = capsys.readouterr().out
    assert status["pending_update_version"] == "1.0.1"
    assert "开始下载更新包: cli-bridge-windows-x64.zip" in output
    assert "100%" in output


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


def test_download_file_emits_text_log_messages(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    app_settings.update_git_proxy_port("7897")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", "# updated\n")
    zip_bytes = buffer.getvalue()

    class FakeResponse:
        headers = {"Content-Length": str(len(zip_bytes))}

        def __init__(self):
            self._chunks = [zip_bytes[:16], zip_bytes[16:], b""]

        def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=60):
            return FakeResponse()

    def fake_build_opener(handler):
        return FakeOpener()

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("should use opener instead of urllib.request.urlopen")

    monkeypatch.setattr(updater.urllib.request, "build_opener", fake_build_opener)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fail_urlopen)

    progress_events: list[dict[str, object]] = []
    updater._download_file(
        "https://example.invalid/cli-bridge-windows-x64.zip",
        tmp_path / "release.zip",
        progress_callback=progress_events.append,
    )

    assert (tmp_path / "release.zip").read_bytes() == zip_bytes
    assert any(str(event.get("message") or "").strip() for event in progress_events)


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
    settings_file.write_text(json.dumps({"pending_update_version": "1.0.1"}), encoding="utf-8")

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("README.md", "# updated\n")
        archive.writestr(".env", "WEB_API_TOKEN=replace-me\n")
        archive.writestr(".web_admin_settings.json", "{\"bad\":true}")
        archive.writestr(".web_tunnel_state.json", "{\"public_url\":\"https://replace.trycloudflare.com\"}")

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
    assert app_settings._load_settings()["pending_update_version"] == ""


def test_apply_pending_update_builds_frontend_before_clearing_pending(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("README.md", "# updated\n")

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


def test_apply_pending_update_keeps_pending_update_when_frontend_build_fails(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("README.md", "# updated\n")

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


def test_apply_pending_update_reports_progress_logs(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings_file = repo_root / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)

    package_path = tmp_path / "release.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("README.md", "# updated\n")
        archive.writestr("front/dist/index.html", "<html></html>")

    current_settings = app_settings._load_settings()
    current_settings["pending_update_version"] = "1.0.1"
    current_settings["pending_update_path"] = str(package_path)
    current_settings["pending_update_platform"] = "windows-x64"
    app_settings._save_settings(current_settings)

    log_lines: list[str] = []
    monkeypatch.setattr(updater, "_build_updated_frontend", lambda path: (True, "frontend build ok"))

    result = updater.apply_pending_update(repo_root, log_callback=log_lines.append)

    assert result["applied"] is True
    assert any("开始应用待更新版本" in line for line in log_lines)
    assert any("正在更新: README.md" in line for line in log_lines)
    assert any("正在重建前端资源" in line for line in log_lines)
    assert any("前端资源重建完成" in line for line in log_lines)


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


def test_list_offline_update_packages_reads_release_artifacts(tmp_path: Path):
    repo_root = tmp_path / "repo"
    artifacts_dir = repo_root / ".release-local" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    package = artifacts_dir / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("bot/version.py", "APP_VERSION = '1.2.3'\n")

    listing = updater.list_offline_update_packages(repo_root)

    assert listing["artifacts_dir"] == str(artifacts_dir)
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["name"] == "offline.zip"
    assert item["path"] == str(package)
    assert item["size"] == package.stat().st_size
    assert item["size_bytes"] == package.stat().st_size
    assert item["package_kind"] == updater.detect_update_package_kind(repo_root)
    assert item["valid"] is True
    assert item["error"] == ""


def test_list_offline_update_packages_does_not_validate_archive_contents(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    artifacts_dir = repo_root / ".release-local" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    package = artifacts_dir / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("bot/version.py", "APP_VERSION = '1.2.3'\n")

    monkeypatch.setattr(
        updater,
        "_validate_package_file",
        lambda _path: (_ for _ in ()).throw(AssertionError("listing should not validate archive contents")),
    )

    listing = updater.list_offline_update_packages(repo_root)

    assert listing["items"][0]["name"] == "offline.zip"
    assert listing["items"][0]["valid"] is True
    assert listing["items"][0]["error"] == ""


def test_prepare_offline_update_sets_pending_update(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / ".web_admin_settings.json"
    monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", settings_file)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    package = tmp_path / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("bot/version.py", "APP_VERSION = '1.2.3'\n")

    status = updater.prepare_offline_update(repo_root, package, version="1.2.3", log_callback=lambda _line: None)

    assert status["pending_update_version"] == "1.2.3"
    assert status["pending_update_path"] == str(package)
    assert status["pending_update_package_kind"] == updater.detect_update_package_kind(repo_root)
