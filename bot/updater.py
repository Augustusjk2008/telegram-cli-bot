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
import time
import re
import urllib.error
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
    from bot.update_service import get_update_service
    return get_update_service(repo_root).status()

def set_update_enabled(enabled: bool, repo_root: Path | None = None) -> dict[str, Any]:
    from bot.update_service import get_update_service
    return get_update_service(repo_root).set_enabled(enabled)

def check_for_updates(repo_root: Path | None = None) -> dict[str, Any]:
    from bot.update_service import get_update_service
    return get_update_service(repo_root).check()

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


def download_latest_update(repo_root: Path | None = None, progress_callback: Any | None = None) -> dict[str, Any]:
    from bot.update_service import get_update_service
    return get_update_service(repo_root).start_online()


def _download_release_package(repo_root: Path, job_dir: Path, release: dict,
                              progress_callback=None) -> Path:
    """Download only assets belonging to the already selected release."""
    from scripts.update_package import normalize_path, normalize_version
    normalize_version(release.get("tag_name"))
    kind = detect_update_package_kind(repo_root)
    asset = _select_release_asset(release.get("assets", []), kind)
    checksum = _select_release_checksum_asset(release.get("assets", []), asset.get("name", ""))
    for item in (asset, checksum):
        name = normalize_path(str(item.get("name") or ""))
        if not name or "/" in name:
            raise RuntimeError("Release 资产文件名无效")
    target = Path(job_dir) / asset["name"]
    checksum_path = Path(job_dir) / checksum["name"]
    _download_text_file(checksum["browser_download_url"], checksum_path)
    expected = _read_sha256_file(checksum_path, asset["name"])
    _download_file(asset["browser_download_url"], target, progress_callback)
    _verify_file_sha256(target, expected)
    return target


def prepare_update_payload(repo_root: Path, package_path: Path, job_dir: Path, *,
                           expected_version="", progress_callback=None) -> dict[str, Any]:
    from scripts.update_package import inspect_package, ownership_plan, normalize_version
    from bot.runtime_paths import get_app_data_root, get_tcb_home_root
    root, package = Path(repo_root).resolve(), Path(package_path).resolve()
    _assert_no_unfinished_legacy_transactions(root)
    if not package.is_file():
        raise RuntimeError(f"更新包不存在: {package}")
    version_file = root / "VERSION"
    current = normalize_version(version_file.read_text(encoding="utf-8-sig") if version_file.exists() else APP_VERSION)
    staging = Path(job_dir).resolve() / "staging"
    kind = detect_update_package_kind(root)
    digest = _file_sha256(package)
    if package.parent != Path(job_dir).resolve():
        from scripts.update_transaction import durable_copy
        suffix = ".zip" if _is_zip_package(package) else ".tar.gz" if _is_tar_gz_package(package) else ""
        if not suffix:
            raise RuntimeError("更新包只支持 .zip 或 .tar.gz")
        frozen_package = Path(job_dir).resolve() / ("package" + suffix)
        frozen_package.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(frozen_package.parent).free < package.stat().st_size + 64 * 1024**2:
            raise RuntimeError("离线包缓存空间不足")
        durable_copy(package, frozen_package)
        if _file_sha256(frozen_package) != digest:
            raise RuntimeError("复制期间离线更新包发生变化，请重新选择")
        package = frozen_package
    manifest = inspect_package(package, staging_dir=staging, expected_version=expected_version,
                               current_version=current, expected_kind=kind,
                               expected_platform=_expected_distribution_platform(kind),
                               progress_callback=progress_callback)
    if _file_sha256(package) != digest:
        raise RuntimeError("校验期间更新包发生变化，请重新选择")
    files, deleted = ownership_plan(root, manifest)
    for runtime_root in (get_app_data_root(), get_tcb_home_root()):
        runtime_root = Path(runtime_root).resolve()
        if runtime_root.is_relative_to(root):
            for relative in [*files, *deleted]:
                if (root / relative).resolve().is_relative_to(runtime_root):
                    raise RuntimeError(f"程序文件清单覆盖当前存储位置: {relative}")
    backup_size = sum((root / name).stat().st_size for name in [*files, *deleted] if (root / name).is_file())
    if shutil.disk_usage(job_dir).free < backup_size + 64 * 1024**2:
        raise RuntimeError("更新恢复备份空间不足")
    return {"current_version": current, "target_version": manifest["version"], "package_kind": kind,
            "package_sha256": digest, "package_path": str(package), "staging_dir": str(staging),
            "files": files, "delete_paths": deleted, "manifest": manifest,
            "original_hashes": {name: _file_sha256(root / name) if (root / name).is_file() else None
                                for name in [*files, *deleted]}}

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
                from scripts.update_package import inspect_package
                distribution = inspect_package(path, current_version=APP_VERSION,
                                               expected_kind=detect_update_package_kind(root),
                                               expected_platform=_expected_distribution_platform(detect_update_package_kind(root)))
                package_kind = distribution.get("package_kind") or ""
                version = distribution.get("version") or ""
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


def prepare_offline_update(repo_root: Path | None, package_path: Path | str, *, version: str = "",
                           log_callback: Any | None = None) -> dict[str, Any]:
    from bot.update_service import get_update_service
    root = Path(repo_root or Path.cwd()).resolve()
    package = Path(package_path).expanduser()
    if not package.is_absolute():
        package = root / package
    return get_update_service(root).start_offline(package, version)

def _print_download_progress(progress: dict[str, Any]) -> None:
    message = str(progress.get("message") or "").strip()
    if message:
        print(f"[更新] {message}", flush=True)


def _emit_apply_log(log_callback: Any | None, message: str) -> None:
    if log_callback is None:
        return
    log_callback(str(message))


def apply_pending_update(repo_root: Path, log_callback: Any | None = None) -> dict[str, Any]:
    """Compatibility command: recover interrupted legacy writes, never consume a ready package."""
    try:
        _recover_interrupted_update_applications(Path(repo_root).resolve(), log_callback=log_callback)
    except Exception as exc:
        return {"applied": False, "reason": "recovery_required", "error": str(exc)}
    status = get_update_status(repo_root)
    if status.get("job"):
        return {"applied": False, "reason": "explicit_application_required", "status": status}
    return {"applied": False, "reason": "no_pending_update"}

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
    text = path.read_text(encoding="utf-8-sig").strip()
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        digest = parts[0].lower()
        if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            if len(parts) > 1 and " ".join(parts[1:]).lstrip("*") != package_name:
                continue
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


def _download_file(url: str, target: Path, progress_callback: Any | None = None) -> None:
    import http.client
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    metadata = target.with_name(target.name + ".resume.json")
    opener = _build_url_opener()
    last_error = None
    for attempt in range(3):
        try:
            previous = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {}
        except (ValueError, OSError):
            previous = {}
        offset = partial.stat().st_size if partial.exists() else 0
        etag = str(previous.get("etag") or "")
        resumable = offset > 0 and etag and not etag.startswith("W/") and previous.get("url") == url
        headers = {"Accept": "application/octet-stream", "User-Agent": f"cli-bridge/{APP_VERSION}"}
        if resumable:
            headers.update(Range=f"bytes={offset}-", **{"If-Range": etag})
        _emit_download_log(progress_callback, f"正在下载 {target.name}（尝试 {attempt + 1}/3）")
        try:
            request = urllib.request.Request(url, headers=headers)
            with opener.open(request, timeout=60) as response:
                status = getattr(response, "status", 200)
                length = _parse_content_length(response.headers.get("Content-Length"))
                current_etag = str(response.headers.get("ETag") or "")
                append = status == 206
                if append:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if (not resumable or current_etag != etag or not match
                            or int(match[1]) != offset or int(match[2]) != int(match[3]) - 1
                            or (length is not None and length != int(match[2]) - offset + 1)
                            or (previous.get("total") is not None and previous["total"] != int(match[3]))):
                        partial.unlink(missing_ok=True)
                        metadata.unlink(missing_ok=True)
                        raise OSError("断点响应的 ETag、范围或总长度不一致")
                    total = int(match[3])
                elif status == 200:
                    offset, total = 0, length
                else:
                    raise OSError(f"下载响应状态无效: {status}")
                if total is not None and shutil.disk_usage(target.parent).free < total - offset + 64 * 1024**2:
                    raise RuntimeError("下载更新包的磁盘空间不足")
                metadata.write_text(json.dumps({"url": url, "etag": current_etag, "total": total}), encoding="utf-8")
                downloaded = offset
                with partial.open("ab" if append else "wb") as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total is not None and downloaded > total:
                            raise OSError("更新包下载长度超过响应长度")
                        _emit_download_progress(progress_callback, phase="downloading", downloaded_bytes=downloaded, total_bytes=total)
                    handle.flush()
                    os.fsync(handle.fileno())
                if total is not None and downloaded != total:
                    raise OSError(f"更新包下载不完整: 期望 {total} bytes，实际 {downloaded} bytes")
            _validate_package_file(partial, package_name=target.name)
            partial.replace(target)
            metadata.unlink(missing_ok=True)
            _emit_download_log(progress_callback, f"下载完成: {target.name}", downloaded_bytes=downloaded, total_bytes=downloaded)
            return
        except (urllib.error.URLError, OSError, http.client.IncompleteRead) as exc:
            last_error = exc
            if attempt < 2:
                _emit_download_log(progress_callback, f"下载暂时失败，稍后重试: {exc}")
                time.sleep(0.25 * 2 ** attempt)
    raise RuntimeError(f"下载失败，已保留可校验的断点文件: {last_error}")


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


def _run_frontend_build_command(command: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
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


def _build_updated_frontend(repo_root: Path) -> tuple[bool, str]:
    front_root = repo_root / "front"
    if not front_root.exists():
        return True, "未检测到前端目录，跳过构建"

    script_name = "build_web_frontend.bat" if os.name == "nt" else "build_web_frontend.sh"
    script_path = (repo_root / "scripts" / script_name).resolve()
    if script_path.exists():
        command = [str(script_path)] if os.name == "nt" else ["bash", str(script_path)]
        return _run_frontend_build_command(command, repo_root)

    npm_path = shutil.which("npm")
    if not npm_path:
        return False, "未找到前端构建脚本，且系统中没有 npm，无法重建前端资源"

    build_command = [npm_path, "run", "build"]
    success, output = _run_frontend_build_command(build_command, front_root)
    if success:
        return success, output

    installed, install_output = _run_frontend_build_command([npm_path, "ci", "--no-audit", "--no-fund"], front_root)
    if not installed:
        return installed, install_output
    return _run_frontend_build_command(build_command, front_root)


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


def _read_package_distribution_from_bytes(raw_bytes: bytes, *, package_name: str) -> dict[str, str]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8-sig"))
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
    from scripts.update_transaction import safe_target
    root = Path(repo_root).resolve()
    try:
        normalized_path = _normalize_archive_path(relative_path)
    except ValueError as exc:
        raise RuntimeError(f"更新包包含非法路径: {relative_path}") from exc
    if not normalized_path:
        raise RuntimeError(f"更新包包含非法路径: {relative_path}")
    return safe_target(root, normalized_path)


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
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _sync_runtime_announcements_from_package(
    package_path: Path,
    relative_paths: list[str],
    *,
    log_callback: Any | None = None,
) -> bool:
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


def _backup_update_targets(write_plan, *, temp_root: Path, journal_path: Path):
    from scripts.update_transaction import Transaction
    transaction = Transaction(temp_root.parent, temp_root)
    records = transaction.backup([relative for _, relative in write_plan])
    return {Path(record["target_path"]): {**record, "journal_path": str(journal_path)}
            for record in records.values()}

def _restore_update_targets(backups):
    from scripts.update_transaction import RecoveryRequired, Transaction, atomic_copy, sha256
    if not backups:
        return
    first = next(iter(backups.values()))
    if first.get("journal_path"):
        directory = Path(first["journal_path"]).parent
        Transaction(directory.parent, directory).rollback()
        return
    for target, record in backups.items():
        backup_text = str(record.get("backup_path") or "")
        if record.get("restored_sha256") and target.is_file() and sha256(target) == record["restored_sha256"]:
            continue
        if not backup_text:
            if target.exists():
                raise RecoveryRequired(f"旧事务缺少目标的归属证明，保留现场: {target}")
            continue
        backup = Path(backup_text)
        if not backup.is_file():
            raise RecoveryRequired(f"旧事务备份缺失，保留目标与现场: {backup}")
        if target.exists():
            if not target.is_file():
                raise RecoveryRequired(f"旧事务恢复目标不是普通文件: {target}")
            current_hash = sha256(target)
            if current_hash == sha256(backup):
                continue
            if current_hash != record.get("new_sha256"):
                raise RecoveryRequired(f"旧事务无法证明当前目标归属，保留目标与备份: {target}")
        atomic_copy(backup, target)
        record["restored_sha256"] = sha256(target)

def _recover_interrupted_update_applications(repo_root: Path, log_callback: Any | None = None) -> None:
    from scripts.update_transaction import RecoveryRequired, Transaction, read_journal
    for directory in repo_root.glob(".update-apply-*"):
        if not directory.is_dir():
            continue
        if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
            raise RecoveryRequired(f"事务目录经过链接，保留现场: {directory}")
        journal = directory / "journal.jsonl"
        if not journal.is_file():
            raise RecoveryRequired(f"旧更新事务缺少日志，恢复材料已保留: {directory}")
        records = read_journal(journal)
        if records and records[0].get("event") == "begin":
            Transaction(repo_root, directory).recover()
            continue
        if any(record.get("event") == "legacy_recovered" for record in records):
            continue
        backups = _read_update_journal(journal)
        if not backups:
            raise RecoveryRequired(f"旧事务日志不足以恢复，保留现场: {directory}")
        for target, record in backups.items():
            if _resolve_update_target_path(repo_root, record.get("relative_path", "")) != target.resolve():
                raise RecoveryRequired(f"旧事务目标不属于当前安装: {target}")
            backup = record.get("backup_path")
            if backup and Path(backup).resolve().parent != directory.resolve():
                raise RecoveryRequired(f"旧事务备份路径不属于事务目录: {backup}")
        _emit_apply_log(log_callback, f"正在恢复未完成的旧更新事务: {directory.name}")
        _restore_update_targets(backups)
        _append_update_journal(journal, {"event": "legacy_recovered"})


def _assert_no_unfinished_legacy_transactions(repo_root: Path) -> None:
    """Preparation cannot restore application files while the old host is running."""
    from scripts.update_transaction import RecoveryRequired, read_journal
    for directory in repo_root.glob(".update-apply-*"):
        if not directory.is_dir():
            continue
        journal = directory / "journal.jsonl"
        records = read_journal(journal) if journal.is_file() else []
        if records and records[-1].get("event") in {"committed", "rolled_back", "legacy_recovered"}:
            continue
        raise RecoveryRequired(
            f"recovery_required: 请退出旧宿主后用新版本的 recover-legacy --repo-root 参数指定安装目录恢复旧事务，保留目录: {directory}"
        )

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


def _replace_target_from_stream(target_path: Path, stream, *, journal_path: Path, backup_record: dict) -> None:
    from scripts.update_transaction import sha256, sync_directory
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target_path.name}.update-", dir=target_path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            shutil.copyfileobj(stream, handle, DOWNLOAD_CHUNK_SIZE)
            handle.flush()
            os.fsync(handle.fileno())
        backup_record.update(write_path=str(staged), new_sha256=sha256(staged))
        _append_update_journal(journal_path, {**backup_record, "event": "apply_intent"})
        staged.replace(target_path)
        sync_directory(target_path.parent)
        _append_update_journal(journal_path, {**backup_record, "event": "applied"})
    finally:
        staged.unlink(missing_ok=True)


def _stream_package_entries(package_path: Path, consumer: Any, *, open_files: bool = True) -> None:
    from scripts.update_package import archive_entries
    try:
        with archive_entries(package_path) as entries:
            for relative_path, _size, _mode, opener in entries:
                if not open_files:
                    consumer(relative_path, None)
                else:
                    with opener() as stream:
                        consumer(relative_path, stream)
    except (ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise _PackageStreamError(_format_invalid_package_message(package_path, exc)) from exc


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
    from scripts.update_package import normalize_path
    return normalize_path(raw_path)

def _normalize_archive_path_for_stream(package_path: Path, raw_path: str) -> str:
    try:
        return _normalize_archive_path(raw_path)
    except ValueError as exc:
        raise _PackageStreamError(
            _format_invalid_package_message(package_path, f"非法归档路径: {raw_path}")
        ) from exc


def _is_protected_update_path(relative_path: str) -> bool:
    from scripts.update_package import protected
    return protected(relative_path)

def _needs_frontend_build(repo_root: Path, relative_paths: list[str]) -> bool:
    normalized = [str(path or "").replace("\\", "/").strip("/") for path in relative_paths]
    if any(path.startswith("front/") for path in normalized):
        return True
    if any(path in FRONTEND_BUILD_TRIGGER_PATHS for path in normalized):
        return True
    front_root = repo_root / "front"
    return front_root.exists() and not (front_root / "dist").exists()


def _append_update_journal(journal_path: Path, record: dict[str, Any]) -> None:
    from scripts.update_transaction import append_journal
    append_journal(journal_path, record)

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
    recover_parser = subcommands.add_parser("recover-legacy", help="在宿主退出后恢复旧版文件事务")
    recover_parser.add_argument("--repo-root", required=True)
    recover_parser.add_argument("--host-stopped", action="store_true", required=True)
    args = parser.parse_args(argv)

    if args.command == "recover-legacy":
        try:
            _recover_interrupted_update_applications(Path(args.repo_root).resolve(), log_callback=print)
            return 0
        except Exception as exc:
            print(f"recovery_required: {exc}", file=sys.stderr)
            return 78
    if args.command == "apply-pending":
        result = apply_pending_update(Path(args.repo_root).resolve(), log_callback=print)
        return 0 if result.get("applied") or result.get("reason") in {"no_pending_update", "already_current_version"} else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
