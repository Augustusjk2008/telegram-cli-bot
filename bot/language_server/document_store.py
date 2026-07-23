"""隔离语言服务器运行时的未保存文档快照。"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_DOCUMENT_BYTES = 512 * 1024
MAX_BATCH_DOCUMENTS = 64
MAX_BATCH_BYTES = 2 * 1024 * 1024


class LanguageDocumentError(ValueError):
    """客户端提交的文档快照不符合语言服务契约。"""


class LanguageDocumentLimitError(LanguageDocumentError):
    """文档或批次超过语言服务同步预算。"""


def normalize_document_path(value: object) -> str:
    """Normalize browser paths so one workspace file has one snapshot key."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    normalized = posixpath.normpath(raw)
    return "" if normalized == "." else normalized


@dataclass(frozen=True, slots=True)
class LanguageDocumentRuntimeKey:
    bot_alias: str
    user_id: int
    workspace_root: Path
    provider_id: str

    @classmethod
    def from_value(cls, value: Any) -> "LanguageDocumentRuntimeKey":
        if isinstance(value, cls):
            return value
        try:
            values = [getattr(value, name, None) for name in ("bot_alias", "user_id", "workspace_root", "provider_id")]
            if any(item is None for item in values):
                values = list(value[:4])
            bot_alias, user_id, workspace_root, provider_id = values
            normalized = cls(
                str(bot_alias or "").strip().lower(),
                int(user_id),
                Path(workspace_root).expanduser().resolve(),
                str(provider_id or "").strip().lower(),
            )
        except (IndexError, KeyError, TypeError, ValueError, OSError) as exc:
            raise LanguageDocumentError("语言服务运行时隔离键无效") from exc
        if not normalized.bot_alias or not normalized.provider_id:
            raise LanguageDocumentError("语言服务运行时隔离键无效")
        return normalized


@dataclass(frozen=True, slots=True)
class LanguageDocument:
    path: str
    language_id: str
    version: int
    content: str
    source_id: str = ""

    @property
    def document_id(self) -> str:
        return self.path or self.source_id

    def to_dict(self, *, include_content: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "path": self.path,
            "languageId": self.language_id,
            "version": self.version,
        }
        if self.source_id:
            result["sourceId"] = self.source_id
        if include_content:
            result["content"] = self.content
        return result

    @classmethod
    def from_value(cls, value: Any) -> "LanguageDocument":
        if isinstance(value, cls):
            document = cls(
                normalize_document_path(value.path),
                str(value.language_id or "").strip().lower(),
                int(value.version),
                value.content,
                str(value.source_id or "").strip(),
            )
        elif isinstance(value, Mapping):
            content = value.get("content")
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise LanguageDocumentError("文档内容必须是文本")
            try:
                version = int(value.get("version", 0))
            except (TypeError, ValueError) as exc:
                raise LanguageDocumentError("文档版本无效") from exc
            document = cls(
                normalize_document_path(value.get("path")),
                str(value.get("languageId") or value.get("language_id") or "").strip().lower(),
                version,
                content,
                str(value.get("sourceId") or value.get("source_id") or "").strip(),
            )
        else:
            raise LanguageDocumentError("文档快照格式无效")
        if not isinstance(document.content, str):
            raise LanguageDocumentError("文档内容必须是文本")
        if document.version < 0:
            raise LanguageDocumentError("文档版本不能为负数")
        if not document.document_id:
            raise LanguageDocumentError("文档缺少路径")
        if not document.language_id:
            raise LanguageDocumentError("文档缺少语言标识")
        return document


@dataclass(frozen=True, slots=True)
class DocumentSyncRejection:
    path: str
    version: int
    current_version: int | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"path": self.path, "version": self.version, "reason": self.reason}
        if self.current_version is not None:
            result["currentVersion"] = self.current_version
        return result


@dataclass(frozen=True, slots=True)
class DocumentSyncResult:
    accepted: tuple[LanguageDocument, ...] = ()
    unchanged: tuple[LanguageDocument, ...] = ()
    rejected: tuple[DocumentSyncRejection, ...] = ()

    @property
    def synced(self) -> tuple[LanguageDocument, ...]:
        return self.accepted

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        return {
            "accepted": [item.to_dict(include_content=include_content) for item in self.accepted],
            "unchanged": [item.to_dict(include_content=include_content) for item in self.unchanged],
            "rejected": [item.to_dict() for item in self.rejected],
            "acceptedCount": self.accepted_count,
            "rejectedCount": self.rejected_count,
        }

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]


@dataclass(frozen=True, slots=True)
class DocumentCloseResult:
    closed: tuple[LanguageDocument, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def closed_count(self) -> int:
        return len(self.closed)

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        return {
            "closed": [item.to_dict(include_content=include_content) for item in self.closed],
            "missing": list(self.missing),
            "closedCount": self.closed_count,
        }

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]


class LanguageDocumentStore:
    def __init__(
        self,
        *,
        max_document_bytes: int = MAX_DOCUMENT_BYTES,
        max_batch_documents: int = MAX_BATCH_DOCUMENTS,
        max_batch_bytes: int = MAX_BATCH_BYTES,
    ) -> None:
        self.max_document_bytes = max(1, int(max_document_bytes))
        self.max_batch_documents = max(1, int(max_batch_documents))
        self.max_batch_bytes = max(self.max_document_bytes, int(max_batch_bytes))
        self._documents: dict[LanguageDocumentRuntimeKey, dict[str, LanguageDocument]] = {}
        from threading import RLock
        self._lock = RLock()

    def validate_documents(
        self,
        documents: Sequence[LanguageDocument | Mapping[str, Any]],
    ) -> tuple[LanguageDocument, ...]:
        if isinstance(documents, (str, bytes)) or not isinstance(documents, Sequence):
            raise LanguageDocumentError("文档同步批次格式无效")
        if len(documents) > self.max_batch_documents:
            raise LanguageDocumentLimitError("文档同步批次过大")
        parsed: list[LanguageDocument] = []
        batch_bytes = 0
        for value in documents:
            document = LanguageDocument.from_value(value)
            size = len(document.content.encode("utf-8"))
            if size > self.max_document_bytes:
                raise LanguageDocumentLimitError("单个文档超过同步大小限制")
            batch_bytes += size
            if batch_bytes > self.max_batch_bytes:
                raise LanguageDocumentLimitError("文档同步批次超过大小限制")
            parsed.append(document)
        return tuple(parsed)

    def sync_documents(self, runtime_key: Any, documents: Sequence[LanguageDocument | Mapping[str, Any]]) -> DocumentSyncResult:
        key = LanguageDocumentRuntimeKey.from_value(runtime_key)
        parsed = self.validate_documents(documents)
        accepted: list[LanguageDocument] = []
        unchanged: list[LanguageDocument] = []
        rejected: list[DocumentSyncRejection] = []
        with self._lock:
            bucket = self._documents.setdefault(key, {})
            for document in parsed:
                current = bucket.get(document.document_id)
                if current is None:
                    bucket[document.document_id] = document
                    accepted.append(document)
                elif document.version < current.version or (
                    document.version == current.version and document.content != current.content
                ):
                    rejected.append(DocumentSyncRejection(document.document_id, document.version, current.version, "stale_version"))
                elif document.version == current.version:
                    unchanged.append(current)
                else:
                    bucket[document.document_id] = document
                    accepted.append(document)
        return DocumentSyncResult(tuple(accepted), tuple(unchanged), tuple(rejected))

    sync = sync_documents

    def close_documents(self, runtime_key: Any, documents: Sequence[LanguageDocument | Mapping[str, Any] | str]) -> DocumentCloseResult:
        key = LanguageDocumentRuntimeKey.from_value(runtime_key)
        if isinstance(documents, (str, bytes)):
            values: list[Any] = [documents]
        else:
            values = list(documents)
        if len(values) > self.max_batch_documents:
            raise LanguageDocumentLimitError("文档关闭批次过大")
        identifiers: list[str] = []
        for value in values:
            if isinstance(value, str):
                identifier = normalize_document_path(value)
            elif isinstance(value, LanguageDocument):
                identifier = value.document_id
            elif isinstance(value, Mapping):
                identifier = normalize_document_path(value.get("path"))
                if not identifier:
                    identifier = str(value.get("sourceId") or value.get("source_id") or "").strip()
            else:
                raise LanguageDocumentError("文档关闭项格式无效")
            if not identifier:
                raise LanguageDocumentError("文档关闭项缺少路径")
            identifiers.append(identifier)
        closed: list[LanguageDocument] = []
        missing: list[str] = []
        with self._lock:
            bucket = self._documents.get(key)
            for identifier in identifiers:
                document = bucket.pop(identifier, None) if bucket is not None else None
                if document is None:
                    missing.append(identifier)
                else:
                    closed.append(document)
            if bucket is not None and not bucket:
                self._documents.pop(key, None)
        return DocumentCloseResult(tuple(closed), tuple(missing))

    close = close_documents

    def snapshot(self, runtime_key: Any, *, paths: Sequence[str] | None = None) -> tuple[LanguageDocument, ...]:
        key = LanguageDocumentRuntimeKey.from_value(runtime_key)
        with self._lock:
            bucket = self._documents.get(key, {})
            if paths is None:
                return tuple(bucket.values())
            wanted = {normalize_document_path(path) for path in paths}
            return tuple(document for identifier, document in bucket.items() if identifier in wanted)

    def get(self, runtime_key: Any, path: str) -> LanguageDocument | None:
        key = LanguageDocumentRuntimeKey.from_value(runtime_key)
        with self._lock:
            return self._documents.get(key, {}).get(normalize_document_path(path))

    def clear_runtime(self, runtime_key: Any) -> tuple[LanguageDocument, ...]:
        key = LanguageDocumentRuntimeKey.from_value(runtime_key)
        with self._lock:
            return tuple(self._documents.pop(key, {}).values())

    def clear(self) -> None:
        with self._lock:
            self._documents.clear()

    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {
                "runtime_count": len(self._documents),
                "document_count": sum(len(bucket) for bucket in self._documents.values()),
            }


def parse_text_document_sync_capability(value: Any) -> tuple[bool, int]:
    open_close = True
    change_kind = 1
    if isinstance(value, Mapping):
        if "openClose" in value:
            open_close = bool(value.get("openClose"))
        value = value.get("change")
    try:
        change_kind = int(value) if value is not None else change_kind
    except (TypeError, ValueError):
        change_kind = 1
    return open_close, max(0, min(2, change_kind))


def build_content_change(previous: str, current: str, *, change_kind: int, encoding: str) -> dict[str, object]:
    if change_kind != 2:
        return {"text": current}
    prefix = 0
    while prefix < min(len(previous), len(current)) and previous[prefix] == current[prefix]:
        prefix += 1
    previous_end = len(previous)
    current_end = len(current)
    while previous_end > prefix and current_end > prefix and previous[previous_end - 1] == current[current_end - 1]:
        previous_end -= 1
        current_end -= 1
    start = _offset_to_lsp_position(previous, prefix, encoding)
    end = _offset_to_lsp_position(previous, previous_end, encoding)
    return {
        "range": {"start": start, "end": end},
        "rangeLength": _text_units(previous[prefix:previous_end], encoding),
        "text": current[prefix:current_end],
    }


def _offset_to_lsp_position(content: str, offset: int, encoding: str) -> dict[str, int]:
    line = content.count("\n", 0, offset)
    line_start = content.rfind("\n", 0, offset) + 1
    return {"line": line, "character": _text_units(content[line_start:offset], encoding)}


def _text_units(value: str, encoding: str) -> int:
    return len(value.encode("utf-8")) if encoding == "utf-8" else len(value.encode("utf-16-le")) // 2
