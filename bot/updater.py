"""GitHub Release based updater."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot import app_settings
from bot.config import APP_UPDATE_REPOSITORY
from bot.version import APP_VERSION

UPDATE_CACHE_DIR_NAME = ".updates"
DOWNLOAD_CHUNK_SIZE = 64 * 1024
PROTECTED_UPDATE_PATHS = {
    ".env",
    "managed_bots.json",
    ".session_store.json",
    ".web_admin_settings.json",
    ".assistant",
    ".claude",
    ".git",
    ".updates",
}


def get_update_status() -> dict[str, Any]:
    settings = app_settings._load_settings()
    return {
        "current_version": APP_VERSION,
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
        "update_last_error": settings["update_last_error"],
    }


def set_update_enabled(enabled: bool) -> dict[str, Any]:
    settings = app_settings._load_settings()
    settings["update_enabled"] = bool(enabled)
    app_settings._save_settings(settings)
    return get_update_status()


def check_for_updates() -> dict[str, Any]:
    settings = app_settings._load_settings()
    settings["last_checked_at"] = _now_iso()
    settings["update_last_error"] = ""

    try:
        release = _fetch_latest_release()
    except Exception as exc:
        settings["update_last_error"] = str(exc)
        app_settings._save_settings(settings)
        return get_update_status()

    settings["last_available_version"] = _normalize_tag_name(release.get("tag_name"))
    settings["last_available_release_url"] = str(release.get("html_url") or "")
    settings["last_available_notes"] = str(release.get("body") or "")
    app_settings._save_settings(settings)
    return get_update_status()


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


def download_latest_update(
    repo_root: Path | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    settings = app_settings._load_settings()
    settings["last_checked_at"] = _now_iso()
    settings["update_last_error"] = ""
    _emit_download_log(progress_callback, "正在检查最新版本信息")

    try:
        release = _fetch_latest_release()
        settings["last_available_version"] = _normalize_tag_name(release.get("tag_name"))
        settings["last_available_release_url"] = str(release.get("html_url") or "")
        settings["last_available_notes"] = str(release.get("body") or "")

        asset = _select_release_asset(release.get("assets", []))
        cache_root = (repo_root or Path.cwd()) / UPDATE_CACHE_DIR_NAME
        cache_root.mkdir(parents=True, exist_ok=True)
        target_path = cache_root / asset["name"]
        _emit_download_log(progress_callback, f"找到更新包: {asset['name']}")
        if progress_callback is None:
            _download_file(asset["browser_download_url"], target_path)
        else:
            _download_file(
                asset["browser_download_url"],
                target_path,
                progress_callback=progress_callback,
            )
    except Exception as exc:
        settings["update_last_error"] = str(exc)
        app_settings._save_settings(settings)
        raise

    settings["pending_update_version"] = _normalize_tag_name(release["tag_name"])
    settings["pending_update_path"] = str(target_path)
    settings["pending_update_notes"] = str(release.get("body") or "")
    settings["pending_update_platform"] = "windows-x64" if os.name == "nt" else "linux-x64"
    app_settings._save_settings(settings)
    _emit_download_log(progress_callback, f"更新包已保存到: {target_path}")
    return get_update_status()


def _emit_apply_log(log_callback: Any | None, message: str) -> None:
    if log_callback is None:
        return
    log_callback(str(message))


def apply_pending_update(repo_root: Path, log_callback: Any | None = None) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    settings = app_settings._load_settings()
    pending_path = str(settings.get("pending_update_path") or "").strip()
    if not pending_path:
        _emit_apply_log(log_callback, "没有待应用的更新。")
        return {"applied": False, "reason": "no_pending_update"}
    pending_version = _normalize_tag_name(settings.get("pending_update_version"))
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

    try:
        package_entries = _iter_package_entries(package_path)
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

    extracted_files = 0
    for relative_path, data in package_entries:
        if _is_protected_update_path(relative_path):
            continue

        _emit_apply_log(log_callback, f"正在更新: {relative_path}")
        target_path = repo_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        extracted_files += 1

    _emit_apply_log(log_callback, "正在重建前端资源...")
    build_success, build_output = _build_updated_frontend(repo_root)
    if not build_success:
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
    if build_output:
        for line in str(build_output).splitlines():
            if line.strip():
                _emit_apply_log(log_callback, line)
    _emit_apply_log(log_callback, "前端资源重建完成。")

    _clear_pending_update(settings)
    settings["update_last_error"] = ""
    app_settings._save_settings(settings)
    _emit_apply_log(log_callback, "更新应用完成。")
    return {
        "applied": True,
        "version": pending_version or _normalize_tag_name(settings.get("last_available_version")),
        "frontend_built": True,
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


def _select_release_asset(assets: list[dict[str, Any]]) -> dict[str, Any]:
    expected_token = "windows" if os.name == "nt" else "linux"
    expected_suffix = ".zip" if os.name == "nt" else ".tar.gz"
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if expected_token in name and name.endswith(expected_suffix):
            return asset
    raise RuntimeError("未找到当前平台的 release 包")


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


def _iter_zip_entries(package_path: Path) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(package_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            relative_path = _normalize_archive_path(member.filename)
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
            relative_path = _normalize_archive_path(member.name)
            if not relative_path:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            entries.append((relative_path, extracted.read()))
    return entries


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
    parts: list[str] = []
    for part in str(raw_path or "").replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            return ""
        parts.append(part)
    return "/".join(parts)


def _is_protected_update_path(relative_path: str) -> bool:
    root_name = relative_path.split("/", 1)[0]
    return relative_path in PROTECTED_UPDATE_PATHS or root_name in PROTECTED_UPDATE_PATHS


def _clear_pending_update(settings: dict[str, Any]) -> None:
    settings["pending_update_version"] = ""
    settings["pending_update_path"] = ""
    settings["pending_update_notes"] = ""
    settings["pending_update_platform"] = ""


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
        return 0 if result.get("applied") or result.get("reason") == "no_pending_update" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
