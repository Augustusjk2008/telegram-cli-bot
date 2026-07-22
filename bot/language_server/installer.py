"""固定清单驱动的语言服务器托管安装器。"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import socket
import shutil
import stat
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.request import urlopen

from bot.runtime_paths import (
    get_language_server_managed_root,
    get_language_server_native_tools_dir,
    get_language_server_node_tools_dir,
)

from .manifest import (
    LanguageServerAsset,
    LanguageServerManifest,
    LanguageServerManifestError,
    LanguageServerProvider,
    current_platform_key,
    load_language_server_manifest,
    normalize_platform_key,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST_PATH = _REPO_ROOT / "tools" / "language-servers" / "manifest.json"
_LOCK_GUARD = threading.Lock()
_INSTALL_LOCKS: dict[str, threading.Lock] = {}
_ACTIVE_INSTALLS: dict[str, int] = {}


class LanguageServerInstallError(RuntimeError):
    """可安全返回给 Web API 的托管安装错误。"""

    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class LanguageServerInstaller:
    """下载、校验并事务性激活固定版本语言服务器资产。

    Node provider 共用一个 ``node`` 根目录和其中的 ``node_modules``；因此以
    该根目录为锁粒度，避免 Pyright 与 TypeScript 同时替换包目录。
    """

    def __init__(
        self,
        *,
        manifest: LanguageServerManifest | None = None,
        manifest_path: Path | str | None = None,
        managed_root: Path | str | None = None,
        node_tools_dir: Path | str | None = None,
        native_tools_dir: Path | str | None = None,
        platform_key: str | None = None,
        download_timeout_seconds: float = 30.0,
        download_max_bytes: int = 512 * 1024 * 1024,
        lock_timeout_seconds: float = 60.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        if manifest is not None and manifest_path is not None:
            raise ValueError("manifest 与 manifest_path 不能同时指定")
        self.manifest_error: LanguageServerManifestError | None = None
        if manifest is not None:
            self.manifest: LanguageServerManifest | None = manifest
        else:
            try:
                self.manifest = load_language_server_manifest(manifest_path or _DEFAULT_MANIFEST_PATH)
            except LanguageServerManifestError as exc:
                # 默认关闭的语言服务不能因为发布资产缺失而阻断整个 Web 服务启动。
                self.manifest = None
                self.manifest_error = exc
        self.managed_root = Path(managed_root or get_language_server_managed_root())
        self._storage_error = ""
        if managed_root is None and _is_within_repository(self.managed_root):
            self._storage_error = "托管语言服务器目录不能位于项目仓库内"
        self.node_tools_dir = Path(
            node_tools_dir
            or (self.managed_root / "node" if managed_root is not None else get_language_server_node_tools_dir())
        )
        self.native_tools_dir = Path(
            native_tools_dir
            or (self.managed_root / "native" if managed_root is not None else get_language_server_native_tools_dir())
        )
        self.platform_key = normalize_platform_key(platform_key or current_platform_key())
        self.download_timeout_seconds = max(0.01, float(download_timeout_seconds))
        self.download_max_bytes = max(1, int(download_max_bytes))
        self.lock_timeout_seconds = max(1.0, float(lock_timeout_seconds))
        self._opener = opener or urlopen
        self._last_errors: dict[str, dict[str, str]] = {}
        self._error_guard = threading.Lock()

    def provider(self, provider_id: str) -> LanguageServerProvider:
        if self.manifest is None:
            raise LanguageServerInstallError(
                "language_server_manifest_unavailable",
                "语言服务器清单不可用，请检查安装包完整性",
            )
        try:
            return self.manifest.get(provider_id)
        except LanguageServerManifestError as exc:
            raise LanguageServerInstallError("invalid_language_server_provider", str(exc)) from exc

    def can_install(self, provider_id: str) -> bool:
        if self._storage_error:
            return False
        return bool(self.provider(provider_id).select_assets(self.platform_key))

    def last_error(self, provider_id: str) -> dict[str, str] | None:
        with self._error_guard:
            error = self._last_errors.get(provider_id)
            return dict(error) if error is not None else None

    def installation_root(self, provider_id: str) -> Path:
        provider = self.provider(provider_id)
        if provider.runtime == "node":
            return self.node_tools_dir
        return self.native_tools_dir / provider.provider_id

    def is_installing(self, provider_id: str) -> bool:
        root = self.installation_root(provider_id)
        key = self._lock_key(root)
        with _LOCK_GUARD:
            if _ACTIVE_INSTALLS.get(key, 0) > 0:
                return True
        # OS advisory lock 会在持有进程异常退出时自动释放；锁文件本身可
        # 长期保留，不能再用“文件存在”推断仍在安装。
        return _FileInstallLock.is_locked(root / ".install.lock")

    def current_installation(self, provider_id: str) -> dict[str, Any] | None:
        provider = self.provider(provider_id)
        selected = provider.select_assets(self.platform_key)
        if not selected:
            return None
        root = self.installation_root(provider_id)
        state_path = self._state_path(provider, root)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict):
            return None
        if state.get("provider") != provider.provider_id:
            return None
        installed_version = str(state.get("version") or "").strip()
        if not installed_version:
            return None
        if state.get("runtime") not in {None, provider.runtime}:
            return None
        if state.get("platform") != self.platform_key and provider.runtime != "node":
            return None
        installed_targets = state.get("targets")
        if not isinstance(installed_targets, list) or not installed_targets:
            return None
        targets = [str(item or "").strip() for item in installed_targets]
        if any(not _is_safe_state_target(item) for item in targets):
            return None
        entrypoint = self._installed_entrypoint_path(provider, targets, root)
        if entrypoint is None or not entrypoint.is_file():
            return None
        if any(not (root / target).is_dir() for target in targets):
            return None
        installed_assets = _normalized_asset_identity(state.get("assets"))
        expected_assets = [
            {"id": asset.asset_id, "version": asset.version, "sha256": asset.sha256}
            for asset in selected
        ]
        expected_targets = [asset.target for asset in selected]
        update_available = bool(
            installed_version != provider.version
            or targets != expected_targets
            or installed_assets != expected_assets
        )
        return {
            "provider": provider.provider_id,
            "version": installed_version,
            "targetVersion": provider.version,
            "updateAvailable": update_available,
            "runtime": provider.runtime,
            "platform": self.platform_key,
            "entrypoint": str(entrypoint),
            "targets": targets,
            "assets": installed_assets,
            "installedAt": state.get("installedAt"),
        }

    def install(self, provider_id: str, *, update: bool = False) -> dict[str, Any]:
        try:
            result = self._install(provider_id, update=update)
        except LanguageServerInstallError as exc:
            self._remember_error(provider_id, exc)
            raise
        except OSError as exc:
            error = LanguageServerInstallError(
                "language_server_storage_unavailable",
                "语言服务器安装目录不可写",
                {"provider": provider_id},
            )
            self._remember_error(provider_id, error)
            raise error from exc
        self._clear_error(provider_id)
        return result

    def _install(self, provider_id: str, *, update: bool) -> dict[str, Any]:
        if self._storage_error:
            raise LanguageServerInstallError(
                "language_server_storage_unsafe",
                self._storage_error,
                {"provider": provider_id, "managed_root": str(self.managed_root)},
            )
        provider = self.provider(provider_id)
        selected = provider.select_assets(self.platform_key)
        if not selected:
            raise LanguageServerInstallError(
                "language_server_platform_unsupported",
                f"{provider.display_name} 暂不支持当前平台 {self.platform_key} 的托管安装",
                {"provider": provider.provider_id, "platform": self.platform_key},
            )

        root = self.installation_root(provider_id)
        key = self._lock_key(root)
        with self._mark_active(key):
            lock = self._shared_lock(key)
            with lock:
                root.mkdir(parents=True, exist_ok=True)
                with _FileInstallLock(root / ".install.lock", timeout_seconds=self.lock_timeout_seconds):
                    current = self.current_installation(provider_id)
                    if current is not None and not update:
                        if current.get("updateAvailable"):
                            return {
                                "provider": provider.provider_id,
                                "version": str(current.get("version") or ""),
                                "targetVersion": provider.version,
                                "status": "update_available",
                                "source": "managed",
                            }
                        return {
                            "provider": provider.provider_id,
                            "version": str(current.get("version") or provider.version),
                            "status": "already_installed",
                            "source": "managed",
                        }
                    self._install_locked(provider, selected, root)
        return {
            "provider": provider.provider_id,
            "version": provider.version,
            "status": "installed",
            "source": "managed",
        }

    def _remember_error(self, provider_id: str, error: LanguageServerInstallError) -> None:
        with self._error_guard:
            self._last_errors[provider_id] = {"code": error.code, "message": error.message}

    def _clear_error(self, provider_id: str) -> None:
        with self._error_guard:
            self._last_errors.pop(provider_id, None)

    def _install_locked(
        self,
        provider: LanguageServerProvider,
        selected: tuple[LanguageServerAsset, ...],
        root: Path,
    ) -> None:
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=root))
        downloaded: list[Path] = []
        try:
            for asset in selected:
                archive_path = self._download_asset(asset, root)
                downloaded.append(archive_path)
                destination = stage / asset.target
                self._extract_asset(asset, archive_path, destination)
            entrypoint = self._entrypoint_path(provider, selected, stage)
            if entrypoint is None or not entrypoint.is_file():
                raise LanguageServerInstallError(
                    "language_server_entrypoint_missing",
                    f"{provider.display_name} 安装包缺少语言服务器入口",
                    {"provider": provider.provider_id},
                )
            if provider.runtime == "native" and os.name != "nt":
                entrypoint.chmod(entrypoint.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
            self._activate_stage(provider, selected, root, stage)
        except LanguageServerInstallError:
            raise
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            raise LanguageServerInstallError(
                "language_server_install_failed",
                f"{provider.display_name} 安装失败，已保留之前版本",
                {"provider": provider.provider_id},
            ) from exc
        finally:
            for archive_path in downloaded:
                archive_path.unlink(missing_ok=True)
            shutil.rmtree(stage, ignore_errors=True)

    def _download_asset(self, asset: LanguageServerAsset, root: Path) -> Path:
        fd, temporary_name = tempfile.mkstemp(prefix=".download-", suffix=".tmp", dir=root)
        os.close(fd)
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        deadline = time.monotonic() + self.download_timeout_seconds
        downloaded_bytes = 0
        try:
            with self._opener(asset.url, timeout=self.download_timeout_seconds) as response, temporary_path.open("wb") as output:
                content_length = _response_content_length(response)
                if content_length is not None and content_length > self.download_max_bytes:
                    raise LanguageServerInstallError(
                        "language_server_download_too_large",
                        f"{asset.asset_id} 安装包超过大小限制",
                        {"asset": asset.asset_id, "maximum": self.download_max_bytes},
                    )
                while True:
                    if time.monotonic() >= deadline:
                        raise LanguageServerInstallError(
                            "language_server_download_timeout",
                            f"下载 {asset.asset_id} 超时",
                            {"asset": asset.asset_id},
                        )
                    chunk = response.read(1024 * 1024)
                    if time.monotonic() >= deadline:
                        raise LanguageServerInstallError(
                            "language_server_download_timeout",
                            f"下载 {asset.asset_id} 超时",
                            {"asset": asset.asset_id},
                        )
                    if not chunk:
                        break
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > self.download_max_bytes:
                        raise LanguageServerInstallError(
                            "language_server_download_too_large",
                            f"{asset.asset_id} 安装包超过大小限制",
                            {"asset": asset.asset_id, "maximum": self.download_max_bytes},
                        )
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
        except LanguageServerInstallError:
            temporary_path.unlink(missing_ok=True)
            raise
        except (TimeoutError, socket.timeout) as exc:
            temporary_path.unlink(missing_ok=True)
            raise LanguageServerInstallError(
                "language_server_download_timeout",
                f"下载 {asset.asset_id} 超时",
                {"asset": asset.asset_id},
            ) from exc
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            raise LanguageServerInstallError(
                "language_server_download_failed",
                f"下载 {asset.asset_id} 失败",
                {"asset": asset.asset_id},
            ) from exc
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != asset.sha256:
            temporary_path.unlink(missing_ok=True)
            raise LanguageServerInstallError(
                "language_server_checksum_mismatch",
                f"{asset.asset_id} 校验和不匹配，未安装该版本",
                {"asset": asset.asset_id, "expected": asset.sha256, "actual": actual_sha256},
            )
        return temporary_path

    def _extract_asset(self, asset: LanguageServerAsset, archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        if asset.archive == "zip":
            self._extract_zip(asset, archive_path, destination)
        elif asset.archive == "tar.gz":
            self._extract_tar(asset, archive_path, destination)
        else:  # 清单校验已覆盖，保留防御式错误以避免未来扩展绕过。
            raise LanguageServerInstallError("language_server_archive_unsupported", f"不支持的归档格式: {asset.archive}")

    def _extract_zip(self, asset: LanguageServerAsset, archive_path: Path, destination: Path) -> None:
        seen: set[str] = set()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                relative = _archive_relative_path(member.filename, asset.archive_root)
                if relative is None:
                    continue
                if relative in seen:
                    raise LanguageServerInstallError("language_server_archive_unsafe", "归档包含重复路径")
                seen.add(relative)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise LanguageServerInstallError("language_server_archive_unsafe", "归档不允许符号链接")
                target = _safe_extract_target(destination, relative)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if mode:
                    target.chmod(mode & 0o777)

    def _extract_tar(self, asset: LanguageServerAsset, archive_path: Path, destination: Path) -> None:
        seen: set[str] = set()
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                relative = _archive_relative_path(member.name, asset.archive_root)
                if relative is None:
                    continue
                if relative in seen:
                    raise LanguageServerInstallError("language_server_archive_unsafe", "归档包含重复路径")
                seen.add(relative)
                if member.issym() or member.islnk() or member.isdev():
                    raise LanguageServerInstallError("language_server_archive_unsafe", "归档不允许链接或设备文件")
                target = _safe_extract_target(destination, relative)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise LanguageServerInstallError("language_server_archive_unsafe", "归档包含不支持的条目")
                source = archive.extractfile(member)
                if source is None:
                    raise LanguageServerInstallError("language_server_archive_unsafe", "无法读取归档条目")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)

    def _activate_stage(
        self,
        provider: LanguageServerProvider,
        selected: tuple[LanguageServerAsset, ...],
        root: Path,
        stage: Path,
    ) -> None:
        backup_root = root / f".backup-{uuid.uuid4().hex}"
        moved_targets: list[tuple[Path, Path]] = []
        backups: list[tuple[Path, Path]] = []
        cleanup_backup = True
        try:
            for index, asset in enumerate(selected):
                source = stage / asset.target
                target = root / asset.target
                if not source.is_dir():
                    raise LanguageServerInstallError("language_server_install_failed", "安装暂存目录不完整")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    backup_target = backup_root / str(index)
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup_target)
                    backups.append((target, backup_target))
                os.replace(source, target)
                moved_targets.append((target, source))
            self._write_state_atomic(provider, selected, root)
        except Exception as exc:
            rollback_error: Exception | None = None
            for target, source in reversed(moved_targets):
                try:
                    if target.exists() or target.is_symlink():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(target, source)
                except OSError as rollback_exc:
                    rollback_error = rollback_exc
            for target, backup_target in reversed(backups):
                try:
                    if backup_target.exists() or backup_target.is_symlink():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(backup_target, target)
                except OSError as rollback_exc:
                    rollback_error = rollback_exc
            recovery_available = any(
                backup_target.exists() or backup_target.is_symlink()
                for _target, backup_target in backups
            )
            if rollback_error is not None:
                cleanup_backup = not recovery_available
                raise LanguageServerInstallError(
                    "language_server_rollback_failed",
                    f"{provider.display_name} 安装失败且回滚不完整",
                    {
                        "provider": provider.provider_id,
                        "recovery_available": recovery_available,
                        "recovery_id": backup_root.name if recovery_available else "",
                    },
                ) from rollback_error
            if isinstance(exc, LanguageServerInstallError):
                raise
            raise LanguageServerInstallError(
                "language_server_install_failed",
                f"{provider.display_name} 安装失败，已保留之前版本",
                {"provider": provider.provider_id},
            ) from exc
        finally:
            if cleanup_backup:
                shutil.rmtree(backup_root, ignore_errors=True)

    def _write_state_atomic(
        self,
        provider: LanguageServerProvider,
        selected: tuple[LanguageServerAsset, ...],
        root: Path,
    ) -> None:
        state_path = self._state_path(provider, root)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": 1,
            "provider": provider.provider_id,
            "version": provider.version,
            "runtime": provider.runtime,
            "platform": self.platform_key,
            "targets": [asset.target for asset in selected],
            "assets": [{"id": asset.asset_id, "version": asset.version, "sha256": asset.sha256} for asset in selected],
            "installedAt": int(time.time()),
        }
        fd, temporary_name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, state_path)
        except OSError:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    def _state_path(self, provider: LanguageServerProvider, root: Path) -> Path:
        if provider.runtime == "node":
            return root / ".providers" / f"{provider.provider_id}.json"
        return root / "current.json"

    def _entrypoint_path(
        self,
        provider: LanguageServerProvider,
        selected: tuple[LanguageServerAsset, ...],
        root: Path,
    ) -> Path | None:
        entrypoint = provider.entrypoint_for(self.platform_key)
        if not entrypoint:
            return None
        if provider.runtime == "node":
            return root / entrypoint
        if len(selected) != 1:
            return None
        return root / selected[0].target / entrypoint

    def _installed_entrypoint_path(
        self,
        provider: LanguageServerProvider,
        targets: list[str],
        root: Path,
    ) -> Path | None:
        entrypoint = provider.entrypoint_for(self.platform_key)
        if not entrypoint:
            return None
        if provider.runtime == "node":
            return root / entrypoint
        if len(targets) != 1:
            return None
        return root / targets[0] / entrypoint

    @staticmethod
    def _lock_key(root: Path) -> str:
        return str(root.expanduser().resolve())

    @staticmethod
    def _shared_lock(key: str) -> threading.Lock:
        with _LOCK_GUARD:
            return _INSTALL_LOCKS.setdefault(key, threading.Lock())

    @contextmanager
    def _mark_active(self, key: str) -> Iterator[None]:
        with _LOCK_GUARD:
            _ACTIVE_INSTALLS[key] = _ACTIVE_INSTALLS.get(key, 0) + 1
        try:
            yield
        finally:
            with _LOCK_GUARD:
                remaining = _ACTIVE_INSTALLS.get(key, 1) - 1
                if remaining > 0:
                    _ACTIVE_INSTALLS[key] = remaining
                else:
                    _ACTIVE_INSTALLS.pop(key, None)


class _FileInstallLock:
    """无第三方依赖、由 OS 在进程退出时自动释放的跨进程安装锁。"""

    def __init__(self, path: Path, *, timeout_seconds: float) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._owned = False
        self._handle = None

    def __enter__(self) -> "_FileInstallLock":
        deadline = time.monotonic() + self.timeout_seconds
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a+b")
            _ensure_lock_byte(self._handle)
        except OSError as exc:
            raise LanguageServerInstallError(
                "language_server_storage_unavailable",
                "语言服务器安装目录不可写",
            ) from exc
        while True:
            try:
                acquired = _try_os_file_lock(self._handle)
            except OSError as exc:
                self._handle.close()
                self._handle = None
                raise LanguageServerInstallError(
                    "language_server_storage_unavailable",
                    "无法锁定语言服务器安装目录",
                ) from exc
            if not acquired:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise LanguageServerInstallError("language_server_install_locked", "语言服务器正在由另一进程安装")
                time.sleep(0.05)
                continue
            self._owned = True
            try:
                self._handle.seek(0)
                marker = f"{os.getpid()} {int(time.time())}\n".encode("ascii")
                self._handle.write(marker)
                self._handle.flush()
            except OSError:
                # 锁本身已经生效；诊断 marker 写入失败不影响互斥正确性。
                pass
            return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        if self._owned:
            try:
                _release_os_file_lock(self._handle)
            except OSError:
                pass
            self._owned = False
        self._handle.close()
        self._handle = None

    @classmethod
    def is_locked(cls, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            handle = path.open("a+b")
            _ensure_lock_byte(handle)
        except FileNotFoundError:
            return False
        except OSError:
            # 无法检查的锁文件按“忙”处理，避免读状态撞入事务中间态。
            return True
        try:
            acquired = _try_os_file_lock(handle)
            if not acquired:
                return True
            _release_os_file_lock(handle)
            return False
        except OSError:
            return True
        finally:
            handle.close()


def _ensure_lock_byte(handle) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _try_os_file_lock(handle) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, 13, 36}:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _release_os_file_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _archive_relative_path(member_name: str, archive_root: str) -> str | None:
    normalized = str(member_name or "").replace("\\", "/").rstrip("/")
    if normalized.startswith("/") or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise LanguageServerInstallError("language_server_archive_unsafe", "归档包含不安全路径")
    if archive_root:
        if normalized == archive_root:
            return None
        prefix = f"{archive_root}/"
        if not normalized.startswith(prefix):
            raise LanguageServerInstallError("language_server_archive_unsafe", "归档根目录不符合固定清单")
        normalized = normalized[len(prefix) :]
    return normalized


def _is_safe_state_target(value: str) -> bool:
    normalized = str(value or "").replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("/") or Path(normalized).is_absolute():
        return False
    parts = normalized.split("/")
    if ":" in parts[0]:
        return False
    return all(part not in {"", ".", ".."} for part in parts)


def _normalized_asset_identity(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            return []
        asset_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "").strip()
        sha256 = str(item.get("sha256") or "").strip().lower()
        if not asset_id or not version or len(sha256) != 64:
            return []
        normalized.append({"id": asset_id, "version": version, "sha256": sha256})
    return normalized


def _is_within_repository(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(_REPO_ROOT.resolve())
    except (OSError, ValueError):
        return False
    return True


def _response_content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Content-Length")
    except (AttributeError, TypeError):
        return None
    try:
        length = int(str(value))
    except (TypeError, ValueError):
        return None
    return length if length >= 0 else None


def _safe_extract_target(destination: Path, relative: str) -> Path:
    target = (destination / relative).resolve()
    root = destination.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise LanguageServerInstallError("language_server_archive_unsafe", "归档路径越界") from exc
    return target
