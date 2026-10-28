from __future__ import annotations

import bz2
import gzip
import lzma
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator
from zipfile import BadZipFile, ZipFile

try:  # RAR listing/extraction is optional and still needs a native backend.
    import rarfile  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on the host installation.
    rarfile = None


DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_EXTRACT_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_TOOL_SECONDS = 120
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_RAR_MAGIC = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")
_SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _max_entries(config: dict[str, object] | None) -> int:
    return _clamp_int((config or {}).get("maxEntries"), DEFAULT_MAX_ENTRIES, 100, 10000)


def _max_extract_bytes(config: dict[str, object] | None) -> int:
    return _clamp_int(
        (config or {}).get("maxExtractBytes"),
        DEFAULT_MAX_EXTRACT_BYTES,
        1,
        DEFAULT_MAX_EXTRACT_BYTES,
    )


def _overwrite_existing(config: dict[str, object] | None) -> bool:
    return bool((config or {}).get("overwriteExisting", True))


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _safe_member_path(name: str) -> str:
    text = str(name or "").replace("\\", "/")
    if not text or "\x00" in text or any(ord(char) < 32 for char in text):
        raise RuntimeError("压缩包包含不安全路径")
    if text.startswith("/") or text.startswith("//") or _WINDOWS_DRIVE_RE.match(text):
        raise RuntimeError(f"压缩包包含不安全路径: {name}")

    parts: list[str] = []
    for part in text.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." or ":" in part:
            raise RuntimeError(f"压缩包包含不安全路径: {name}")
        parts.append(part)
    if not parts:
        return ""
    return "/".join(parts)


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    ordinal: int
    size: int
    compressed_size: int
    is_dir: bool = False


# Kept as a compatibility alias for code that imported the old ZIP-only name.
ZipMember = ArchiveEntry


def _append_unique(entries: list[ArchiveEntry], entry: ArchiveEntry, seen: set[str]) -> None:
    key = entry.path.casefold()
    if key in seen:
        raise RuntimeError(f"压缩包包含重复路径: {entry.path}")
    seen.add(key)
    entries.append(entry)


def _check_total_size(total: int, limit: int) -> None:
    if total > limit:
        raise RuntimeError(f"压缩内容超过限制: {total} > {limit} bytes")


def _zip_entries(content: bytes, max_extract_bytes: int) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    seen: set[str] = set()
    total = 0
    try:
        with ZipFile(BytesIO(content)) as archive:
            for ordinal, info in enumerate(archive.infolist()):
                member_path = _safe_member_path(info.filename)
                if not member_path:
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if stat.S_ISLNK(mode):
                    raise RuntimeError(f"压缩包不允许符号链接: {info.filename}")
                is_dir = info.is_dir() or info.filename.endswith(("/", "\\"))
                size = 0 if is_dir else max(0, int(info.file_size))
                total += size
                _check_total_size(total, max_extract_bytes)
                _append_unique(
                    entries,
                    ArchiveEntry(member_path, ordinal, size, max(0, int(info.compress_size)), is_dir),
                    seen,
                )
    except BadZipFile as exc:
        raise RuntimeError("ZIP 文件损坏或格式不支持") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"ZIP 文件读取失败: {exc}") from exc
    return entries


def _tar_entries(content: bytes, max_extract_bytes: int) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=BytesIO(content), mode="r:*") as archive:
            for ordinal, info in enumerate(archive.getmembers()):
                member_path = _safe_member_path(info.name)
                if not member_path:
                    continue
                if info.issym() or info.islnk() or info.isdev() or not (info.isdir() or info.isfile()):
                    raise RuntimeError(f"压缩包包含不支持的条目: {info.name}")
                is_dir = info.isdir()
                size = 0 if is_dir else max(0, int(info.size))
                total += size
                _check_total_size(total, max_extract_bytes)
                _append_unique(entries, ArchiveEntry(member_path, ordinal, size, 0, is_dir), seen)
    except tarfile.TarError as exc:
        raise RuntimeError("TAR 文件损坏或格式不支持") from exc
    except OSError as exc:
        raise RuntimeError(f"TAR 文件读取失败: {exc}") from exc
    return entries


def _is_tar_archive(content: bytes) -> bool:
    try:
        with tarfile.open(fileobj=BytesIO(content), mode="r:*") as archive:
            archive.getmembers()
        return True
    except (OSError, tarfile.TarError):
        return False


def _decompress_limited(content: bytes, kind: str, limit: int) -> bytes:
    stream: Any
    try:
        if kind == "gz":
            stream = gzip.GzipFile(fileobj=BytesIO(content), mode="rb")
        elif kind == "bz2":
            stream = bz2.BZ2File(BytesIO(content), mode="rb")
        else:
            stream = lzma.LZMAFile(BytesIO(content), mode="rb")
        with stream:
            data = stream.read(limit + 1)
    except (OSError, EOFError, ValueError) as exc:
        raise RuntimeError(f"{kind.upper()} 文件损坏或格式不支持") from exc
    if len(data) > limit:
        raise RuntimeError(f"压缩内容超过限制: {len(data)} > {limit} bytes")
    return data


def _single_file_name(path: str, kind: str) -> str:
    source = PurePosixPath(path)
    suffix = f".{kind}"
    name = source.name
    if name.casefold().endswith(suffix):
        name = name[: -len(suffix)] or "decompressed"
    return name


def _find_seven_zip() -> str:
    for candidate in ("7z", "7zz", "7za"):
        found = shutil.which(candidate)
        if found:
            return found
    for root_name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = os.environ.get(root_name)
        if not root:
            continue
        for filename in ("7z.exe", "7zz.exe", "7za.exe"):
            candidate = Path(root) / "7-Zip" / filename
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("RAR/7z 预览需要安装 7-Zip，或安装 rarfile 并配置 UnRAR")


@contextmanager
def _temporary_archive(path: str, content: bytes) -> Iterator[Path]:
    suffix = PurePosixPath(path).suffix or ".archive"
    with tempfile.TemporaryDirectory(prefix="orbit-archive-") as directory:
        archive_path = Path(directory) / f"source{suffix}"
        archive_path.write_bytes(content)
        yield archive_path


def _parse_seven_zip_listing(output: str, max_extract_bytes: int) -> list[ArchiveEntry]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current:
            records.append(current)
            current = {}

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        current[key.strip()] = value.strip()
    flush()

    entries: list[ArchiveEntry] = []
    seen: set[str] = set()
    total = 0
    for record in records:
        raw_path = record.get("Path")
        if not raw_path or ("Size" not in record and record.get("Folder") not in {"+", "-"}):
            continue
        member_path = _safe_member_path(raw_path)
        if not member_path:
            continue
        is_dir = record.get("Folder") == "+"
        try:
            size = 0 if is_dir else max(0, int(record.get("Size") or 0))
            compressed_size = max(0, int(record.get("Packed Size") or 0))
        except ValueError as exc:
            raise RuntimeError(f"7-Zip 返回了无效的条目大小: {raw_path}") from exc
        total += size
        _check_total_size(total, max_extract_bytes)
        _append_unique(entries, ArchiveEntry(member_path, len(entries), size, compressed_size, is_dir), seen)
    if not entries:
        raise RuntimeError("无法读取 RAR/7z 文件目录")
    return entries


def _seven_zip_entries(path: str, content: bytes, max_extract_bytes: int) -> list[ArchiveEntry]:
    tool = _find_seven_zip()
    with _temporary_archive(path, content) as archive_path:
        completed = subprocess.run(
            [tool, "l", "-slt", "-y", str(archive_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MAX_ARCHIVE_TOOL_SECONDS,
            check=False,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"7-Zip 无法读取压缩包{': ' + detail if detail else ''}")
    return _parse_seven_zip_listing(completed.stdout, max_extract_bytes)


def _rarfile_entries(content: bytes, max_extract_bytes: int) -> list[ArchiveEntry]:
    if rarfile is None:
        raise RuntimeError("Python rarfile 未安装")
    entries: list[ArchiveEntry] = []
    seen: set[str] = set()
    total = 0
    with rarfile.RarFile(BytesIO(content)) as archive:
        for ordinal, info in enumerate(archive.infolist()):
            member_path = _safe_member_path(info.filename)
            if not member_path:
                continue
            is_dir = bool(info.isdir())
            size = 0 if is_dir else max(0, int(info.file_size))
            total += size
            _check_total_size(total, max_extract_bytes)
            _append_unique(
                entries,
                ArchiveEntry(member_path, ordinal, size, max(0, int(info.compress_size)), is_dir),
                seen,
            )
    return entries


def _rar_entries(path: str, content: bytes, max_extract_bytes: int) -> list[ArchiveEntry]:
    errors: list[str] = []
    if rarfile is not None:
        try:
            return _rarfile_entries(content, max_extract_bytes)
        except Exception as exc:
            errors.append(str(exc))
    try:
        return _seven_zip_entries(path, content, max_extract_bytes)
    except Exception as exc:
        errors.append(str(exc))
    detail = next((item for item in errors if item), "未知错误")
    raise RuntimeError(f"RAR 文件暂不可用: {detail}")


def _load_entries(path: str, content: bytes, config: dict[str, object] | None = None) -> tuple[str, list[ArchiveEntry]]:
    suffix = PurePosixPath(path).name.casefold()
    max_extract_bytes = _max_extract_bytes(config)
    if suffix.endswith(".zip") or content.startswith(b"PK\x03\x04") or content.startswith(b"PK\x05\x06"):
        return "zip", _zip_entries(content, max_extract_bytes)
    if suffix.endswith(".rar") or content.startswith(_RAR_MAGIC):
        return "rar", _rar_entries(path, content, max_extract_bytes)
    if suffix.endswith(".7z") or content.startswith(_SEVEN_ZIP_MAGIC):
        return "7z", _seven_zip_entries(path, content, max_extract_bytes)

    tar_hint = suffix.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2", ".tar.xz", ".txz"))
    if tar_hint:
        return "tar", _tar_entries(content, max_extract_bytes)
    if suffix.endswith(".gz"):
        if _is_tar_archive(content):
            return "tar", _tar_entries(content, max_extract_bytes)
        data = _decompress_limited(content, "gz", max_extract_bytes)
        return "gz", [ArchiveEntry(_single_file_name(path, "gz"), 0, len(data), 0)]
    if suffix.endswith(".bz2"):
        if _is_tar_archive(content):
            return "tar", _tar_entries(content, max_extract_bytes)
        data = _decompress_limited(content, "bz2", max_extract_bytes)
        return "bz2", [ArchiveEntry(_single_file_name(path, "bz2"), 0, len(data), 0)]
    if suffix.endswith(".xz"):
        if _is_tar_archive(content):
            return "tar", _tar_entries(content, max_extract_bytes)
        data = _decompress_limited(content, "xz", max_extract_bytes)
        return "xz", [ArchiveEntry(_single_file_name(path, "xz"), 0, len(data), 0)]

    for kind in ("tar", "zip"):
        try:
            return (kind, _tar_entries(content, max_extract_bytes)) if kind == "tar" else (kind, _zip_entries(content, max_extract_bytes))
        except RuntimeError:
            continue
    raise RuntimeError("文件不是受支持的压缩格式")


def _folder_node(path: str, label: str) -> dict[str, object]:
    return {
        "id": f"dir:{path}",
        "label": label,
        "kind": "folder",
        "hasChildren": True,
        "expandable": True,
        "children": [],
    }


def _file_node(member: ArchiveEntry, archive_format: str) -> dict[str, object]:
    current_path = PurePosixPath(member.path)
    parent = str(current_path.parent)
    badges = [{"text": _size_label(member.size), "tone": "info"}]
    if member.compressed_size:
        badges.append({"text": f"{archive_format} {_size_label(member.compressed_size)}"})
    else:
        badges.append({"text": archive_format})
    return {
        "id": f"file:{member.ordinal}:{member.path}",
        "label": current_path.name,
        "kind": "file",
        "secondaryText": "" if parent == "." else parent,
        "badges": badges,
        "payload": {
            "path": member.path,
            "size": member.size,
            "compressedSize": member.compressed_size,
            "archiveFormat": archive_format,
        },
    }


def _sorted_nodes(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(nodes, key=lambda item: (item.get("kind") != "folder", str(item.get("label") or "").lower()))


def _ensure_folder(children: dict[str, list[str | ArchiveEntry]], folder_path: str) -> None:
    if not folder_path or folder_path == "." or folder_path in children:
        return
    parent = str(PurePosixPath(folder_path).parent)
    parent_key = "" if parent == "." else parent
    _ensure_folder(children, parent_key)
    children.setdefault(parent_key, []).append(folder_path)
    children[folder_path] = []


def _build_tree(entries: list[ArchiveEntry]) -> dict[str, list[str | ArchiveEntry]]:
    children: dict[str, list[str | ArchiveEntry]] = {"": []}
    for entry in entries:
        if entry.is_dir:
            _ensure_folder(children, entry.path)
            continue
        member_path = PurePosixPath(entry.path)
        for folder in reversed(member_path.parents):
            folder_path = str(folder)
            if folder_path != ".":
                _ensure_folder(children, folder_path)
        parent = str(member_path.parent)
        children.setdefault("" if parent == "." else parent, []).append(entry)
    return children


@dataclass(frozen=True)
class ArchiveIndex:
    path: str
    archive_format: str
    children: dict[str, list[str | ArchiveEntry]]
    stats_text: str
    entries: tuple[ArchiveEntry, ...]
    truncated: bool = False

    def get_nodes(self, node_id: str | None = None) -> list[dict[str, object]]:
        folder_path = ""
        if node_id is not None:
            if not node_id.startswith("dir:") or not node_id[4:] or node_id[4:] not in self.children:
                raise RuntimeError("压缩包目录节点不存在")
            folder_path = node_id[4:]
        return _sorted_nodes([
            _folder_node(item, PurePosixPath(item).name) if isinstance(item, str) else _file_node(item, self.archive_format)
            for item in self.children[folder_path]
        ])

    def _actions(self) -> list[dict[str, object]]:
        return [{
            "id": "extract-here",
            "label": "解压到所在文件夹",
            "target": "plugin",
            "location": "toolbar",
            "variant": "primary",
            "confirm": {
                "title": "解压压缩包",
                "message": "将压缩包内容解压到当前文件所在文件夹，已有同名文件会按插件设置处理。",
            },
        }]

    def summary(self) -> dict[str, object]:
        return {
            "path": self.path,
            "roots": self.get_nodes(),
            "statsText": self.stats_text,
            "searchable": False,
            "emptySearchText": "压缩包为空",
            "actions": self._actions(),
        }

    def snapshot(self) -> dict[str, object]:
        payload = self.summary()
        pending = list(payload["roots"])
        while pending:
            node = pending.pop()
            if node.get("kind") == "folder":
                nodes = self.get_nodes(str(node["id"]))
                node["children"] = nodes
                pending.extend(nodes)
        return payload


# Compatibility alias for integrations that still use the old ZIP-only symbol.
ZipIndex = ArchiveIndex


def build_archive_index(path: str, content: bytes, config: dict[str, object] | None = None) -> ArchiveIndex:
    archive_format, entries = _load_entries(path, content, config)
    limit = _max_entries(config)
    truncated = len(entries) > limit
    visible_entries = entries[:limit]
    children = _build_tree(visible_entries)
    file_count = sum(not entry.is_dir for entry in visible_entries)
    folder_count = len(children) - 1
    stats_text = f"{file_count} 文件 · {folder_count} 文件夹 · {archive_format.upper()}"
    if truncated:
        stats_text += f" · 仅预览前 {limit} 项"
    return ArchiveIndex(path, archive_format, children, stats_text, tuple(visible_entries), truncated)


def build_zip_index(path: str, content: bytes, config: dict[str, object] | None = None) -> ArchiveIndex:
    return build_archive_index(path, content, config)


def parse_zip_tree(path: str, content: bytes, config: dict[str, object] | None = None) -> dict[str, object]:
    return build_archive_index(path, content, config).snapshot()


def _read_stream_limited(stream: Any, limit: int) -> bytes:
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"压缩内容超过限制: {len(data)} > {limit} bytes")
    return data


def _output_path(archive_path: str, member_path: str) -> str:
    parent = str(PurePosixPath(archive_path).parent)
    output = member_path if parent == "." else f"{parent}/{member_path}"
    if output.casefold() == archive_path.casefold():
        raise RuntimeError(f"解压目标不能覆盖压缩包: {member_path}")
    return output


def _extract_zip(
    archive_path: str,
    content: bytes,
    entries: list[ArchiveEntry],
    *,
    max_extract_bytes: int,
    write_bytes: Callable[..., dict[str, Any]],
    make_directory: Callable[..., dict[str, Any]],
    overwrite: bool,
) -> tuple[int, int]:
    files = 0
    total = 0
    with ZipFile(BytesIO(content)) as archive:
        infos = archive.infolist()
        for entry in entries:
            target = _output_path(archive_path, entry.path)
            if entry.is_dir:
                make_directory(target, error_message="创建解压目录失败")
                continue
            info = infos[entry.ordinal]
            with archive.open(info) as source:
                data = _read_stream_limited(source, max_extract_bytes - total)
            total += len(data)
            _check_total_size(total, max_extract_bytes)
            write_bytes(target, data, overwrite=overwrite, error_message="写入解压文件失败")
            files += 1
    return files, total


def _extract_tar(
    archive_path: str,
    content: bytes,
    entries: list[ArchiveEntry],
    *,
    max_extract_bytes: int,
    write_bytes: Callable[..., dict[str, Any]],
    make_directory: Callable[..., dict[str, Any]],
    overwrite: bool,
) -> tuple[int, int]:
    files = 0
    total = 0
    with tarfile.open(fileobj=BytesIO(content), mode="r:*") as archive:
        members = archive.getmembers()
        for entry in entries:
            target = _output_path(archive_path, entry.path)
            member = members[entry.ordinal]
            if entry.is_dir:
                make_directory(target, error_message="创建解压目录失败")
                continue
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"无法读取压缩包条目: {entry.path}")
            with source:
                data = _read_stream_limited(source, max_extract_bytes - total)
            total += len(data)
            _check_total_size(total, max_extract_bytes)
            write_bytes(target, data, overwrite=overwrite, error_message="写入解压文件失败")
            files += 1
    return files, total


def _extract_single(
    archive_path: str,
    content: bytes,
    archive_format: str,
    *,
    max_extract_bytes: int,
    write_bytes: Callable[..., dict[str, Any]],
    overwrite: bool,
) -> tuple[int, int]:
    data = _decompress_limited(content, archive_format, max_extract_bytes)
    target = _output_path(archive_path, _single_file_name(archive_path, archive_format))
    write_bytes(target, data, overwrite=overwrite, error_message="写入解压文件失败")
    return 1, len(data)


def _extract_rar_with_rarfile(
    archive_path: str,
    content: bytes,
    entries: list[ArchiveEntry],
    *,
    max_extract_bytes: int,
    write_bytes: Callable[..., dict[str, Any]],
    make_directory: Callable[..., dict[str, Any]],
    overwrite: bool,
) -> tuple[int, int]:
    if rarfile is None:
        raise RuntimeError("Python rarfile 未安装")
    files = 0
    total = 0
    with rarfile.RarFile(BytesIO(content)) as archive:
        infos = archive.infolist()
        for entry in entries:
            target = _output_path(archive_path, entry.path)
            info = infos[entry.ordinal]
            if entry.is_dir:
                make_directory(target, error_message="创建解压目录失败")
                continue
            with archive.open(info) as source:
                data = _read_stream_limited(source, max_extract_bytes - total)
            total += len(data)
            _check_total_size(total, max_extract_bytes)
            write_bytes(target, data, overwrite=overwrite, error_message="写入解压文件失败")
            files += 1
    return files, total


def _extract_with_seven_zip(
    archive_path: str,
    content: bytes,
    entries: list[ArchiveEntry],
    *,
    max_extract_bytes: int,
    write_bytes: Callable[..., dict[str, Any]],
    make_directory: Callable[..., dict[str, Any]],
    overwrite: bool,
) -> tuple[int, int]:
    tool = _find_seven_zip()
    with _temporary_archive(archive_path, content) as source_archive:
        with tempfile.TemporaryDirectory(prefix="orbit-archive-extract-") as directory:
            output_root = Path(directory).resolve()
            completed = subprocess.run(
                [tool, "x", "-y", f"-o{output_root}", str(source_archive)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=MAX_ARCHIVE_TOOL_SECONDS,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"7-Zip 无法解压压缩包{': ' + detail if detail else ''}")

            files = 0
            total = 0
            for entry in entries:
                target = _output_path(archive_path, entry.path)
                local_path = (output_root / Path(*entry.path.split("/"))).resolve()
                if output_root != local_path and output_root not in local_path.parents:
                    raise RuntimeError(f"压缩包包含不安全路径: {entry.path}")
                if entry.is_dir:
                    make_directory(target, error_message="创建解压目录失败")
                    continue
                if local_path.is_symlink() or not local_path.is_file():
                    raise RuntimeError(f"7-Zip 未生成预期文件: {entry.path}")
                with local_path.open("rb") as source:
                    data = _read_stream_limited(source, max_extract_bytes - total)
                total += len(data)
                _check_total_size(total, max_extract_bytes)
                write_bytes(target, data, overwrite=overwrite, error_message="写入解压文件失败")
                files += 1
            return files, total


def extract_archive(
    path: str,
    content: bytes,
    config: dict[str, object] | None = None,
    *,
    write_bytes: Callable[..., dict[str, Any]],
    make_directory: Callable[..., dict[str, Any]],
) -> tuple[int, int, str]:
    archive_format, entries = _load_entries(path, content, config)
    max_extract_bytes = _max_extract_bytes(config)
    overwrite = _overwrite_existing(config)
    max_entries = _max_entries(config)
    if len(entries) > max_entries:
        raise RuntimeError(f"压缩包条目超过解压限制: {len(entries)} > {max_entries}")
    if archive_format == "zip":
        files, total = _extract_zip(
            path,
            content,
            entries,
            max_extract_bytes=max_extract_bytes,
            write_bytes=write_bytes,
            make_directory=make_directory,
            overwrite=overwrite,
        )
    elif archive_format == "tar":
        files, total = _extract_tar(
            path,
            content,
            entries,
            max_extract_bytes=max_extract_bytes,
            write_bytes=write_bytes,
            make_directory=make_directory,
            overwrite=overwrite,
        )
    elif archive_format in {"gz", "bz2", "xz"}:
        files, total = _extract_single(
            path,
            content,
            archive_format,
            max_extract_bytes=max_extract_bytes,
            write_bytes=write_bytes,
            overwrite=overwrite,
        )
    elif archive_format == "rar":
        try:
            files, total = _extract_rar_with_rarfile(
                path,
                content,
                entries,
                max_extract_bytes=max_extract_bytes,
                write_bytes=write_bytes,
                make_directory=make_directory,
                overwrite=overwrite,
            )
        except Exception as first_error:
            try:
                files, total = _extract_with_seven_zip(
                    path,
                    content,
                    entries,
                    max_extract_bytes=max_extract_bytes,
                    write_bytes=write_bytes,
                    make_directory=make_directory,
                    overwrite=overwrite,
                )
            except Exception as second_error:
                raise RuntimeError(f"RAR 文件暂不可用: {second_error}") from first_error
    elif archive_format == "7z":
        files, total = _extract_with_seven_zip(
            path,
            content,
            entries,
            max_extract_bytes=max_extract_bytes,
            write_bytes=write_bytes,
            make_directory=make_directory,
            overwrite=overwrite,
        )
    else:  # pragma: no cover - _load_entries exhaustively chooses a format.
        raise RuntimeError(f"不支持的压缩格式: {archive_format}")
    return files, total, archive_format
