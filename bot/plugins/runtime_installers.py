from __future__ import annotations

import hashlib
import re
import shutil
import stat
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class RuntimeInstallerError(RuntimeError):
    """A controlled plugin runtime installation failed."""


@dataclass(frozen=True)
class RuntimeInstallSpec:
    key: str
    plugin_id: str
    version: str
    url: str
    sha256: str
    max_download_bytes: int
    target_relative_path: str
    required_member: str = "bin/dot.exe"


GRAPHVIZ_RUNTIME_KEY = "mermaid-visio/graphviz"
# Verified against the official page and checksum sidecar:
# https://graphviz.org/download/
# https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/16.1.0/
# windows_10_cmake_Release_Graphviz-16.1.0-win64.zip.sha256
GRAPHVIZ_RUNTIME_SPEC = RuntimeInstallSpec(
    key=GRAPHVIZ_RUNTIME_KEY,
    plugin_id="mermaid-visio",
    version="16.1.0",
    url=(
        "https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/"
        "16.1.0/windows_10_cmake_Release_Graphviz-16.1.0-win64.zip"
    ),
    sha256="733e49626c492242eb8dca30ea627b6ead20710e207998c7933b4909d92d6abc",
    max_download_bytes=16 * 1024 * 1024,
    target_relative_path="vendor/graphviz/win-x64",
)

RUNTIME_INSTALL_ALLOWLIST: Mapping[str, RuntimeInstallSpec] = {
    GRAPHVIZ_RUNTIME_KEY: GRAPHVIZ_RUNTIME_SPEC,
}

_INSTALL_LOCKS: dict[str, threading.Lock] = {}
_INSTALL_LOCKS_GUARD = threading.Lock()
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 60.0
_MAX_EXTRACTED_BYTES_MULTIPLIER = 8
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "conin$",
    "conout$",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}
_WINDOWS_FORBIDDEN_NAME_CHARS = set('<>:"|?*')


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(str(newurl)).scheme.lower() != "https":
            raise RuntimeInstallerError("运行时下载重定向必须使用 HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HTTPS_OPENER = urllib.request.build_opener(_HttpsOnlyRedirectHandler)


def _runtime_install_lock(key: str) -> threading.Lock:
    with _INSTALL_LOCKS_GUARD:
        return _INSTALL_LOCKS.setdefault(key, threading.Lock())


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        path.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_symlink_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise RuntimeInstallerError("运行时路径包含符号链接")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _target_path(plugin_root: Path, spec: RuntimeInstallSpec) -> Path:
    lexical_root = plugin_root.expanduser().absolute()
    _reject_symlink_ancestors(lexical_root)
    root = lexical_root.resolve()
    if not root.is_dir():
        raise RuntimeInstallerError(f"插件目录不存在: {root}")
    relative = PurePosixPath(spec.target_relative_path)
    if relative.is_absolute() or ".." in relative.parts or _DRIVE_PATH_RE.match(str(relative)):
        raise RuntimeInstallerError("运行时目标策略不安全")
    lexical_target = lexical_root.joinpath(*relative.parts)
    _reject_symlink_ancestors(lexical_target)
    target = lexical_target.resolve()
    if target == root or root not in target.parents:
        raise RuntimeInstallerError("运行时目标策略越界")
    return target


def _zip_member_parts(member: zipfile.ZipInfo) -> tuple[str, ...]:
    raw_name = str(member.orig_filename or "")
    if not raw_name or "\x00" in raw_name:
        raise RuntimeInstallerError("运行时压缩包包含不安全成员")
    normalized = raw_name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or _DRIVE_PATH_RE.match(normalized):
        raise RuntimeInstallerError("运行时压缩包包含绝对路径")
    raw_parts = normalized.split("/")
    if member.is_dir() and raw_parts and raw_parts[-1] == "":
        raw_parts.pop()
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise RuntimeInstallerError("运行时压缩包包含越界路径")
    for part in raw_parts:
        if part[-1] in ". ":
            raise RuntimeInstallerError("运行时压缩包包含 Windows 不安全文件名")
        if any(ord(char) < 0x20 or char in _WINDOWS_FORBIDDEN_NAME_CHARS for char in part):
            raise RuntimeInstallerError("运行时压缩包包含 Windows 不安全文件名")
        device_name = part.split(".", 1)[0].rstrip(" .").casefold()
        if device_name in _WINDOWS_RESERVED_NAMES:
            raise RuntimeInstallerError("运行时压缩包包含 Windows 保留设备名")
    mode = (member.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise RuntimeInstallerError("运行时压缩包包含符号链接")
    if file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}:
        raise RuntimeInstallerError("运行时压缩包包含不支持的文件类型")
    return tuple(raw_parts)


def _safe_extract(archive: zipfile.ZipFile, target_dir: Path, max_bytes: int) -> None:
    _reject_symlink_ancestors(target_dir)
    target_root = target_dir.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, ...]] = set()
    declared_bytes = 0
    actual_bytes = 0
    for member in archive.infolist():
        parts = _zip_member_parts(member)
        alias = tuple(part.casefold() for part in parts)
        if alias in seen:
            raise RuntimeInstallerError("运行时压缩包包含重复成员")
        seen.add(alias)
        lexical_destination = target_dir.joinpath(*parts)
        _reject_symlink_ancestors(lexical_destination)
        destination = lexical_destination.resolve()
        if destination != target_root and target_root not in destination.parents:
            raise RuntimeInstallerError("运行时压缩包包含越界路径")
        if member.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        declared_bytes += max(0, int(member.file_size))
        if declared_bytes > max_bytes:
            raise RuntimeInstallerError("运行时压缩包解压后超过大小限制")
        destination.parent.mkdir(parents=True, exist_ok=True)
        member_bytes = 0
        with archive.open(member, "r") as source, destination.open("wb") as target:
            while True:
                chunk = source.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                member_bytes += len(chunk)
                actual_bytes += len(chunk)
                if actual_bytes > max_bytes:
                    raise RuntimeInstallerError("运行时压缩包解压后超过大小限制")
                target.write(chunk)
        if member_bytes != int(member.file_size):
            raise RuntimeInstallerError("运行时压缩包成员大小不匹配")


def _find_runtime_root(extract_dir: Path, required_member: str) -> Path:
    required_name = PurePosixPath(required_member).name.lower()
    candidates = [path for path in extract_dir.rglob("*") if path.name.casefold() == required_name and path.is_file()]
    candidates = [path for path in candidates if path.parent.name.lower() == "bin"]
    if not candidates:
        raise RuntimeInstallerError(f"运行时压缩包中未找到 {required_member}")
    _reject_symlink_ancestors(candidates[0].parent.parent)
    runtime_root = candidates[0].parent.parent.resolve()
    extract_root = extract_dir.resolve()
    if runtime_root == extract_root or extract_root not in runtime_root.parents:
        raise RuntimeInstallerError("运行时压缩包目录结构不安全")
    return runtime_root


def _replace_runtime_dir(source: Path, target: Path) -> None:
    """Replace a runtime directory while restoring the old one if promotion fails."""
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.parent / f".{target.name}.backup-{uuid.uuid4().hex}"
    promoted = False
    try:
        if target.exists() or target.is_symlink():
            target.rename(backup)
        try:
            source.rename(target)
            promoted = True
        except Exception:
            if target.exists() or target.is_symlink():
                _remove_path(target)
            if backup.exists() or backup.is_symlink():
                backup.rename(target)
            raise
    finally:
        _remove_path(source)
        if promoted:
            _remove_path(backup)


class PluginRuntimeInstaller:
    def __init__(
        self,
        allowlist: Mapping[str, RuntimeInstallSpec] | None = None,
        *,
        timeout_seconds: float = _DOWNLOAD_TIMEOUT_SECONDS,
        opener: Any | None = None,
    ) -> None:
        self.allowlist = dict(allowlist or RUNTIME_INSTALL_ALLOWLIST)
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def install(self, runtime_key: str, plugin_root: Path | str) -> dict[str, object]:
        key = str(runtime_key or "").strip()
        spec = self.allowlist.get(key)
        if spec is None:
            raise RuntimeInstallerError(f"不支持的插件运行时: {key}")
        root = Path(plugin_root)
        target = _target_path(root, spec)
        lock_key = f"{spec.key}:{target}"
        with _runtime_install_lock(lock_key):
            try:
                return self._install_locked(spec, target)
            except RuntimeInstallerError:
                raise
            except Exception as exc:
                raise RuntimeInstallerError(f"运行时安装失败: {exc}") from exc

    def _install_locked(self, spec: RuntimeInstallSpec, target: Path) -> dict[str, object]:
        created_parents: list[Path] = []
        current = target.parent
        while not current.exists():
            created_parents.append(current)
            current = current.parent
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".runtime-install-", dir=str(target.parent)) as work_dir:
                work = Path(work_dir)
                archive_path = work / "runtime.zip"
                self._download(spec, archive_path)
                digest = _sha256_file(archive_path)
                if digest.lower() != spec.sha256.lower():
                    raise RuntimeInstallerError(f"运行时 SHA256 校验失败: {digest}")

                extract_dir = work / "extract"
                try:
                    with zipfile.ZipFile(archive_path) as archive:
                        _safe_extract(
                            archive,
                            extract_dir,
                            max_bytes=spec.max_download_bytes * _MAX_EXTRACTED_BYTES_MULTIPLIER,
                        )
                except RuntimeInstallerError:
                    raise
                except Exception as exc:
                    raise RuntimeInstallerError(f"运行时压缩包无效: {exc}") from exc

                runtime_root = _find_runtime_root(extract_dir, spec.required_member)
                staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
                try:
                    shutil.copytree(runtime_root, staging)
                    (staging / "MERMAID_VISIO_GRAPHVIZ_NOTICE.txt").write_text(
                        "Graphviz runtime is installed locally for Mermaid Visio.\n"
                        "Graphviz is distributed under the Eclipse Public License 2.0.\n"
                        "License: https://graphviz.org/license/\n"
                        "EPL-2.0: https://www.eclipse.org/legal/epl-2.0/\n"
                        f"Version: {spec.version}\n",
                        encoding="utf-8",
                    )
                    _replace_runtime_dir(staging, target)
                finally:
                    _remove_path(staging)
        finally:
            for parent in created_parents:
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()

        return {
            "ok": True,
            "runtimeId": spec.key,
            "version": spec.version,
            "message": "Graphviz 运行时已安装",
            "dotPath": str(target / "bin" / "dot.exe"),
        }

    def _download(self, spec: RuntimeInstallSpec, destination: Path) -> None:
        parsed = urllib.parse.urlparse(spec.url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise RuntimeInstallerError("运行时下载地址必须使用 HTTPS")
        started_at = time.monotonic()

        def check_elapsed() -> None:
            if time.monotonic() - started_at > self.timeout_seconds:
                raise RuntimeInstallerError("运行时下载超时")

        try:
            if self._opener is not None:
                response_context = self._opener(spec.url, timeout=self.timeout_seconds)
            else:
                response_context = _HTTPS_OPENER.open(spec.url, timeout=self.timeout_seconds)
            with response_context as response:
                check_elapsed()
                geturl = getattr(response, "geturl", None)
                response_url = geturl() if callable(geturl) else spec.url
                final_url = urllib.parse.urlparse(str(response_url or spec.url))
                if final_url.scheme.lower() != "https":
                    raise RuntimeInstallerError("运行时下载重定向必须使用 HTTPS")
                header_value = response.headers.get("Content-Length")
                expected_size: int | None = None
                if header_value is not None:
                    try:
                        expected_size = int(str(header_value).strip())
                    except ValueError as exc:
                        raise RuntimeInstallerError("运行时 Content-Length 无效") from exc
                    if expected_size < 0 or expected_size > spec.max_download_bytes:
                        raise RuntimeInstallerError("运行时下载超过大小限制")

                total = 0
                # One socket read keeps elapsed checks effective for trickle downloads.
                read_chunk = getattr(response, "read1", response.read)
                with destination.open("wb") as output:
                    while True:
                        check_elapsed()
                        chunk = read_chunk(_DOWNLOAD_CHUNK_BYTES)
                        check_elapsed()
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > spec.max_download_bytes:
                            raise RuntimeInstallerError("运行时下载超过大小限制")
                        output.write(chunk)
                if expected_size is not None and total != expected_size:
                    raise RuntimeInstallerError(
                        f"运行时下载大小不匹配: expected={expected_size} actual={total}"
                    )
                if total == 0:
                    raise RuntimeInstallerError("运行时下载为空")
        except RuntimeInstallerError:
            raise
        except Exception as exc:
            raise RuntimeInstallerError(f"运行时下载失败: {exc}") from exc
