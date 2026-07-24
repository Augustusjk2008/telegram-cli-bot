"""安全的外部依赖源码令牌注册与只读读取。

语言服务器只会看到本机文件 URI。这个模块把 URI 解析、approved root
校验、短期令牌和文本读取集中到一个小的、内存内的边界，避免 provider
把绝对路径直接交给浏览器。
"""

from __future__ import annotations

import os
import secrets
import stat
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from bot.web.text_encoding import (
    DecodedText,
    UnsupportedTextEncoding,
    decode_text_bytes,
    decode_text_prefix_bytes,
)


DEFAULT_EXTERNAL_SOURCE_TTL_SECONDS = 5 * 60
DEFAULT_EXTERNAL_SOURCE_CAPACITY = 128
DEFAULT_EXTERNAL_SOURCE_MAX_BYTES = 4 * 1024 * 1024
MAX_EXTERNAL_SOURCE_HEAD_LINES = 2_000
_EXTERNAL_SOURCE_READ_BLOCK_SIZE = 4_096


class ExternalSourceError(ValueError):
    """Base error raised by the source registry."""

    status = 400
    code = "external_source_invalid"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = int(status)
        if code is not None:
            self.code = str(code)
        self.message = str(message)


class ExternalSourceDisabledError(ExternalSourceError):
    status = 404
    code = "external_sources_disabled"


class ExternalSourceUriError(ExternalSourceError):
    status = 400
    code = "unsupported_external_source_uri"


class ExternalSourcePolicyError(ExternalSourceError):
    status = 403
    code = "external_source_not_approved"


class ExternalSourceNotFoundError(ExternalSourceError):
    status = 404
    code = "external_source_not_found"


class ExternalSourceExpiredError(ExternalSourceNotFoundError):
    code = "external_source_expired"


class ExternalSourceTextError(ExternalSourceError):
    status = 415
    code = "external_source_not_text"


class ExternalSourceTooLargeError(ExternalSourceError):
    status = 413
    code = "external_source_too_large"


@dataclass(frozen=True, slots=True)
class ApprovedRoot:
    """A canonical dependency root and its browser-safe label."""

    path: Path
    label: str = "external"

    @classmethod
    def from_value(cls, value: Any, *, default_label: str = "external") -> "ApprovedRoot | None":
        raw_path: Any = value
        label = default_label
        if isinstance(value, ApprovedRoot):
            raw_path = value.path
            label = value.label or default_label
        if isinstance(value, Mapping):
            raw_path = value.get("path") or value.get("root") or value.get("directory")
            label = str(value.get("label") or value.get("display") or default_label).strip() or default_label
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if not value:
                return None
            raw_path = value[0]
            if len(value) > 1 and str(value[1] or "").strip():
                label = str(value[1]).strip()
        if raw_path is None:
            return None
        try:
            path = Path(raw_path).expanduser().resolve(strict=False)
        except (OSError, TypeError, ValueError):
            return None
        if not path.exists() or not path.is_dir():
            return None
        return cls(path=path, label=_safe_display_label(label))


@dataclass(slots=True)
class ExternalSourceRecord:
    """Internal source binding. ``path`` never leaves the registry."""

    source_id: str
    path: Path
    file_device: int
    file_inode: int
    display_path: str
    alias: str
    user_id: int
    workspace_root: Path
    provider_id: str
    approved_root: ApprovedRoot
    created_at: float
    expires_at: float
    last_access_at: float

    def public_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "display_path": self.display_path,
            "path": self.display_path,
            "provider": self.provider_id,
            "target_type": "external",
            "read_only": True,
            "expires_at": self.expires_at,
        }


# Short alias useful to callers that use the name from the API contract.
ExternalSource = ExternalSourceRecord


def _safe_display_label(value: str) -> str:
    text = str(value or "external").strip().replace("\\", "/")
    if text.startswith("/") or (len(text) >= 3 and text[1] == ":" and text[2] == "/"):
        return "external"
    text = "/".join(part for part in text.split("/") if part not in {"", ".", ".."})
    if text and len(text.split("/", 1)[0]) == 2 and text[1] == ":":
        return "external"
    return text[:80] or "external"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path_text = os.path.normcase(os.path.normpath(str(path)))
        root_text = os.path.normcase(os.path.normpath(str(root)))
        return os.path.commonpath([path_text, root_text]) == root_text
    except (OSError, ValueError):
        return False


def _file_uri_to_path(value: str) -> Path:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.lower() != "file":
        raise ExternalSourceUriError("仅支持 file:// 外部源码位置")
    if parsed.query or parsed.fragment:
        raise ExternalSourceUriError("外部源码 URI 不支持查询参数或片段")
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path = f"//{parsed.netloc}{path}"
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    if not path:
        raise ExternalSourceUriError("外部源码 URI 缺少文件路径")
    return Path(path)


def canonicalize_external_path(value: Path | str, *, require_file: bool = True) -> Path:
    """Resolve a local path or file URI and reject missing/non-file targets."""

    if isinstance(value, Path):
        candidate = value
    else:
        raw = str(value or "").strip()
        if not raw or "\x00" in raw:
            raise ExternalSourceError("外部源码路径不合法")
        parsed = urlparse(raw)
        if parsed.scheme:
            candidate = _file_uri_to_path(raw)
        else:
            candidate = Path(raw)
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise ExternalSourceNotFoundError("外部源码文件不存在") from exc
    if require_file and (not resolved.is_file() or resolved.is_dir()):
        raise ExternalSourcePolicyError("外部源码目标不是普通文件", status=403, code="external_source_not_file")
    return resolved


def canonicalize_approved_roots(
    roots: Iterable[ApprovedRoot | Path | str | Mapping[str, Any] | Sequence[Any]],
) -> tuple[ApprovedRoot, ...]:
    if roots is None:
        return ()
    result: list[ApprovedRoot] = []
    seen: set[str] = set()
    for value in roots:
        item = ApprovedRoot.from_value(value)
        if item is None:
            continue
        key = os.path.normcase(os.path.normpath(str(item.path)))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    result.sort(key=lambda item: len(str(item.path)), reverse=True)
    return tuple(result)


def _coerce_enabled(value: bool | None) -> bool:
    if value is not None:
        return bool(value)
    try:
        from bot import config

        return bool(getattr(config, "TCB_LSP_EXTERNAL_SOURCES_ENABLED", False))
    except Exception:
        return False


class ExternalSourceRegistry:
    """In-memory, scoped registry for read-only external source tokens."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        ttl_seconds: float = DEFAULT_EXTERNAL_SOURCE_TTL_SECONDS,
        max_per_user: int = DEFAULT_EXTERNAL_SOURCE_CAPACITY,
        capacity: int | None = None,
        max_source_bytes: int = DEFAULT_EXTERNAL_SOURCE_MAX_BYTES,
        max_bytes: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        configured_capacity = max_per_user if capacity is None else capacity
        self.max_per_user = max(1, int(configured_capacity))
        configured_bytes = max_source_bytes if max_bytes is None else max_bytes
        self.max_source_bytes = max(1, int(configured_bytes))
        self._clock = clock or time.monotonic
        self._items: dict[str, ExternalSourceRecord] = {}
        self._lock = RLock()

    @property
    def is_enabled(self) -> bool:
        return _coerce_enabled(self.enabled)

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def snapshot(self) -> tuple[ExternalSourceRecord, ...]:
        with self._lock:
            self._purge_expired()
            return tuple(self._items.values())

    def approved_roots(self, roots: Iterable[Any]) -> tuple[ApprovedRoot, ...]:
        return canonicalize_approved_roots(roots)

    def register(
        self,
        path: Path | str | None = None,
        *,
        uri: str | None = None,
        alias: str = "",
        user_id: int = 0,
        workspace_root: Path | str = "",
        provider_id: str = "",
        provider: str | None = None,
        approved_roots: Iterable[Any] = (),
        display_path: str | None = None,
        **kwargs: Any,
    ) -> ExternalSourceRecord:
        """Validate and issue a token for one provider-reported location."""

        if path is None:
            path = uri
        if path is None and kwargs.get("location") is not None:
            path = kwargs["location"]
        if not self.is_enabled:
            raise ExternalSourceDisabledError("外部依赖源码浏览已关闭")
        normalized_alias = str(alias or kwargs.get("bot_alias") or "").strip().lower()
        normalized_provider = str(provider_id or provider or kwargs.get("language_provider") or "").strip().lower()
        if not normalized_alias or not normalized_provider:
            raise ExternalSourcePolicyError("外部源码绑定缺少 Bot 或 provider", status=400, code="external_source_scope_invalid")
        try:
            normalized_user = int(user_id if user_id is not None else kwargs.get("user") or 0)
        except (TypeError, ValueError) as exc:
            raise ExternalSourcePolicyError("外部源码用户范围无效", status=400, code="external_source_scope_invalid") from exc
        try:
            workspace = Path(workspace_root).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            raise ExternalSourcePolicyError("工作区不存在", status=400, code="external_source_scope_invalid") from exc
        if not workspace.is_dir():
            raise ExternalSourcePolicyError("工作区不是目录", status=400, code="external_source_scope_invalid")

        target = canonicalize_external_path(path, require_file=True)
        roots = canonicalize_approved_roots(approved_roots)
        matching_root = next((root for root in roots if _is_within(target, root.path)), None)
        if matching_root is None:
            raise ExternalSourcePolicyError("外部源码不在 provider 批准目录内")

        descriptor, target_stat = self._open_approved_file(target, matching_root)
        try:
            file_device = int(target_stat.st_dev)
            file_inode = int(target_stat.st_ino)
        finally:
            os.close(descriptor)
        relative = target.relative_to(matching_root.path).as_posix()
        safe_display = _safe_display_label(display_path or f"{matching_root.label}/{relative}")
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            self._evict_for_capacity(normalized_user)
            token = self._new_source_id()
            record = ExternalSourceRecord(
                source_id=token,
                path=target,
                file_device=file_device,
                file_inode=file_inode,
                display_path=safe_display,
                alias=normalized_alias,
                user_id=normalized_user,
                workspace_root=workspace,
                provider_id=normalized_provider,
                approved_root=matching_root,
                created_at=now,
                expires_at=now + self.ttl_seconds,
                last_access_at=now,
            )
            self._items[token] = record
        return record

    register_source = register
    register_location = register
    issue = register

    def resolve(
        self,
        source_id: str,
        *,
        alias: str = "",
        user_id: int = 0,
        workspace_root: Path | str = "",
        provider_id: str | None = None,
        provider: str | None = None,
    ) -> ExternalSourceRecord:
        if not self.is_enabled:
            raise ExternalSourceDisabledError("外部依赖源码浏览已关闭")
        token = str(source_id or "").strip()
        with self._lock:
            record = self._items.get(token)
            if record is None:
                raise ExternalSourceNotFoundError("外部源码令牌无效或已过期")
            if record.expires_at <= self._clock():
                self._items.pop(token, None)
                raise ExternalSourceExpiredError("外部源码令牌已过期")
        normalized_alias = str(alias or "").strip().lower()
        try:
            normalized_user = int(user_id)
            workspace = Path(workspace_root).expanduser().resolve(strict=True)
        except (TypeError, ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
            raise ExternalSourceNotFoundError("外部源码绑定范围无效") from exc
        normalized_provider = str(provider_id or provider or "").strip().lower()
        if (
            record.alias != normalized_alias
            or record.user_id != normalized_user
            or record.workspace_root != workspace
            or (normalized_provider and record.provider_id != normalized_provider)
        ):
            raise ExternalSourceNotFoundError("外部源码令牌不属于当前范围")
        try:
            current = canonicalize_external_path(record.path, require_file=True)
        except ExternalSourceError:
            with self._lock:
                self._items.pop(token, None)
            raise
        if current != record.path or not _is_within(current, record.approved_root.path):
            with self._lock:
                self._items.pop(token, None)
            raise ExternalSourcePolicyError("外部源码路径已离开批准目录")
        with self._lock:
            record.last_access_at = self._clock()
        return record

    get = resolve
    resolve_source = resolve

    def read(
        self,
        source_id: str,
        *,
        alias: str = "",
        user_id: int = 0,
        workspace_root: Path | str = "",
        provider_id: str | None = None,
        provider: str | None = None,
        mode: str = "cat",
        lines: int = 0,
        encoding: str | None = None,
        requested_encoding: str | None = None,
    ) -> dict[str, object]:
        record = self.resolve(
            source_id,
            alias=alias,
            user_id=user_id,
            workspace_root=workspace_root,
            provider_id=provider_id,
            provider=provider,
        )
        descriptor: int | None = None
        try:
            descriptor, opened_stat = self._open_approved_file(
                record.path,
                record.approved_root,
                expected_device=record.file_device,
                expected_inode=record.file_inode,
            )
            if opened_stat.st_size > self.max_source_bytes:
                raise ExternalSourceTooLargeError("外部源码文件超过只读大小限制")
            requested = requested_encoding if requested_encoding is not None else encoding
            normalized_mode = str(mode or "cat").strip().lower()
            handle = os.fdopen(descriptor, "rb")
            descriptor = None
            with handle:
                if normalized_mode in {"head", "preview"}:
                    try:
                        line_limit = max(1, min(int(lines or 80), MAX_EXTERNAL_SOURCE_HEAD_LINES))
                    except (TypeError, ValueError) as exc:
                        raise ExternalSourceError("外部源码行数无效", status=400, code="external_source_invalid_lines") from exc
                    decoded = self._read_head_from_open_file(handle, line_limit, requested)
                    is_full = False
                elif normalized_mode in {"cat", "full"}:
                    content = handle.read(self.max_source_bytes + 1)
                    if len(content) > self.max_source_bytes:
                        raise ExternalSourceTooLargeError("外部源码文件超过只读大小限制")
                    decoded = decode_text_bytes(content, requested)
                    is_full = True
                    normalized_mode = "cat"
                else:
                    raise ExternalSourceError("外部源码读取模式无效", status=400, code="external_source_invalid_mode")
                final_stat = os.fstat(handle.fileno())
            if final_stat.st_size > self.max_source_bytes:
                raise ExternalSourceTooLargeError("外部源码文件超过只读大小限制")
        except UnsupportedTextEncoding as exc:
            raise ExternalSourceTextError("外部源码不是受支持的文本文件") from exc
        except (ExternalSourcePolicyError, ExternalSourceNotFoundError):
            self._discard_record(record)
            raise
        except OSError as exc:
            self._discard_record(record)
            raise ExternalSourceNotFoundError("外部源码文件不可读取") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

        return {
            "source_id": record.source_id,
            "target_type": "external",
            "path": record.display_path,
            "display_path": record.display_path,
            "provider": record.provider_id,
            "content": decoded.text,
            "mode": normalized_mode,
            "file_size_bytes": final_stat.st_size,
            "is_full_content": is_full,
            "encoding": decoded.encoding,
            "last_modified_ns": final_stat.st_mtime_ns,
            "read_only": True,
        }

    read_source = read
    read_registered_source = read

    def _open_approved_file(
        self,
        path: Path,
        approved_root: ApprovedRoot,
        *,
        expected_device: int | None = None,
        expected_inode: int | None = None,
    ) -> tuple[int, os.stat_result]:
        flags = os.O_RDONLY
        for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
            flags |= int(getattr(os, flag_name, 0))
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise ExternalSourceNotFoundError("外部源码文件不可读取") from exc
        except OSError as exc:
            raise ExternalSourcePolicyError("外部源码文件无法安全打开") from exc

        try:
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode):
                raise ExternalSourcePolicyError("外部源码目标不是普通文件", status=403, code="external_source_not_file")
            if (
                expected_device is not None
                and expected_inode is not None
                and (opened_stat.st_dev != expected_device or opened_stat.st_ino != expected_inode)
            ):
                raise ExternalSourcePolicyError("外部源码文件已被替换")
            current = canonicalize_external_path(path, require_file=True)
            if current != path or not _is_within(current, approved_root.path):
                raise ExternalSourcePolicyError("外部源码路径已离开批准目录")
            try:
                current_stat = current.stat()
            except OSError as exc:
                raise ExternalSourceNotFoundError("外部源码文件不可读取") from exc
            if not os.path.samestat(opened_stat, current_stat):
                raise ExternalSourcePolicyError("外部源码文件已被替换")
            return descriptor, opened_stat
        except BaseException:
            os.close(descriptor)
            raise

    def _read_head_from_open_file(
        self,
        handle: BinaryIO,
        line_limit: int,
        requested_encoding: str | None,
    ) -> DecodedText:
        if requested_encoding:
            consumed = self._read_until_line_limit(handle, line_limit)
            return decode_text_prefix_bytes(consumed, requested_encoding)

        prefix_limit = min(
            self.max_source_bytes,
            max(_EXTERNAL_SOURCE_READ_BLOCK_SIZE, line_limit * 256),
        )
        prefix = handle.read(prefix_limit)
        detected = decode_text_prefix_bytes(prefix)
        if prefix.count(b"\n") >= line_limit or len(prefix) < prefix_limit:
            return detected
        consumed = self._read_until_line_limit(handle, line_limit, initial=prefix)
        return decode_text_prefix_bytes(consumed, detected.encoding)

    def _read_until_line_limit(
        self,
        handle: BinaryIO,
        line_limit: int,
        *,
        initial: bytes = b"",
    ) -> bytes:
        chunks = [initial] if initial else []
        total = len(initial)
        newline_count = initial.count(b"\n")
        while newline_count < line_limit and total < self.max_source_bytes:
            chunk = handle.read(min(_EXTERNAL_SOURCE_READ_BLOCK_SIZE, self.max_source_bytes - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            newline_count += chunk.count(b"\n")
        return b"".join(chunks)

    def _discard_record(self, record: ExternalSourceRecord) -> None:
        with self._lock:
            if self._items.get(record.source_id) is record:
                self._items.pop(record.source_id, None)

    def _new_source_id(self) -> str:
        token = ""
        while not token or token in self._items:
            token = f"src_{secrets.token_urlsafe(24)}"
        return token

    def _purge_expired(self, now: float | None = None) -> None:
        current = self._clock() if now is None else now
        stale = [token for token, item in self._items.items() if item.expires_at <= current]
        for token in stale:
            self._items.pop(token, None)

    def _evict_for_capacity(self, user_id: int) -> None:
        scoped = [item for item in self._items.values() if item.user_id == user_id]
        overflow = len(scoped) - self.max_per_user + 1
        if overflow <= 0:
            return
        scoped.sort(key=lambda item: (item.last_access_at, item.created_at, item.source_id))
        for item in scoped[:overflow]:
            self._items.pop(item.source_id, None)


def source_record_public_dict(record: ExternalSourceRecord) -> dict[str, object]:
    """Return the only safe fields suitable for a navigation response."""

    return record.public_dict()


__all__ = [
    "ApprovedRoot",
    "ExternalSource",
    "ExternalSourceDisabledError",
    "ExternalSourceError",
    "ExternalSourceExpiredError",
    "ExternalSourceNotFoundError",
    "ExternalSourcePolicyError",
    "ExternalSourceRecord",
    "ExternalSourceRegistry",
    "ExternalSourceTextError",
    "ExternalSourceTooLargeError",
    "ExternalSourceUriError",
    "canonicalize_approved_roots",
    "canonicalize_external_path",
    "source_record_public_dict",
]
