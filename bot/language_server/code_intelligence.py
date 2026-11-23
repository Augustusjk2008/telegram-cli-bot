"""语言服务器代码智能查询：能力协商、结果归一化与服务端推送状态。

导航以外的编辑器能力（悬停、引用、文档符号、语义标记、补全、诊断）共用这里的
实现；各 provider 只提供文档归属判断与位置归一化。
"""

from __future__ import annotations

import asyncio
import os
import re
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname


CODE_INTELLIGENCE_KINDS = (
    "hover",
    "references",
    "documentSymbols",
    "semanticTokens",
    "completion",
    "diagnostics",
)
POSITION_KINDS = frozenset({"hover", "references", "completion"})
_KIND_BY_LOWER = {kind.lower(): kind for kind in CODE_INTELLIGENCE_KINDS}

INDEXING_MESSAGE = "仍在索引"

MAX_HOVER_CHARS = 20_000
MAX_REFERENCE_ITEMS = 500
MAX_REFERENCE_EXTERNAL_FILES = 32
MAX_REFERENCE_PREVIEW_CHARS = 200
MAX_SYMBOL_NODES = 5_000
MAX_SYMBOL_DEPTH = 64
MAX_SEMANTIC_TOKENS = 50_000
MAX_COMPLETION_ITEMS = 200
MAX_COMPLETION_DOCUMENTATION_CHARS = 2_000
MAX_DIAGNOSTIC_MESSAGE_CHARS = 2_000
MAX_DIAGNOSTICS_PER_DOCUMENT = 500
# Once a document's messages exceed this many characters in total, the remaining
# ones are stored shortened so one noisy file cannot hold megabytes.
_DIAGNOSTIC_MESSAGE_BUDGET_CHARS = 64_000
_SHORT_DIAGNOSTIC_MESSAGE_CHARS = 200
MAX_PUSHED_DOCUMENTS = 200
MAX_INACTIVE_REGIONS_PER_DOCUMENT = 2_000
MAX_DIAGNOSTICS_WAIT_MS = 5_000
_MAX_LABEL_CHARS = 500
_MAX_INSERT_TEXT_CHARS = 10_000
_DIAGNOSTICS_RECHECK_SECONDS = 0.25

_SYMBOL_KINDS = (
    "file",
    "module",
    "namespace",
    "package",
    "class",
    "method",
    "property",
    "field",
    "constructor",
    "enum",
    "interface",
    "function",
    "variable",
    "constant",
    "string",
    "number",
    "boolean",
    "array",
    "object",
    "key",
    "null",
    "enumMember",
    "struct",
    "event",
    "operator",
    "typeParameter",
)
_COMPLETION_KINDS = (
    "text",
    "method",
    "function",
    "constructor",
    "field",
    "variable",
    "class",
    "interface",
    "module",
    "property",
    "unit",
    "value",
    "enum",
    "keyword",
    "snippet",
    "color",
    "file",
    "reference",
    "folder",
    "enumMember",
    "constant",
    "struct",
    "event",
    "operator",
    "typeParameter",
)
_DIAGNOSTIC_SEVERITIES = {1: "error", 2: "warning", 3: "info", 4: "hint"}
_SEMANTIC_TOKEN_TYPES = (
    "namespace",
    "type",
    "class",
    "enum",
    "interface",
    "struct",
    "typeParameter",
    "parameter",
    "variable",
    "property",
    "enumMember",
    "event",
    "function",
    "method",
    "macro",
    "keyword",
    "modifier",
    "comment",
    "string",
    "number",
    "regexp",
    "operator",
    "decorator",
)
_SEMANTIC_TOKEN_MODIFIERS = (
    "declaration",
    "definition",
    "readonly",
    "static",
    "deprecated",
    "abstract",
    "async",
    "modification",
    "documentation",
    "defaultLibrary",
)
_EXTERNAL_DEPENDENCY_PARTS = frozenset(
    {".venv", "venv", "site-packages", "dist-packages", "node_modules", ".yarn", ".pnp", ".pnpm"}
)
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
# Characters ``str.splitlines`` treats as line ends but LSP and the editor do not.
_NON_LSP_LINE_BREAK = re.compile("[\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")
_WORD_PREFIX = re.compile(r"[\w$]+\Z")
_SNIPPET_PLACEHOLDER = re.compile(r"\$\{\d+:((?:\\.|[^}\\])*)\}")
_SNIPPET_CHOICE = re.compile(r"\$\{\d+\|((?:\\.|[^,|\\])*)(?:\\.|[^|\\])*\|\}")
_SNIPPET_TABSTOP = re.compile(r"\$(?:\d+|\{\d+\})")
_SNIPPET_ESCAPE = re.compile(r"\\([$}\\,|])")


def split_lsp_lines(content: str) -> list[str]:
    """Split text at the line terminators LSP defines: ``\\n``, ``\\r\\n`` and ``\\r``.

    ``str.splitlines`` also breaks at form feeds and other separators, which
    shifts every later line in sources that contain them (GNU-style C files do).
    """

    if _NON_LSP_LINE_BREAK.search(content) is None:
        return content.splitlines()
    return _LINE_BREAK.split(content)


def normalize_code_intelligence_kind(value: object) -> str:
    kind = _KIND_BY_LOWER.get(str(value or "").strip().lower())
    if kind is None:
        raise ValueError("代码智能查询类型无效")
    return kind


def clamp_diagnostics_wait_ms(value: object) -> int:
    try:
        wait_ms = int(value if value is not None else 0)
    except (TypeError, ValueError):
        return 0
    return min(MAX_DIAGNOSTICS_WAIT_MS, max(0, wait_ms))


def empty_code_intelligence_payload(kind: str) -> dict[str, object]:
    if kind == "hover":
        return {"contents": [], "range": None}
    if kind == "references":
        return {"items": [], "truncated": False}
    if kind == "documentSymbols":
        return {"items": [], "truncated": False}
    if kind == "semanticTokens":
        return {
            "legend": {"types": [], "modifiers": []},
            "tokens": [],
            "truncated": False,
            "inactive_ranges": [],
            "version": None,
        }
    if kind == "completion":
        return {"items": [], "is_incomplete": False}
    return {"items": [], "version": None, "ready": False}


def code_intelligence_result(
    kind: str,
    request_id: str,
    *,
    provider: str = "",
    available: bool = True,
    supported: bool = True,
    message: str = "",
    payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "request_id": request_id,
        "kind": kind,
        "provider": provider,
        "available": bool(available),
        "supported": bool(supported),
        "message": message,
    }
    result.update(empty_code_intelligence_payload(kind))
    if payload:
        result.update(payload)
    return result


def code_intelligence_text_document_capabilities() -> dict[str, Any]:
    """Client capabilities for every code-intelligence request Orbit issues."""

    return {
        "hover": {"dynamicRegistration": False, "contentFormat": ["markdown", "plaintext"]},
        "references": {"dynamicRegistration": False},
        "documentSymbol": {
            "dynamicRegistration": False,
            "hierarchicalDocumentSymbolSupport": True,
            # Without the value set a server must fold struct/enumMember/... into
            # the original 18 kinds.
            "symbolKind": {"valueSet": list(range(1, len(_SYMBOL_KINDS) + 1))},
        },
        "semanticTokens": {
            "dynamicRegistration": False,
            "requests": {"full": True, "range": False},
            "formats": ["relative"],
            "tokenTypes": list(_SEMANTIC_TOKEN_TYPES),
            "tokenModifiers": list(_SEMANTIC_TOKEN_MODIFIERS),
            "overlappingTokenSupport": False,
            "multilineTokenSupport": False,
            "augmentsSyntaxTokens": True,
        },
        "completion": {
            "dynamicRegistration": False,
            "completionItem": {
                "snippetSupport": False,
                "documentationFormat": ["markdown", "plaintext"],
                "deprecatedSupport": True,
                "insertReplaceSupport": False,
            },
            "completionItemKind": {"valueSet": list(range(1, len(_COMPLETION_KINDS) + 1))},
            "contextSupport": True,
        },
        "publishDiagnostics": {"relatedInformation": False, "versionSupport": True},
    }


def _provider_enabled(value: object) -> bool:
    # LSP providers are ``boolean | Options``; an empty options object still
    # means the feature is available.
    return value is True or isinstance(value, Mapping)


def _string_tuple(value: object, *, limit: int = 256) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item)[:100] for item in value[:limit] if isinstance(item, str))


@dataclass(frozen=True, slots=True)
class ServerFeatures:
    """Which code-intelligence requests the initialized server advertises."""

    hover: bool = False
    references: bool = False
    document_symbols: bool = False
    semantic_tokens: bool = False
    completion: bool = False
    semantic_token_types: tuple[str, ...] = ()
    semantic_token_modifiers: tuple[str, ...] = ()
    completion_trigger_characters: frozenset[str] = frozenset()

    @classmethod
    def from_capabilities(cls, capabilities: object) -> "ServerFeatures":
        if not isinstance(capabilities, Mapping):
            return cls()
        semantic = capabilities.get("semanticTokensProvider")
        semantic_types: tuple[str, ...] = ()
        semantic_modifiers: tuple[str, ...] = ()
        semantic_supported = False
        if isinstance(semantic, Mapping):
            legend = semantic.get("legend")
            if isinstance(legend, Mapping):
                semantic_types = _string_tuple(legend.get("tokenTypes"))
                semantic_modifiers = _string_tuple(legend.get("tokenModifiers"))
            semantic_supported = _provider_enabled(semantic.get("full")) and bool(semantic_types)
        completion = capabilities.get("completionProvider")
        triggers: frozenset[str] = frozenset()
        if isinstance(completion, Mapping):
            triggers = frozenset(_string_tuple(completion.get("triggerCharacters")))
        return cls(
            hover=_provider_enabled(capabilities.get("hoverProvider")),
            references=_provider_enabled(capabilities.get("referencesProvider")),
            document_symbols=_provider_enabled(capabilities.get("documentSymbolProvider")),
            semantic_tokens=semantic_supported,
            completion=_provider_enabled(completion),
            semantic_token_types=semantic_types,
            semantic_token_modifiers=semantic_modifiers,
            completion_trigger_characters=triggers,
        )

    def supports(self, kind: str) -> bool:
        if kind == "hover":
            return self.hover
        if kind == "references":
            return self.references
        if kind == "documentSymbols":
            return self.document_symbols
        if kind == "semanticTokens":
            return self.semantic_tokens
        if kind == "completion":
            return self.completion
        # Diagnostics are pushed by every supported server.
        return kind == "diagnostics"


@lru_cache(maxsize=2048)
def document_uri_key(uri: str) -> str:
    """Comparable identity for a ``file://`` URI, tolerant of encoding variants."""

    value = str(uri or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() != "file":
        return ""
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path = f"//{parsed.netloc}{path}"
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return os.path.normcase(os.path.normpath(path)) if path else ""


def _unit_width(character: str, encoding: str) -> int:
    code = ord(character)
    if encoding == "utf-8":
        return 1 if code < 0x80 else 2 if code < 0x800 else 3 if code < 0x10000 else 4
    return 2 if code >= 0x10000 else 1


class TextIndex:
    """Line table converting between LSP positions and 1-based code-point positions.

    Lines end only at the terminators LSP defines (``\\n``, ``\\r\\n``, ``\\r``),
    which is also how the editor counts them.
    """

    __slots__ = ("lines", "encoding", "_tables")

    def __init__(self, content: str, encoding: str) -> None:
        self.lines = split_lsp_lines(str(content))
        self.encoding = "utf-8" if encoding == "utf-8" else "utf-16"
        self._tables: dict[int, list[int] | None] = {}

    def line_text(self, line_index: int) -> str:
        return self.lines[line_index] if 0 <= line_index < len(self.lines) else ""

    def _table(self, line_index: int) -> list[int] | None:
        """Cumulative unit offsets for a non-ASCII line, ``None`` for ASCII."""

        if line_index in self._tables:
            return self._tables[line_index]
        text = self.line_text(line_index)
        table: list[int] | None = None
        if not text.isascii():
            table = [0]
            total = 0
            for character in text:
                total += _unit_width(character, self.encoding)
                table.append(total)
        self._tables[line_index] = table
        return table

    def codepoint_index(self, line_index: int, units: int) -> int:
        units = max(0, units)
        table = self._table(line_index)
        if table is None:
            return min(units, len(self.line_text(line_index)))
        # A position inside a multi-unit character snaps to that character's start.
        return bisect_right(table, units) - 1

    def to_lsp_position(self, *, line: int, column: int) -> dict[str, int]:
        line_index = max(0, int(line) - 1)
        text = self.line_text(line_index)
        codepoint_index = min(max(0, int(column) - 1), len(text))
        table = self._table(line_index)
        character = codepoint_index if table is None else table[codepoint_index]
        return {"line": line_index, "character": character}

    def position(self, value: object) -> dict[str, int] | None:
        if not isinstance(value, Mapping):
            return None
        try:
            line_index = max(0, int(value.get("line") or 0))
            units = max(0, int(value.get("character") or 0))
        except (TypeError, ValueError):
            return None
        return {"line": line_index + 1, "column": self.codepoint_index(line_index, units) + 1}

    def range(self, value: object) -> dict[str, dict[str, int]] | None:
        if not isinstance(value, Mapping):
            return None
        start = self.position(value.get("start"))
        end = self.position(value.get("end"))
        if start is None or end is None:
            return None
        return {"start": start, "end": end}

    def word_prefix(self, *, line: int, column: int) -> str:
        text = self.line_text(max(0, int(line) - 1))
        match = _WORD_PREFIX.search(text[: max(0, int(column) - 1)])
        return match.group(0) if match else ""


class LocationContentCache:
    """Target file contents and line tables shared across one location list."""

    def __init__(self) -> None:
        self._contents: dict[str, str] = {}
        self._lines: dict[str, list[str]] = {}

    def get(self, key: str) -> str | None:
        return self._contents.get(key)

    def put(self, key: str, content: str) -> None:
        if self._contents.get(key) is not content:
            self._contents[key] = content
            self._lines.pop(key, None)

    def preview(self, key: str, line: int) -> str:
        """The stripped source line at a 1-based line number, bounded for transport."""

        lines = self._lines.get(key)
        if lines is None:
            lines = self._lines[key] = split_lsp_lines(self._contents.get(key, ""))
        if not 1 <= line <= len(lines):
            return ""
        return lines[line - 1].strip()[:MAX_REFERENCE_PREVIEW_CHARS]


def _fenced_code_block(language: str, value: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{value}\n{fence}"


def normalize_hover_contents(value: object, *, limit: int = MAX_HOVER_CHARS) -> list[dict[str, str]]:
    """Flatten MarkupContent, MarkedString and arrays of either."""

    entries: list[dict[str, str]] = []
    remaining = max(0, int(limit))
    for raw in value if isinstance(value, list) else [value]:
        if remaining <= 0:
            break
        language: str | None = None
        kind = "markdown"
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, Mapping):
            text = raw.get("value")
            if not isinstance(text, str):
                continue
            raw_kind = str(raw.get("kind") or "").strip().lower()
            if raw_kind in {"markdown", "plaintext"}:
                kind = raw_kind
            elif "language" in raw:
                language = re.sub(r"[^\w+#.-]", "", str(raw.get("language") or ""))[:40]
        else:
            continue
        if not text.strip():
            continue
        text = text[:remaining]
        remaining -= len(text)
        entries.append({"kind": kind, "value": text if language is None else _fenced_code_block(language, text)})
    return entries


def _markup_text(value: object, *, limit: int) -> str:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, Mapping):
        text = value.get("value")
        return text[:limit] if isinstance(text, str) else ""
    return ""


def _text(value: object, *, limit: int = _MAX_LABEL_CHARS) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _kind_name(names: Sequence[str], value: object, default: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return names[value - 1] if 1 <= value <= len(names) else default


def normalize_document_symbols(
    response: object,
    index: TextIndex,
    *,
    active_uri: str = "",
    limit: int = MAX_SYMBOL_NODES,
) -> tuple[list[dict[str, object]], bool]:
    """Normalize ``DocumentSymbol[]`` (tree) or ``SymbolInformation[]`` (flat)."""

    if not isinstance(response, list):
        return [], False
    budget = max(0, int(limit))
    truncated = False
    active_key = document_uri_key(active_uri)

    def convert(raw: object, depth: int) -> dict[str, object] | None:
        nonlocal budget, truncated
        if not isinstance(raw, Mapping):
            return None
        location = raw.get("location")
        flat = isinstance(location, Mapping) and "range" not in raw
        if flat:
            uri_key = document_uri_key(str(location.get("uri") or ""))
            if active_key and uri_key and uri_key != active_key:
                return None
            symbol_range = index.range(location.get("range"))
            selection_range = symbol_range
        else:
            symbol_range = index.range(raw.get("range"))
            selection_range = index.range(raw.get("selectionRange")) or symbol_range
        if symbol_range is None or selection_range is None:
            return None
        if budget <= 0:
            truncated = True
            return None
        budget -= 1
        children: list[dict[str, object]] = []
        raw_children = raw.get("children")
        if not flat and isinstance(raw_children, list) and raw_children:
            if depth >= MAX_SYMBOL_DEPTH:
                truncated = True
            else:
                for child in raw_children:
                    if budget <= 0:
                        truncated = True
                        break
                    node = convert(child, depth + 1)
                    if node is not None:
                        children.append(node)
        node: dict[str, object] = {
            "name": _text(raw.get("name")) or "(anonymous)",
            "detail": _text(raw.get("detail")),
            "kind": _kind_name(_SYMBOL_KINDS, raw.get("kind"), "variable"),
            "range": symbol_range,
            "selection_range": selection_range,
            "children": children,
        }
        if flat:
            node["container_name"] = _text(raw.get("containerName"))
        return node

    items: list[dict[str, object]] = []
    for raw in response:
        if budget <= 0:
            truncated = True
            break
        node = convert(raw, 0)
        if node is not None:
            items.append(node)
    return items, truncated


def decode_semantic_tokens(
    data: object,
    index: TextIndex,
    *,
    type_count: int | None = None,
    limit: int = MAX_SEMANTIC_TOKENS,
) -> tuple[list[int], bool]:
    """Decode LSP relative tokens into flat absolute 1-based code-point tuples."""

    if not isinstance(data, list):
        return [], False
    tokens: list[tuple[int, int, int, int, int]] = []
    truncated = False
    line = 0
    start = 0
    for base in range(0, len(data) - len(data) % 5, 5):
        try:
            delta_line = int(data[base])
            delta_start = int(data[base + 1])
            length = int(data[base + 2])
            token_type = int(data[base + 3])
            modifiers = int(data[base + 4])
        except (TypeError, ValueError):
            break
        if delta_line < 0 or delta_start < 0:
            break
        if delta_line:
            line += delta_line
            start = delta_start
        else:
            start += delta_start
        if length <= 0 or token_type < 0 or (type_count is not None and token_type >= type_count):
            continue
        begin = index.codepoint_index(line, start)
        end = index.codepoint_index(line, start + length)
        if end <= begin:
            continue
        if len(tokens) >= limit:
            truncated = True
            break
        tokens.append((line + 1, begin + 1, end - begin, token_type, max(0, modifiers)))
    tokens.sort()
    return [value for token in tokens for value in token], truncated


def normalize_inactive_regions(regions: Sequence[tuple[int, int, int, int]]) -> list[dict[str, int]]:
    """Convert stored LSP ranges into inclusive 1-based line spans."""

    result: list[dict[str, int]] = []
    for start_line, _start_character, end_line, end_character in regions:
        # An end at column 0 of a later line excludes that line.
        last = end_line - 1 if end_character == 0 and end_line > start_line else end_line
        if last < start_line:
            continue
        result.append({"start_line": start_line + 1, "end_line": last + 1})
    return result


def _plain_snippet(value: str) -> str:
    text = _SNIPPET_PLACEHOLDER.sub(lambda match: match.group(1), value)
    text = _SNIPPET_CHOICE.sub(lambda match: match.group(1), text)
    text = _SNIPPET_TABSTOP.sub("", text)
    return _SNIPPET_ESCAPE.sub(lambda match: match.group(1), text)


def _is_subsequence(needle: str, haystack: str) -> bool:
    iterator = iter(haystack)
    return all(character in iterator for character in needle)


def normalize_completion(
    response: object,
    index: TextIndex,
    *,
    prefix: str = "",
    limit: int = MAX_COMPLETION_ITEMS,
) -> tuple[list[dict[str, object]], bool]:
    """Normalize ``CompletionItem[] | CompletionList`` into bounded plain items.

    Servers such as tsserver return every visible symbol and leave filtering to
    the client; when the list exceeds the cap, entries matching the typed
    prefix are kept first so the cap never hides what the user is typing.
    """

    if isinstance(response, Mapping):
        raw_items = response.get("items")
        is_incomplete = bool(response.get("isIncomplete"))
    else:
        raw_items = response
        is_incomplete = False
    if not isinstance(raw_items, list):
        return [], is_incomplete

    candidates = [raw for raw in raw_items if isinstance(raw, Mapping) and isinstance(raw.get("label"), str)]

    def sort_key(raw: Mapping[str, Any]) -> str:
        sort_text = raw.get("sortText")
        return sort_text if isinstance(sort_text, str) and sort_text else raw["label"]

    candidates.sort(key=sort_key)
    if len(candidates) > limit:
        is_incomplete = True
        needle = prefix.lower()
        if needle:
            starts: list[Mapping[str, Any]] = []
            fuzzy: list[Mapping[str, Any]] = []
            for raw in candidates:
                filter_text = raw.get("filterText")
                haystack = (filter_text if isinstance(filter_text, str) and filter_text else raw["label"]).strip().lower()
                if haystack.startswith(needle):
                    starts.append(raw)
                elif len(starts) + len(fuzzy) < limit and _is_subsequence(needle, haystack):
                    fuzzy.append(raw)
            candidates = starts + fuzzy
        candidates = candidates[:limit]

    items: list[dict[str, object]] = []
    for raw in candidates:
        label = raw["label"][:_MAX_LABEL_CHARS]
        snippet = raw.get("insertTextFormat") == 2
        text_edit: dict[str, object] | None = None
        raw_edit = raw.get("textEdit")
        new_text: str | None = None
        if isinstance(raw_edit, Mapping) and isinstance(raw_edit.get("newText"), str):
            new_text = raw_edit["newText"][:_MAX_INSERT_TEXT_CHARS]
            if snippet:
                new_text = _plain_snippet(new_text)
            # InsertReplaceEdit carries ``insert``/``replace`` instead of ``range``.
            edit_range = index.range(raw_edit.get("range") or raw_edit.get("insert"))
            if edit_range is not None:
                text_edit = {"range": edit_range, "new_text": new_text}
        insert_text = new_text
        if insert_text is None:
            raw_insert = raw.get("insertText")
            if isinstance(raw_insert, str) and raw_insert:
                insert_text = raw_insert[:_MAX_INSERT_TEXT_CHARS]
                if snippet:
                    insert_text = _plain_snippet(insert_text)
        label_details = raw.get("labelDetails")
        detail_parts: list[str] = []
        for part in (
            label_details.get("detail") if isinstance(label_details, Mapping) else None,
            raw.get("detail"),
            label_details.get("description") if isinstance(label_details, Mapping) else None,
        ):
            text = part.strip() if isinstance(part, str) else ""
            if text and text not in detail_parts:
                detail_parts.append(text)
        tags = raw.get("tags")
        items.append(
            {
                "label": label,
                "kind": _kind_name(_COMPLETION_KINDS, raw.get("kind"), "text"),
                "detail": " ".join(detail_parts)[:_MAX_LABEL_CHARS],
                "documentation": _markup_text(
                    raw.get("documentation"),
                    limit=MAX_COMPLETION_DOCUMENTATION_CHARS,
                ),
                "insert_text": insert_text if insert_text else label,
                "filter_text": _text(raw.get("filterText")) or label,
                "sort_text": _text(raw.get("sortText")) or label,
                "text_edit": text_edit,
                "deprecated": raw.get("deprecated") is True or (isinstance(tags, list) and 1 in tags),
            }
        )
    return items, is_incomplete


@dataclass(frozen=True, slots=True)
class StoredDiagnostic:
    start_line: int
    start_character: int
    end_line: int
    end_character: int
    severity: str
    message: str
    source: str
    code: str


@dataclass(frozen=True, slots=True)
class DiagnosticsEntry:
    """The latest ``publishDiagnostics`` payload of one document."""

    version: int | None
    observed_version: int | None
    items: tuple[StoredDiagnostic, ...]

    @property
    def document_version(self) -> int | None:
        return self.version if self.version is not None else self.observed_version

    def is_current(self, document_version: int) -> bool:
        # Servers without version support are matched by the document version
        # that had been sent when the notification arrived.
        return self.document_version == document_version


def _range_tuple(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return None
    try:
        return (
            max(0, int(start.get("line") or 0)),
            max(0, int(start.get("character") or 0)),
            max(0, int(end.get("line") or 0)),
            max(0, int(end.get("character") or 0)),
        )
    except (TypeError, ValueError):
        return None


def _stored_diagnostics(value: object) -> tuple[StoredDiagnostic, ...]:
    if not isinstance(value, list):
        return ()
    items: list[StoredDiagnostic] = []
    budget = _DIAGNOSTIC_MESSAGE_BUDGET_CHARS
    for raw in value:
        if len(items) >= MAX_DIAGNOSTICS_PER_DOCUMENT:
            break
        if not isinstance(raw, Mapping):
            continue
        span = _range_tuple(raw.get("range"))
        if span is None:
            continue
        code = raw.get("code")
        severity = raw.get("severity")
        message = _text(
            raw.get("message"),
            limit=MAX_DIAGNOSTIC_MESSAGE_CHARS if budget > 0 else _SHORT_DIAGNOSTIC_MESSAGE_CHARS,
        )
        budget -= len(message)
        items.append(
            StoredDiagnostic(
                *span,
                severity=_DIAGNOSTIC_SEVERITIES.get(severity, "error") if isinstance(severity, int) else "error",
                message=message,
                source=_text(raw.get("source"), limit=200),
                code="" if code is None or isinstance(code, (Mapping, list, bool)) else str(code)[:200],
            )
        )
    return tuple(items)


class PushedDocumentState:
    """Bounded per-document state the server pushes without being asked."""

    def __init__(self, *, max_documents: int = MAX_PUSHED_DOCUMENTS) -> None:
        self.max_documents = max(1, int(max_documents))
        self._diagnostics: OrderedDict[str, DiagnosticsEntry] = OrderedDict()
        self._inactive_regions: OrderedDict[str, tuple[tuple[int, int, int, int], ...]] = OrderedDict()
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def document_count(self) -> int:
        return len(self._diagnostics.keys() | self._inactive_regions.keys())

    def _store(self, bucket: OrderedDict[str, Any], key: str, value: Any) -> None:
        bucket[key] = value
        bucket.move_to_end(key)
        while len(bucket) > self.max_documents:
            bucket.popitem(last=False)

    def record_diagnostics(
        self,
        key: str,
        *,
        version: int | None,
        observed_version: int | None,
        diagnostics: object,
    ) -> None:
        items = _stored_diagnostics(diagnostics)
        if not items and version is None and observed_version is None:
            # The "cleared" notification that follows didClose carries nothing
            # worth keeping for a document that is no longer open.
            self._diagnostics.pop(key, None)
        else:
            self._store(self._diagnostics, key, DiagnosticsEntry(version, observed_version, items))
        self._wake()

    def record_inactive_regions(self, key: str, regions: object) -> None:
        spans: list[tuple[int, int, int, int]] = []
        if isinstance(regions, list):
            for raw in regions[:MAX_INACTIVE_REGIONS_PER_DOCUMENT]:
                span = _range_tuple(raw)
                if span is not None:
                    spans.append(span)
        self._store(self._inactive_regions, key, tuple(spans))

    def diagnostics(self, key: str) -> DiagnosticsEntry | None:
        return self._diagnostics.get(key)

    def inactive_regions(self, key: str) -> tuple[tuple[int, int, int, int], ...]:
        return self._inactive_regions.get(key, ())

    def drop(self, key: str) -> None:
        self._diagnostics.pop(key, None)
        self._inactive_regions.pop(key, None)
        self._wake()

    def _wake(self) -> None:
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    async def wait_for_change(self, timeout: float) -> None:
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            await asyncio.wait_for(waiter, timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            pass
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)


@dataclass(frozen=True, slots=True)
class DiagnosticsTicket:
    """A synced document version whose diagnostics a query is waiting for."""

    uri: str
    key: str
    lsp_version: int
    request_version: int
    content: str


class CodeIntelligenceMixin:
    """Code-intelligence requests shared by every language-server provider.

    The host provider supplies ``provider_id``, ``workspace_root``,
    ``position_encoding``, ``_documents``, ``_navigation_lock``,
    ``_sync_active_document``, ``_normalize_locations`` and the two hooks below.
    """

    features: ServerFeatures
    pushed_state: PushedDocumentState

    def _init_code_intelligence(self) -> None:
        self.features = ServerFeatures()
        self.pushed_state = PushedDocumentState()

    def _accepts_active_document(self, target: Path, language_id: str, source_id: str) -> bool:
        raise NotImplementedError

    def _active_lsp_language_id(self, target: Path) -> str:
        raise NotImplementedError

    def _record_server_capabilities(self, capabilities: object) -> None:
        self.features = ServerFeatures.from_capabilities(capabilities)

    def _forget_pushed_document(self, uri: str) -> None:
        key = document_uri_key(uri)
        if key:
            self.pushed_state.drop(key)

    def _open_document_version(self, key: str) -> int | None:
        for uri, snapshot in self._documents.items():  # type: ignore[attr-defined]
            if document_uri_key(uri) == key:
                return int(snapshot[0])
        return None

    def handle_push_notification(self, method: str, params: Any) -> None:
        """Keep the latest pushed diagnostics / inactive regions per document."""

        if not isinstance(params, Mapping):
            return
        if method == "textDocument/publishDiagnostics":
            key = document_uri_key(str(params.get("uri") or ""))
            if not key:
                return
            version = params.get("version")
            self.pushed_state.record_diagnostics(
                key,
                version=version if isinstance(version, int) and not isinstance(version, bool) else None,
                observed_version=self._open_document_version(key),
                diagnostics=params.get("diagnostics"),
            )
        elif method == "textDocument/inactiveRegions":
            document = params.get("textDocument")
            key = document_uri_key(str(document.get("uri") or "")) if isinstance(document, Mapping) else ""
            if key:
                self.pushed_state.record_inactive_regions(key, params.get("regions"))

    async def query_code_intelligence(
        self,
        client: Any,
        *,
        kind: str,
        path: Path | str,
        language_id: str,
        version: int,
        content: str,
        line: int = 1,
        column: int = 1,
        source_id: str = "",
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        """Run one request kind and return its payload plus ``supported``."""

        kind = normalize_code_intelligence_kind(kind)
        if kind == "diagnostics":
            raise ValueError("诊断通过 prepare_diagnostics 查询")
        unsupported: dict[str, object] = {"supported": False, **empty_code_intelligence_payload(kind)}
        if not self.features.supports(kind):
            return unsupported
        target = Path(path).expanduser().resolve()
        active_source_id = str(source_id or "").strip()
        if not self._accepts_active_document(target, language_id, active_source_id):
            return unsupported
        text = str(content)
        document_version = max(0, int(version))
        options = context if isinstance(context, Mapping) else {}
        uri = target.as_uri()
        text_document = {"uri": uri}
        index = TextIndex(text, self.position_encoding)  # type: ignore[attr-defined]
        position = index.to_lsp_position(line=max(1, int(line)), column=max(1, int(column)))

        async with self._navigation_lock:  # type: ignore[attr-defined]
            await self._sync_active_document(  # type: ignore[attr-defined]
                client,
                uri=uri,
                language_id=self._active_lsp_language_id(target),
                version=document_version,
                content=text,
            )
            if kind == "hover":
                response = await client.request(
                    "textDocument/hover",
                    {"textDocument": text_document, "position": position},
                )
            elif kind == "references":
                include_declaration = options.get("includeDeclaration", options.get("include_declaration", True))
                response = await client.request(
                    "textDocument/references",
                    {
                        "textDocument": text_document,
                        "position": position,
                        "context": {"includeDeclaration": include_declaration is not False},
                    },
                )
                # Location normalization reads referenced files; keep it off the
                # event loop while the lock still fences document changes.
                items, truncated = await asyncio.to_thread(
                    self._normalize_reference_locations,
                    response,
                    active_path=target,
                    active_content=text,
                    active_source_id=active_source_id,
                )
                return {"supported": True, "items": items, "truncated": truncated}
            elif kind == "documentSymbols":
                response = await client.request("textDocument/documentSymbol", {"textDocument": text_document})
            elif kind == "semanticTokens":
                response = await client.request("textDocument/semanticTokens/full", {"textDocument": text_document})
            else:
                trigger = str(options.get("triggerCharacter") or options.get("trigger_character") or "")
                completion_context: dict[str, object] = {"triggerKind": 1}
                if trigger and trigger in self.features.completion_trigger_characters:
                    completion_context = {"triggerKind": 2, "triggerCharacter": trigger}
                response = await client.request(
                    "textDocument/completion",
                    {"textDocument": text_document, "position": position, "context": completion_context},
                )

        if kind == "hover":
            if not isinstance(response, Mapping):
                return {"supported": True, "contents": [], "range": None}
            return {
                "supported": True,
                "contents": normalize_hover_contents(response.get("contents")),
                "range": index.range(response.get("range")),
            }
        if kind == "documentSymbols":
            symbols, truncated = normalize_document_symbols(response, index, active_uri=uri)
            return {"supported": True, "items": symbols, "truncated": truncated}
        if kind == "semanticTokens":
            types = self.features.semantic_token_types
            data = response.get("data") if isinstance(response, Mapping) else None
            tokens, truncated = await asyncio.to_thread(
                decode_semantic_tokens,
                data,
                index,
                type_count=len(types),
            )
            return {
                "supported": True,
                "legend": {"types": list(types), "modifiers": list(self.features.semantic_token_modifiers)},
                "tokens": tokens,
                "truncated": truncated,
                "inactive_ranges": normalize_inactive_regions(
                    self.pushed_state.inactive_regions(document_uri_key(uri))
                ),
                "version": document_version,
            }
        completions, is_incomplete = normalize_completion(
            response,
            index,
            prefix=index.word_prefix(line=max(1, int(line)), column=max(1, int(column))),
        )
        return {"supported": True, "items": completions, "is_incomplete": is_incomplete}

    def _normalize_reference_locations(
        self,
        response: object,
        *,
        active_path: Path,
        active_content: str,
        active_source_id: str,
    ) -> tuple[list[dict[str, object]], bool]:
        if not isinstance(response, list):
            return [], False
        truncated = len(response) > MAX_REFERENCE_ITEMS
        workspace_root: Path = self.workspace_root  # type: ignore[attr-defined]
        content_cache = LocationContentCache()
        external_files: set[str] = set()
        items: list[dict[str, object]] = []
        for raw in response[:MAX_REFERENCE_ITEMS]:
            if not isinstance(raw, Mapping):
                continue
            key = document_uri_key(str(raw.get("uri") or raw.get("targetUri") or ""))
            if not key:
                continue
            try:
                relative_parts = Path(key).relative_to(os.path.normcase(str(workspace_root))).parts
                external = any(part.lower() in _EXTERNAL_DEPENDENCY_PARTS for part in relative_parts)
            except ValueError:
                external = True
            if external and key not in external_files:
                # Every external file takes a slot in the per-user read-only
                # source registry; one query must not evict what the user has open.
                if len(external_files) >= MAX_REFERENCE_EXTERNAL_FILES:
                    truncated = True
                    continue
                external_files.add(key)
            try:
                items.extend(
                    self._normalize_locations(  # type: ignore[attr-defined]
                        [raw],
                        active_path=active_path,
                        active_content=active_content,
                        active_source_id=active_source_id,
                        content_cache=content_cache,
                    )
                )
            except (OSError, ValueError, RuntimeError):
                # One unreadable or unapproved target must not hide the rest.
                continue
        return items, truncated

    async def prepare_diagnostics(
        self,
        client: Any,
        *,
        path: Path | str,
        language_id: str,
        version: int,
        content: str,
        source_id: str = "",
    ) -> DiagnosticsTicket | None:
        """Sync the active document and describe the version to wait for."""

        target = Path(path).expanduser().resolve()
        if not self._accepts_active_document(target, language_id, str(source_id or "").strip()):
            return None
        text = str(content)
        document_version = max(0, int(version))
        uri = target.as_uri()
        async with self._navigation_lock:  # type: ignore[attr-defined]
            await self._sync_active_document(  # type: ignore[attr-defined]
                client,
                uri=uri,
                language_id=self._active_lsp_language_id(target),
                version=document_version,
                content=text,
            )
            lsp_version = int(self._documents[uri][0])  # type: ignore[attr-defined]
        return DiagnosticsTicket(uri, document_uri_key(uri), lsp_version, document_version, text)

    def diagnostics_snapshot(self, ticket: DiagnosticsTicket) -> dict[str, object]:
        """The stored diagnostics, ``ready`` when they match the ticket's version."""

        entry = self.pushed_state.diagnostics(ticket.key)
        if entry is None:
            return {"items": [], "version": None, "ready": False}
        ready = entry.is_current(ticket.lsp_version)
        index = TextIndex(ticket.content, self.position_encoding)  # type: ignore[attr-defined]
        items: list[dict[str, object]] = []
        for diagnostic in entry.items:
            items.append(
                {
                    "range": {
                        "start": {
                            "line": diagnostic.start_line + 1,
                            "column": index.codepoint_index(diagnostic.start_line, diagnostic.start_character) + 1,
                        },
                        "end": {
                            "line": diagnostic.end_line + 1,
                            "column": index.codepoint_index(diagnostic.end_line, diagnostic.end_character) + 1,
                        },
                    },
                    "severity": diagnostic.severity,
                    "message": diagnostic.message,
                    "source": diagnostic.source,
                    "code": diagnostic.code,
                }
            )
        return {
            "items": items,
            "version": ticket.request_version if ready else entry.document_version,
            "ready": ready,
        }

    async def wait_for_diagnostics(self, ticket: DiagnosticsTicket, timeout: float) -> dict[str, object]:
        """Wait until diagnostics for the ticket's version arrive or time runs out."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(timeout))
        while True:
            entry = self.pushed_state.diagnostics(ticket.key)
            if entry is not None and entry.is_current(ticket.lsp_version):
                break
            snapshot = self._documents.get(ticket.uri)  # type: ignore[attr-defined]
            if snapshot is None or int(snapshot[0]) != ticket.lsp_version:
                # Closed or edited again: this version will not be reported.
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await self.pushed_state.wait_for_change(min(remaining, _DIAGNOSTICS_RECHECK_SECONDS))
        return self.diagnostics_snapshot(ticket)
