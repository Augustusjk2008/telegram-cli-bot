"""GitHub Release based updater."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot import app_settings
from bot.config import APP_UPDATE_REPOSITORY
from bot.runtime_paths import get_announcements_content_path
from bot.version import APP_VERSION

UPDATE_CACHE_DIR_NAME = ".updates"
DOWNLOAD_CHUNK_SIZE = 64 * 1024
PROTECTED_UPDATE_PATHS = {
    ".env",
    "managed_bots.json",
    ".session_store.json",
    ".web_admin_settings.json",
    ".web_announcement_reads.json",
    ".web_tunnel_state.json",
    ".web_lan_chat.json",
    ".web_lan_chat_messages.json",
    ".assistant",
    ".claude",
    ".git",
    ".updates",
}
DISTRIBUTION_MARKER_FILE = ".distribution.json"
ANNOUNCEMENTS_FILE = ".web_announcements.json"
ANNOUNCEMENT_READS_FILE = ".web_announcement_reads.json"
WINDOWS_INSTALLER_PACKAGE_KIND = "installer"
WINDOWS_PORTABLE_PACKAGE_KIND = "portable"
LINUX_PACKAGE_KIND = "linux"
MACOS_PACKAGE_KIND = "macos"
UNKNOWN_PACKAGE_KIND = "unknown"
SUPPORTED_UPDATE_PACKAGE_KINDS = {
    WINDOWS_INSTALLER_PACKAGE_KIND,
    WINDOWS_PORTABLE_PACKAGE_KIND,
    LINUX_PACKAGE_KIND,
    MACOS_PACKAGE_KIND,
}
FRONTEND_BUILD_TRIGGER_PATHS = {
    "scripts/build_web_frontend.bat",
    "scripts/build_web_frontend.sh",
}


class _PackageStreamError(RuntimeError):
    pass


def get_update_status(repo_root: Path | None = None) -> dict[str, Any]:
    settings = app_settings._load_settings()
    return {
        "current_version": APP_VERSION,
        "current_package_kind": detect_update_package_kind(repo_root),
        "update_enabled": bool(settings["update_enabled"]),
        "update_channel": settings["update_channel"] or "release",
        "last_checked_at": settings["last_checked_at"],
        "last_available_version": settings["last_available_version"],
        "last_available_release_url": settings["last_available_release_url"],
        "last_available_notes": settings["last_available_notes"],
        "pending_update_version": settings["pending_update_version"],
        "pending_update_path": settings["pending_update_path"],
        "pending_update_notes": settings["pending_update_notes"],
        "pending_update_platform": settings["pending_update_platform"],
        "pending_update_package_kind": settings["pending_update_package_kind"],
        "pending_update_sha256": settings.get("pending_update_sha256", ""),
        "update_last_error": settings["update_last_error"],
    }


def set_update_enabled(enabled: bool, repo_root: Path | None = None) -> dict[str, Any]:
    settings = app_settings._load_settings()
    settings["update_enabled"] = bool(enabled)
    app_settings._save_settings(settings)
    return get_update_status(repo_root)


def check_for_updates(repo_root: Path | None = None) -> dict[str, Any]:
    settings = app_settings._load_settings()
    settings["last_checked_at"] = _now_iso()
    settings["update_last_error"] = ""

    try:
        release = _fetch_latest_release()
    except Exception as exc:
        settings["update_last_error"] = str(exc)
        app_settings._save_settings(settings)
        return get_update_status(repo_root)

    settings["last_available_version"] = _normalize_tag_name(release.get("tag_name"))
    settings["last_available_release_url"] = str(release.get("html_url") or "")
    settings["last_available_notes"] = str(release.get("body") or "")
    app_settings._save_settings(settings)
    return get_update_status(repo_root)


def _build_url_opener():
    proxy_url = app_settings.get_git_proxy_url()
    if proxy_url:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            )
        )
    return urllib.request.build_opener()


def detect_update_package_kind(repo_root: Path | None = None) -> str:
    override = _normalize_update_package_kind(os.environ.get("CLI_BRIDGE_UPDATE_PACKAGE_KIND"))
    if override:
        return override

    if sys.platform == "darwin":
        return MACOS_PACKAGE_KIND
    if not _is_windows_runtime():
        return LINUX_PACKAGE_KIND
    root = Path(repo_root or Path.cwd()).resolve()
    marker_kind = _read_distribution_marker_kind(root)
    if marker_kind:
        return marker_kind
    if _looks_like_portable_install(root):
        return WINDOWS_PORTABLE_PACKAGE_KIND
    return WINDOWS_INSTALLER_PACKAGE_KIND


def _is_windows_runtime() -> bool:
    return os.name == "nt"


def _normalize_update_package_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    return kind if kind in SUPPORTED_UPDATE_PACKAGE_KINDS else ""


def _read_distribution_marker_kind(repo_root: Path) -> str:
    marker_path = repo_root / DISTRIBUTION_MARKER_FILE
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return _normalize_update_package_kind(payload.get("packageKind") or payload.get("package_kind"))


def _looks_like_portable_install(repo_root: Path) -> bool:
    return (
        (repo_root / "runtime" / "portable_bootstrap.py").exists()
        and (repo_root / "runtime" / "python" / "python.exe").exists()
    ) or (repo_root / "PORTABLE-README.txt").exists()


def download_latest_update(
    repo_root: Path | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    effective_progress_callback = progress_callback or _print_download_progress
    settings = app_settings._load_settings()
    settings["last_checked_at"] = _now_iso()
    settings["update_last_error"] = ""
    _emit_download_log(effective_progress_callback, "正在检查最新版本信息")
    package_kind = detect_update_package_kind(repo_root)
    _emit_download_log(effective_progress_callback, f"当前安装类型: {_format_update_package_kind(package_kind)}")

    try:
        release = _fetch_latest_release()
        settings["last_available_version"] = _normalize_tag_name(release.get("tag_name"))
        settings["last_available_release_url"] = str(release.get("html_url") or "")
        settings["last_available_notes"] = str(release.get("body") or "")

        asset = _select_release_asset(release.get("assets", []), package_kind)
        checksum_asset = _select_release_checksum_asset(release.get("assets", []), str(asset.get("name") or ""))
        cache_root = _prepare_update_cache_dir(repo_root, progress_callback=effective_progress_callback)
        target_path = cache_root / asset["name"]
        checksum_path = cache_root / checksum_asset["name"]
        _emit_download_log(effective_progress_callback, f"找到更新包: {asset['name']}")
        _download_file(
            asset["browser_download_url"],
            target_path,
            progress_callback=effective_progress_callback,
        )
        _download_text_file(checksum_asset["browser_download_url"], checksum_path)
        expected_sha256 = _read_sha256_file(checksum_path, asset["name"])
        _verify_file_sha256(target_path, expected_sha256)
    except Exception as exc:
        settings["update_last_error"] = str(exc)
        app_settings._save_settings(settings)
        raise

    settings["pending_update_version"] = _normalize_tag_name(release["tag_name"])
    settings["pending_update_path"] = str(target_path)
    settings["pending_update_notes"] = str(release.get("body") or "")
    settings["pending_update_platform"] = _pending_update_platform(package_kind)
    settings["pending_update_package_kind"] = package_kind
    settings["pending_update_sha256"] = expected_sha256
    app_settings._save_settings(settings)
    _emit_download_log(effective_progress_callback, f"更新包已保存到: {target_path}")
    return get_update_status(repo_root)


def list_offline_update_packages(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd()).resolve()
    artifacts_dir = root / ".release-local" / "artifacts"
    items: list[dict[str, Any]] = []
    if artifacts_dir.exists():
        for path in sorted(artifacts_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or not (_is_zip_package(path) or _is_tar_gz_package(path)):
                continue
            size = path.stat().st_size
            version = ""
            package_kind = ""
            valid = True
            error = ""
            try:
                distribution = _read_package_distribution_from_package(path)
                package_kind = distribution.get("package_kind") or ""
                version = distribution.get("version") or ""
                _validate_package_distribution(root, distribution, package_name=path.name)
            except Exception as exc:
                valid = False
                error = str(exc)
            items.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": size,
                    "size_bytes": size,
                    "version": version,
                    "package_kind": package_kind,
                    "valid": valid,
                    "error": error,
                }
            )
    return {"artifacts_dir": str(artifacts_dir), "items": items}


def prepare_offline_update(
    repo_root: Path | None,
    package_path: Path | str,
    *,
    version: str = "",
    log_callback: Any | None = None,
) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd()).resolve()
    package = Path(package_path).expanduser()
    if not package.is_absolute():
        package = (root / package).resolve()
    _emit_apply_log(log_callback, f"正在校验离线更新包: {package.name}")
    if not package.exists():
        raise RuntimeError(f"更新包不存在: {package}")
    _validate_package_file(package)
    distribution = _read_package_distribution_from_package(package)
    _validate_package_distribution(root, distribution, package_name=package.name)
    package_kind = distribution.get("package_kind") or detect_update_package_kind(root)
    package_version = _normalize_tag_name(distribution.get("version"))
    settings = app_settings._load_settings()
    settings["pending_update_version"] = (
        _normalize_tag_name(version)
        or package_version
        or _normalize_tag_name(settings.get("last_available_version"))
        or "offline"
    )
    settings["pending_update_path"] = str(package)
    settings["pending_update_notes"] = "离线更新包"
    settings["pending_update_platform"] = (
        str(distribution.get("platform") or "").strip() or _pending_update_platform(package_kind)
    )
    settings["pending_update_package_kind"] = package_kind
    settings["pending_update_sha256"] = _file_sha256(package)
    settings["update_last_error"] = ""
    app_settings._save_settings(settings)
    _emit_apply_log(log_callback, "离线更新包已设置为待应用。关闭当前程序后重新运行 start.bat 生效。")
    return get_update_status(root)


def _print_download_progress(progress: dict[str, Any]) -> None:
    message = str(progress.get("message") or "").strip()
    if message:
        print(f"[更新] {message}", flush=True)


def _emit_apply_log(log_callback: Any | None, message: str) -> None:
    if log_callback is None:
        return
    log_callback(str(message))


def apply_pending_update(repo_root: Path, log_callback: Any | None = None) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    _recover_interrupted_update_applications(repo_root, log_callback=log_callback)
    settings = app_settings._load_settings()
    pending_path = str(settings.get("pending_update_path") or "").strip()
    pending_version = _normalize_tag_name(settings.get("pending_update_version"))
    current_version = _normalize_tag_name(APP_VERSION)
    if pending_version and pending_version == current_version:
        _clear_pending_update(settings)
        settings["update_last_error"] = ""
        app_settings._save_settings(settings)
        _emit_apply_log(log_callback, f"当前版本已是 {current_version}，跳过待更新包。")
        return {
            "applied": False,
            "skipped": True,
            "reason": "already_current_version",
            "version": current_version,
        }
    if not pending_path:
        _emit_apply_log(log_callback, "没有待应用的更新。")
        return {"applied": False, "reason": "no_pending_update"}
    if pending_version:
        _emit_apply_log(log_callback, f"开始应用待更新版本: {pending_version}")
    else:
        _emit_apply_log(log_callback, "开始应用待更新版本。")

    package_path = Path(pending_path)
    if not package_path.is_absolute():
        package_path = (repo_root / package_path).resolve()
    if not package_path.exists():
        settings["update_last_error"] = f"更新包不存在: {package_path}"
        app_settings._save_settings(settings)
        _emit_apply_log(log_callback, settings["update_last_error"])
        return {"applied": False, "reason": "missing_package", "path": str(package_path)}
    expected_sha256 = str(settings.get("pending_update_sha256") or "").strip()
    if expected_sha256:
        try:
            _verify_file_sha256(package_path, expected_sha256)
        except Exception as exc:
            settings["update_last_error"] = str(exc)
            app_settings._save_settings(settings)
            _emit_apply_log(log_callback, settings["update_last_error"])
            return {
                "applied": False,
                "reason": "checksum_mismatch",
                "package_path": str(package_path),
                "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
            }

    try:
        distribution = _read_package_distribution_from_package(package_path)
        _validate_package_distribution(repo_root, distribution, package_name=package_path.name)
    except Exception as exc:
        settings["update_last_error"] = str(exc)
        _clear_pending_update(settings)
        app_settings._save_settings(settings)
        _emit_apply_log(log_callback, settings["update_last_error"])
        return {
            "applied": False,
            "reason": "invalid_package",
            "package_path": str(package_path),
            "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
        }

    try:
        package_entry_paths = _list_package_entry_paths(package_path)
    except _PackageStreamError as exc:
        settings["update_last_error"] = str(exc)
        _clear_pending_update(settings)
        app_settings._save_settings(settings)
        _emit_apply_log(log_callback, settings["update_last_error"])
        return {
            "applied": False,
            "reason": "invalid_package",
            "package_path": str(package_path),
            "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
        }

    try:
        write_plan = _build_update_write_plan(repo_root, package_entry_paths)
    except RuntimeError as exc:
        settings["update_last_error"] = str(exc)
        _clear_pending_update(settings)
        app_settings._save_settings(settings)
        _emit_apply_log(log_callback, settings["update_last_error"])
        return {
            "applied": False,
            "reason": "invalid_package",
            "package_path": str(package_path),
            "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
        }

    write_targets = {relative_path: target_path for target_path, relative_path in write_plan}
    _preserve_legacy_announcement_reads(
        repo_root,
        [relative_path for _target_path, relative_path in write_plan],
        log_callback=log_callback,
    )
    needs_frontend_build = _needs_frontend_build(
        repo_root,
        [relative_path for _target_path, relative_path in write_plan],
    )
    extracted_files = 0
    frontend_built = False
    try:
        with tempfile.TemporaryDirectory(prefix=".update-apply-", dir=repo_root) as temp_root_str:
            temp_root = Path(temp_root_str)
            journal_path = temp_root / "journal.jsonl"
            backups = _backup_update_targets(write_plan, temp_root=temp_root, journal_path=journal_path)

            try:
                def _write_entry(relative_path: str, stream) -> None:
                    nonlocal extracted_files
                    if _is_protected_update_path(relative_path):
                        return
                    target_path = write_targets.get(relative_path)
                    if target_path is None:
                        raise _PackageStreamError(_format_invalid_package_message(package_path, f"非法归档路径: {relative_path}"))
                    _emit_apply_log(log_callback, f"正在更新: {relative_path}")
                    _replace_target_from_stream(
                        target_path,
                        stream,
                        journal_path=journal_path,
                        backup_record=backups[target_path],
                    )
                    extracted_files += 1

                _stream_package_entries(package_path, _write_entry)
            except _PackageStreamError as exc:
                _restore_update_targets(backups)
                settings["update_last_error"] = str(exc)
                _clear_pending_update(settings)
                app_settings._save_settings(settings)
                _emit_apply_log(log_callback, settings["update_last_error"])
                return {
                    "applied": False,
                    "reason": "invalid_package",
                    "package_path": str(package_path),
                    "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
                }
            except Exception:
                _restore_update_targets(backups)
                raise

            if needs_frontend_build:
                _emit_apply_log(log_callback, "正在重建前端资源...")
                build_success, build_output = _build_updated_frontend(repo_root)
                if not build_success:
                    _restore_update_targets(backups)
                    settings["update_last_error"] = build_output
                    app_settings._save_settings(settings)
                    if build_output:
                        for line in str(build_output).splitlines():
                            if line.strip():
                                _emit_apply_log(log_callback, line)
                    return {
                        "applied": False,
                        "reason": "frontend_build_failed",
                        "frontend_built": False,
                        "files_written": extracted_files,
                        "package_path": str(package_path),
                        "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
                    }
                frontend_built = True
                if build_output:
                    for line in str(build_output).splitlines():
                        if line.strip():
                            _emit_apply_log(log_callback, line)
                _emit_apply_log(log_callback, "前端资源重建完成。")
            else:
                _emit_apply_log(log_callback, "未检测到前端改动，跳过前端重建。")
            _sync_runtime_announcements_from_package(
                package_path,
                [relative_path for _target_path, relative_path in write_plan],
                log_callback=log_callback,
            )
    except Exception:
        raise

    _clear_pending_update(settings)
    settings["update_last_error"] = ""
    app_settings._save_settings(settings)
    _emit_apply_log(log_callback, "更新应用完成。")
    return {
        "applied": True,
        "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
        "frontend_built": frontend_built,
        "files_written": extracted_files,
        "package_path": str(package_path),
    }


def _fetch_latest_release() -> dict[str, Any]:
    repository = str(APP_UPDATE_REPOSITORY or "").strip()
    if not repository:
        raise RuntimeError("未配置 APP_UPDATE_REPOSITORY")

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"cli-bridge/{APP_VERSION}",
        },
    )
    opener = _build_url_opener()
    with opener.open(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _select_release_asset(assets: list[dict[str, Any]], package_kind: str | None = None) -> dict[str, Any]:
    normalized_kind = _normalize_update_package_kind(package_kind) or detect_update_package_kind()
    if normalized_kind == LINUX_PACKAGE_KIND:
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if "linux" in name and name.endswith(".tar.gz"):
                return asset
        raise RuntimeError("未找到 Linux release 包")

    if normalized_kind == MACOS_PACKAGE_KIND:
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if "macos" in name and name.endswith(".tar.gz"):
                return asset
        raise RuntimeError("未找到 macOS release 包")

    if normalized_kind in {WINDOWS_INSTALLER_PACKAGE_KIND, WINDOWS_PORTABLE_PACKAGE_KIND}:
        want_installer = normalized_kind == WINDOWS_INSTALLER_PACKAGE_KIND
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if "windows-x64" not in name or not name.endswith(".zip"):
                continue
            is_installer = "installer" in name
            if is_installer == want_installer:
                return asset
        label = "安装版" if want_installer else "绿色版"
        raise RuntimeError(f"未找到 Windows {label} release 包")

    raise RuntimeError("未找到当前平台的 release 包")


def _select_release_checksum_asset(assets: list[dict[str, Any]], package_name: str) -> dict[str, Any]:
    expected_name = f"{str(package_name or '').strip()}.sha256".lower()
    for asset in assets:
        if str(asset.get("name") or "").strip().lower() == expected_name:
            return asset
    raise RuntimeError(f"未找到更新包校验文件: {expected_name}")


def _download_text_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/plain",
            "User-Agent": f"cli-bridge/{APP_VERSION}",
        },
    )
    opener = _build_url_opener()
    with opener.open(request, timeout=30) as response:
        target.write_bytes(response.read())


def _read_sha256_file(path: Path, package_name: str) -> str:
    text = path.read_text(encoding="utf-8").strip()
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        digest = parts[0].lower()
        if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            return digest
    raise RuntimeError(f"更新包校验文件无效: {package_name}.sha256")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file_sha256(path: Path, expected_sha256: str) -> None:
    actual = _file_sha256(path)
    if actual.lower() != str(expected_sha256 or "").strip().lower():
        raise RuntimeError("更新包 SHA256 校验失败")


def _pending_update_platform(package_kind: str) -> str:
    if package_kind == WINDOWS_INSTALLER_PACKAGE_KIND:
        return "windows-x64-installer"
    if package_kind == WINDOWS_PORTABLE_PACKAGE_KIND:
        return "windows-x64-portable"
    if package_kind == LINUX_PACKAGE_KIND:
        return "linux-x64"
    if package_kind == MACOS_PACKAGE_KIND:
        return "macos-universal"
    return UNKNOWN_PACKAGE_KIND


def _format_update_package_kind(package_kind: str) -> str:
    if package_kind == WINDOWS_INSTALLER_PACKAGE_KIND:
        return "Windows 安装版"
    if package_kind == WINDOWS_PORTABLE_PACKAGE_KIND:
        return "Windows 绿色版"
    if package_kind == LINUX_PACKAGE_KIND:
        return "Linux"
    if package_kind == MACOS_PACKAGE_KIND:
        return "macOS"
    return "未知"


def _prepare_update_cache_dir(
    repo_root: Path | None = None,
    *,
    progress_callback: Any | None = None,
) -> Path:
    root = Path(repo_root or Path.cwd()).resolve()
    cache_root = root / UPDATE_CACHE_DIR_NAME
    try:
        _ensure_writable_directory(cache_root)
        return cache_root
    except OSError as exc:
        backup_path = _reset_blocked_cache_dir(cache_root, exc, progress_callback=progress_callback)
        if backup_path is not None:
            try:
                _ensure_writable_directory(cache_root)
                return cache_root
            except OSError as retry_exc:
                _emit_download_log(progress_callback, f"仓库内更新缓存目录重建失败: {retry_exc}")
        fallback_root = _fallback_update_cache_dir(root)
        _emit_download_log(progress_callback, f"仓库内更新缓存目录不可用，改用备用目录: {fallback_root}")
        _ensure_writable_directory(fallback_root)
        return fallback_root


def _ensure_writable_directory(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(f"更新缓存路径不是目录: {path}")
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, prefix=".write-test-", delete=True) as handle:
        handle.write(b"")
        handle.flush()


def _reset_blocked_cache_dir(
    cache_root: Path,
    error: OSError,
    *,
    progress_callback: Any | None = None,
) -> Path | None:
    if not cache_root.exists():
        return None
    backup_path = _unique_update_cache_backup_path(cache_root)
    try:
        cache_root.rename(backup_path)
    except OSError as rename_exc:
        _emit_download_log(
            progress_callback,
            f"更新缓存目录不可用且无法迁移: {cache_root} ({error}); {rename_exc}",
        )
        return None
    _emit_download_log(progress_callback, f"更新缓存目录不可用，已迁移旧目录到: {backup_path}")
    return backup_path


def _unique_update_cache_backup_path(cache_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for index in range(1000):
        suffix = f".blocked-{timestamp}" if index == 0 else f".blocked-{timestamp}-{index}"
        candidate = cache_root.with_name(f"{cache_root.name}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为更新缓存目录生成备份路径: {cache_root}")


def _fallback_update_cache_dir(repo_root: Path) -> Path:
    repo_hash = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:12]
    return _default_user_cache_root() / "cli-bridge" / "updates" / f"{repo_root.name}-{repo_hash}"


def _default_user_cache_root() -> Path:
    if _is_windows_runtime():
        local_appdata = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local_appdata:
            return Path(local_appdata).expanduser()
    xdg_cache_home = str(os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg_cache_home:
        return Path(xdg_cache_home).expanduser()
    return Path.home() / ".cache"


def _download_file(
    url: str,
    target: Path,
    progress_callback: Any | None = None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(target.suffix + ".tmp")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"cli-bridge/{APP_VERSION}",
        },
    )
    if temp_path.exists():
        temp_path.unlink()
    opener = _build_url_opener()
    with opener.open(request, timeout=60) as response:
        total_bytes = _parse_content_length(response.headers.get("Content-Length"))
        _emit_download_log(progress_callback, f"开始下载更新包: {target.name}", total_bytes=total_bytes)
        _emit_download_progress(
            progress_callback,
            phase="starting",
            downloaded_bytes=0,
            total_bytes=total_bytes,
        )
        downloaded_bytes = 0
        last_logged_percent = -10
        with temp_path.open("wb") as handle:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded_bytes += len(chunk)
                _emit_download_progress(
                    progress_callback,
                    phase="downloading",
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                )
                percent = _calculate_progress_percent(downloaded_bytes, total_bytes)
                if total_bytes and percent >= last_logged_percent + 10:
                    _emit_download_log(
                        progress_callback,
                        f"已下载 {downloaded_bytes} / {total_bytes} bytes ({percent}%)",
                        downloaded_bytes=downloaded_bytes,
                        total_bytes=total_bytes,
                    )
                    last_logged_percent = percent
    if total_bytes is not None and downloaded_bytes != total_bytes:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"更新包下载不完整: 期望 {total_bytes} bytes，实际 {downloaded_bytes} bytes")

    try:
        _validate_package_file(temp_path, package_name=target.name)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    temp_path.replace(target)
    final_size = target.stat().st_size if target.exists() else 0
    _emit_download_log(
        progress_callback,
        f"下载完成: {target.name} ({final_size} bytes)",
        downloaded_bytes=final_size,
        total_bytes=final_size or None,
    )


def _parse_content_length(raw_value: Any) -> int | None:
    try:
        length = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return None
    return length if length >= 0 else None


def _calculate_progress_percent(downloaded_bytes: int, total_bytes: int | None) -> int:
    if total_bytes and total_bytes > 0:
        return min(100, int(downloaded_bytes * 100 / total_bytes))
    return 0


def _emit_download_progress(
    progress_callback: Any | None,
    *,
    phase: str,
    downloaded_bytes: int,
    total_bytes: int | None,
) -> None:
    if progress_callback is None:
        return
    percent = _calculate_progress_percent(downloaded_bytes, total_bytes)
    progress_callback(
        {
            "phase": phase,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
            "percent": percent,
        }
    )


def _emit_download_log(
    progress_callback: Any | None,
    message: str,
    *,
    downloaded_bytes: int = 0,
    total_bytes: int | None = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "phase": "log",
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
            "percent": _calculate_progress_percent(downloaded_bytes, total_bytes),
            "message": message,
        }
    )


def _build_updated_frontend(repo_root: Path) -> tuple[bool, str]:
    if not (repo_root / "front").exists():
        return True, "未检测到前端目录，跳过构建"

    script_name = "build_web_frontend.bat" if os.name == "nt" else "build_web_frontend.sh"
    script_path = (repo_root / "scripts" / script_name).resolve()
    if not script_path.exists():
        return False, f"未找到前端构建脚本: {script_path}"

    command = [str(script_path)] if os.name == "nt" else ["bash", str(script_path)]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        return False, f"执行前端构建失败: {exc}"

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip()).strip()
    if result.returncode != 0:
        return False, output or f"前端构建失败，退出码 {result.returncode}"
    return True, output or "Web 前端构建完成"


def _iter_package_entries(package_path: Path) -> list[tuple[str, bytes]]:
    if _is_zip_package(package_path):
        if not zipfile.is_zipfile(package_path):
            raise RuntimeError(_format_invalid_package_message(package_path))
        return _iter_zip_entries(package_path)
    if _is_tar_gz_package(package_path):
        try:
            return _iter_tar_entries(package_path)
        except (OSError, tarfile.TarError) as exc:
            raise RuntimeError(_format_invalid_package_message(package_path, exc)) from exc
    raise RuntimeError(f"不支持的更新包格式: {package_path.name}")


def _list_package_entry_paths(package_path: Path) -> list[str]:
    entries: list[str] = []

    def _append(relative_path: str, _stream) -> None:
        entries.append(relative_path)

    _stream_package_entries(package_path, _append, open_files=False)
    return entries


def _read_package_distribution_from_package(package_path: Path) -> dict[str, str]:
    raw_bytes = _read_distribution_marker_from_package(package_path)
    return _read_package_distribution_from_bytes(raw_bytes, package_name=package_path.name)


def _read_distribution_marker_from_package(package_path: Path) -> bytes:
    marker_bytes: bytes | None = None

    def _capture_marker(relative_path: str, stream) -> None:
        nonlocal marker_bytes
        if relative_path != DISTRIBUTION_MARKER_FILE or marker_bytes is not None or stream is None:
            return
        marker_bytes = stream.read()

    try:
        _stream_package_entries(package_path, _capture_marker)
    except _PackageStreamError as exc:
        raise RuntimeError(str(exc)) from exc

    if marker_bytes is None:
        raise RuntimeError(f"更新包缺少分发标记: {package_path.name}")
    return marker_bytes


def _read_package_distribution_from_entries(
    package_entries: list[tuple[str, bytes]],
    *,
    package_name: str,
) -> dict[str, str]:
    raw_bytes = next((data for relative_path, data in package_entries if relative_path == DISTRIBUTION_MARKER_FILE), None)
    if raw_bytes is None:
        raise RuntimeError(f"更新包缺少分发标记: {package_name}")
    return _read_package_distribution_from_bytes(raw_bytes, package_name=package_name)


def _read_package_distribution_from_bytes(raw_bytes: bytes, *, package_name: str) -> dict[str, str]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"更新包分发标记无效: {package_name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"更新包分发标记无效: {package_name}")
    return {
        "package_kind": _normalize_update_package_kind(payload.get("packageKind") or payload.get("package_kind")),
        "platform": str(payload.get("platform") or "").strip(),
        "version": _normalize_tag_name(payload.get("version")),
    }


def _expected_distribution_platform(package_kind: str) -> str:
    if package_kind in {WINDOWS_INSTALLER_PACKAGE_KIND, WINDOWS_PORTABLE_PACKAGE_KIND}:
        return "windows-x64"
    if package_kind == LINUX_PACKAGE_KIND:
        return "linux-x64"
    if package_kind == MACOS_PACKAGE_KIND:
        return "macos-universal"
    return ""


def _validate_package_distribution(
    repo_root: Path,
    distribution: dict[str, str],
    *,
    package_name: str,
) -> None:
    package_kind = _normalize_update_package_kind(distribution.get("package_kind"))
    if not package_kind:
        raise RuntimeError(f"更新包缺少有效包类型: {package_name}")
    expected_kind = detect_update_package_kind(repo_root)
    if expected_kind and package_kind != expected_kind:
        raise RuntimeError(
            f"更新包类型不匹配: 当前安装为 {_format_update_package_kind(expected_kind)}，更新包为 {_format_update_package_kind(package_kind)}"
        )
    platform = str(distribution.get("platform") or "").strip()
    expected_platform = _expected_distribution_platform(package_kind)
    if expected_platform and platform and platform != expected_platform:
        raise RuntimeError(
            f"更新包平台不匹配: 期望 {expected_platform}，实际 {platform}"
        )


def _build_update_write_plan(
    repo_root: Path,
    package_entries: list[str],
) -> list[tuple[Path, str]]:
    plan: list[tuple[Path, str]] = []
    for relative_path in package_entries:
        target_path = _resolve_update_target_path(repo_root, relative_path)
        if _is_protected_update_path(relative_path):
            continue
        plan.append((target_path, relative_path))
    return plan


def _resolve_update_target_path(repo_root: Path, relative_path: str) -> Path:
    root = Path(repo_root).resolve()
    try:
        normalized_path = _normalize_archive_path(relative_path)
    except ValueError as exc:
        raise RuntimeError(f"更新包包含非法路径: {relative_path}") from exc
    if not normalized_path:
        raise RuntimeError(f"更新包包含非法路径: {relative_path}")
    target_path = (root / normalized_path).resolve(strict=False)
    try:
        target_path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"更新包包含非法路径: {relative_path}") from exc
    return target_path


def _preserve_legacy_announcement_reads(
    repo_root: Path,
    relative_paths: list[str],
    *,
    log_callback: Any | None = None,
) -> None:
    normalized_paths = {str(path or "").replace("\\", "/").strip("/") for path in relative_paths}
    if ANNOUNCEMENTS_FILE not in normalized_paths:
        return

    content_path = repo_root / ANNOUNCEMENTS_FILE
    reads_path = repo_root / ANNOUNCEMENT_READS_FILE
    if reads_path.exists() or not content_path.exists():
        return

    try:
        data = json.loads(content_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    reads = data.get("reads")
    if not isinstance(reads, dict) or not reads:
        return

    payload = {
        "version": 1,
        "updated_at": str(data.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        "reads": reads,
    }
    reads_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _emit_apply_log(log_callback, "已迁移公告已读状态到本地 sidecar。")


def _load_announcement_content_from_bytes(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"version": 1, "updated_at": _now_iso(), "items": []}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": _now_iso(), "items": []}
    items = data.get("items")
    return {
        "version": data.get("version", 1),
        "updated_at": str(data.get("updated_at") or _now_iso()),
        "items": items if isinstance(items, list) else [],
    }


def _merge_announcement_content(target: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    merged_items: list[Any] = []
    seen_ids: set[str] = set()
    for item in target.get("items", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        merged_items.append(item)
        seen_ids.add(item_id)

    changed = False
    for item in source.get("items", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen_ids:
            continue
        merged_items.append(item)
        seen_ids.add(item_id)
        changed = True

    if not changed:
        return target, False

    return {
        "version": target.get("version", source.get("version", 1)),
        "updated_at": str(source.get("updated_at") or _now_iso()),
        "items": merged_items,
    }, True


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sync_runtime_announcements_from_package(
    package_path: Path,
    relative_paths: list[str],
    *,
    log_callback: Any | None = None,
) -> bool:
    normalized_paths = {str(path or "").replace("\\", "/").strip("/") for path in relative_paths}
    if ANNOUNCEMENTS_FILE not in normalized_paths:
        return False

    package_content: dict[str, Any] | None = None

    def _capture(relative_path: str, stream) -> None:
        nonlocal package_content
        if relative_path != ANNOUNCEMENTS_FILE or stream is None:
            return
        package_content = _load_announcement_content_from_bytes(stream.read())

    _stream_package_entries(package_path, _capture)
    if package_content is None:
        return False

    target_path = get_announcements_content_path()
    if target_path.exists():
        try:
            target_content = _load_announcement_content_from_bytes(target_path.read_bytes())
        except OSError:
            target_content = {"version": 1, "updated_at": _now_iso(), "items": []}
    else:
        target_content = {"version": 1, "updated_at": _now_iso(), "items": []}

    merged, changed = _merge_announcement_content(target_content, package_content)
    if not changed:
        return False

    _write_json_file(target_path, merged)
    _emit_apply_log(log_callback, "已同步发布公告到本地公告中心。")
    return True


def _backup_update_targets(
    write_plan: list[tuple[Path, str]],
    *,
    temp_root: Path,
    journal_path: Path,
) -> dict[Path, dict[str, str]]:
    backups: dict[Path, dict[str, str]] = {}
    for index, (target_path, relative_path) in enumerate(write_plan):
        if target_path in backups:
            continue
        backup_path = ""
        if target_path.exists():
            if not target_path.is_file():
                raise IsADirectoryError(str(target_path))
            backup_file = temp_root / f"backup-{index:04d}"
            target_path.replace(backup_file)
            backup_path = str(backup_file)
        record = {
            "target_path": str(target_path),
            "relative_path": relative_path,
            "backup_path": backup_path,
            "write_path": "",
        }
        backups[target_path] = record
        _append_update_journal(journal_path, {"event": "backup", **record})
    return backups


def _restore_update_targets(backups: dict[Path, dict[str, str]]) -> None:
    for target_path, record in backups.items():
        write_path = str(record.get("write_path") or "").strip()
        if write_path:
            temp_output = Path(write_path)
            if temp_output.exists():
                temp_output.unlink()
        backup_path = str(record.get("backup_path") or "").strip()
        if not backup_path:
            if target_path.exists():
                target_path.unlink()
            continue
        if target_path.exists():
            target_path.unlink()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        Path(backup_path).replace(target_path)


def _recover_interrupted_update_applications(repo_root: Path, log_callback: Any | None = None) -> None:
    for temp_root in repo_root.glob(".update-apply-*"):
        if not temp_root.is_dir():
            continue
        journal_path = temp_root / "journal.jsonl"
        if not journal_path.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
            continue
        backups = _read_update_journal(journal_path)
        if backups:
            _emit_apply_log(log_callback, f"检测到未完成的更新应用，正在回滚: {temp_root.name}")
            _restore_update_targets(backups)
        shutil.rmtree(temp_root, ignore_errors=True)


def _read_update_journal(journal_path: Path) -> dict[Path, dict[str, str]]:
    backups: dict[Path, dict[str, str]] = {}
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return backups

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        target_text = str(record.get("target_path") or "").strip()
        if not target_text:
            continue
        target_path = Path(target_text)
        current = backups.setdefault(
            target_path,
            {
                "target_path": target_text,
                "relative_path": str(record.get("relative_path") or ""),
                "backup_path": "",
                "write_path": "",
            },
        )
        backup_path = str(record.get("backup_path") or "").strip()
        write_path = str(record.get("write_path") or "").strip()
        if backup_path:
            current["backup_path"] = backup_path
        if write_path:
            current["write_path"] = write_path
        relative_path = str(record.get("relative_path") or "").strip()
        if relative_path:
            current["relative_path"] = relative_path
    return backups


def _replace_target_from_stream(
    target_path: Path,
    stream,
    *,
    journal_path: Path,
    backup_record: dict[str, str],
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target_path.name}.update-",
        suffix=".tmp",
        dir=target_path.parent,
        delete=False,
    ) as handle:
        temp_output = Path(handle.name)
        backup_record["write_path"] = str(temp_output)
        _append_update_journal(
            journal_path,
            {
                "event": "stage",
                "target_path": str(target_path),
                "relative_path": backup_record.get("relative_path") or "",
                "backup_path": backup_record.get("backup_path") or "",
                "write_path": str(temp_output),
            },
        )
        try:
            while True:
                chunk = stream.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            if temp_output.exists():
                temp_output.unlink()
            raise
    temp_output.replace(target_path)


def _iter_zip_entries(package_path: Path) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(package_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            relative_path = _normalize_archive_path_for_package(package_path, member.filename)
            if not relative_path:
                continue
            entries.append((relative_path, archive.read(member)))
    return entries


def _iter_tar_entries(package_path: Path) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    with tarfile.open(package_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            relative_path = _normalize_archive_path_for_package(package_path, member.name)
            if not relative_path:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            entries.append((relative_path, extracted.read()))
    return entries


def _stream_package_entries(
    package_path: Path,
    consumer: Any,
    *,
    open_files: bool = True,
) -> None:
    if _is_zip_package(package_path):
        if not zipfile.is_zipfile(package_path):
            raise _PackageStreamError(_format_invalid_package_message(package_path))
        try:
            with zipfile.ZipFile(package_path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    relative_path = _normalize_archive_path_for_stream(package_path, member.filename)
                    if not relative_path:
                        continue
                    if not open_files:
                        consumer(relative_path, None)
                        continue
                    with archive.open(member, "r") as extracted:
                        consumer(relative_path, extracted)
            return
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise _PackageStreamError(_format_invalid_package_message(package_path, exc)) from exc

    if _is_tar_gz_package(package_path):
        try:
            with tarfile.open(package_path, "r:gz") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    relative_path = _normalize_archive_path_for_stream(package_path, member.name)
                    if not relative_path:
                        continue
                    if not open_files:
                        consumer(relative_path, None)
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    with extracted:
                        consumer(relative_path, extracted)
            return
        except (OSError, tarfile.TarError) as exc:
            raise _PackageStreamError(_format_invalid_package_message(package_path, exc)) from exc

    raise _PackageStreamError(f"不支持的更新包格式: {package_path.name}")


def _validate_package_file(package_path: Path, package_name: str | None = None) -> None:
    effective_name = str(package_name or package_path.name)
    if _is_zip_package_name(effective_name):
        if not zipfile.is_zipfile(package_path):
            raise RuntimeError(_format_invalid_package_message(package_path, package_name=effective_name))
        try:
            with zipfile.ZipFile(package_path) as archive:
                bad_member = archive.testzip()
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise RuntimeError(_format_invalid_package_message(package_path, exc, package_name=effective_name)) from exc
        if bad_member is not None:
            raise RuntimeError(
                _format_invalid_package_message(package_path, f"CRC 校验失败: {bad_member}", package_name=effective_name)
            )
        return

    if _is_tar_gz_package_name(effective_name):
        try:
            with tarfile.open(package_path, "r:gz") as archive:
                for _member in archive:
                    pass
        except (OSError, tarfile.TarError) as exc:
            raise RuntimeError(_format_invalid_package_message(package_path, exc, package_name=effective_name)) from exc
        return

    raise RuntimeError(f"不支持的更新包格式: {effective_name}")


def _is_zip_package(package_path: Path) -> bool:
    return _is_zip_package_name(package_path.name)


def _is_tar_gz_package(package_path: Path) -> bool:
    return _is_tar_gz_package_name(package_path.name)


def _is_zip_package_name(package_name: str) -> bool:
    return str(package_name or "").lower().endswith(".zip")


def _is_tar_gz_package_name(package_name: str) -> bool:
    return str(package_name or "").lower().endswith(".tar.gz")


def _format_invalid_package_message(
    package_path: Path,
    detail: Any | None = None,
    *,
    package_name: str | None = None,
) -> str:
    display_name = str(package_name or package_path.name)
    message = f"更新包已损坏，请重新下载: {display_name}"
    detail_text = str(detail or "").strip()
    if detail_text:
        return f"{message} ({detail_text})"
    return message


def _normalize_archive_path(raw_path: str) -> str:
    raw_value = str(raw_path or "")
    if not raw_value:
        return ""
    if raw_value.startswith(("/", "\\")):
        raise ValueError(f"非法归档路径: {raw_value}")
    parts: list[str] = []
    for part in raw_value.replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        if part == ".." or ":" in part:
            raise ValueError(f"非法归档路径: {raw_value}")
        parts.append(part)
    return "/".join(parts)


def _normalize_archive_path_for_package(package_path: Path, raw_path: str) -> str:
    try:
        return _normalize_archive_path(raw_path)
    except ValueError as exc:
        raise RuntimeError(
            _format_invalid_package_message(package_path, f"非法归档路径: {raw_path}")
        ) from exc


def _normalize_archive_path_for_stream(package_path: Path, raw_path: str) -> str:
    try:
        return _normalize_archive_path(raw_path)
    except ValueError as exc:
        raise _PackageStreamError(
            _format_invalid_package_message(package_path, f"非法归档路径: {raw_path}")
        ) from exc


def _is_protected_update_path(relative_path: str) -> bool:
    root_name = relative_path.split("/", 1)[0]
    return relative_path in PROTECTED_UPDATE_PATHS or root_name in PROTECTED_UPDATE_PATHS


def _needs_frontend_build(repo_root: Path, relative_paths: list[str]) -> bool:
    normalized = [str(path or "").replace("\\", "/").strip("/") for path in relative_paths]
    if any(path.startswith("front/") for path in normalized):
        return True
    if any(path in FRONTEND_BUILD_TRIGGER_PATHS for path in normalized):
        return True
    front_root = repo_root / "front"
    return front_root.exists() and not (front_root / "dist").exists()


def _append_update_journal(journal_path: Path, record: dict[str, Any]) -> None:
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")


def _clear_pending_update(settings: dict[str, Any]) -> None:
    settings["pending_update_version"] = ""
    settings["pending_update_path"] = ""
    settings["pending_update_notes"] = ""
    settings["pending_update_platform"] = ""
    settings["pending_update_package_kind"] = ""
    settings["pending_update_sha256"] = ""


def _normalize_tag_name(tag_name: Any) -> str:
    value = str(tag_name or "").strip()
    if value.lower().startswith("v"):
        return value[1:]
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    apply_parser = subcommands.add_parser("apply-pending")
    apply_parser.add_argument("--repo-root", default=os.getcwd())
    args = parser.parse_args(argv)

    if args.command == "apply-pending":
        result = apply_pending_update(Path(args.repo_root).resolve(), log_callback=print)
        return 0 if result.get("applied") or result.get("reason") in {"no_pending_update", "already_current_version"} else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
