"""Code-intelligence normalization and provider behaviour against fake LSP clients."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from bot.language_server.clangd import ClangdProvider, describe_clangd_configuration
from bot.language_server.code_intelligence import (
    MAX_COMPLETION_ITEMS,
    MAX_DIAGNOSTICS_PER_DOCUMENT,
    MAX_HOVER_CHARS,
    MAX_PUSHED_DOCUMENTS,
    MAX_REFERENCE_ITEMS,
    TextIndex,
    decode_semantic_tokens,
    normalize_completion,
    normalize_document_symbols,
    normalize_hover_contents,
    normalize_inactive_regions,
)
from bot.language_server.pyright import PyrightProvider
from bot.language_server.typescript import TypeScriptProvider


FULL_CAPABILITIES: dict[str, Any] = {
    "positionEncoding": "utf-16",
    "textDocumentSync": {"openClose": True, "change": 2},
    "hoverProvider": True,
    "referencesProvider": {},
    "documentSymbolProvider": True,
    "completionProvider": {"triggerCharacters": [".", ":"]},
    "semanticTokensProvider": {
        "legend": {"tokenTypes": ["variable", "function", "comment"], "tokenModifiers": ["declaration", "readonly"]},
        "full": {"delta": True},
        "range": False,
    },
}


class FakeLspClient:
    def __init__(self, capabilities: dict[str, Any] | None = None, responses: dict[str, Any] | None = None) -> None:
        self.capabilities = FULL_CAPABILITIES if capabilities is None else capabilities
        self.responses = dict(responses or {})
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        if method == "initialize":
            return {"capabilities": self.capabilities}
        response = self.responses.get(method)
        if isinstance(response, BaseException):
            raise response
        return response(params) if callable(response) else response

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        self.notifications.append((method, params))

    def sent(self, method: str) -> list[dict[str, Any]]:
        return [params for name, params in self.requests if name == method]


def _lsp_range(start_line: int, start_character: int, end_line: int, end_character: int) -> dict[str, Any]:
    return {
        "start": {"line": start_line, "character": start_character},
        "end": {"line": end_line, "character": end_character},
    }


def _api_range(start_line: int, start_column: int, end_line: int, end_column: int) -> dict[str, Any]:
    return {
        "start": {"line": start_line, "column": start_column},
        "end": {"line": end_line, "column": end_column},
    }


async def _clangd(tmp_path: Path, client: FakeLspClient) -> ClangdProvider:
    provider = ClangdProvider(tmp_path)
    await provider.initialize(client)
    return provider


async def _query(provider: Any, client: FakeLspClient, kind: str, path: Path, content: str, **extra: Any) -> dict[str, object]:
    return await provider.query_code_intelligence(
        client,
        kind=kind,
        path=path,
        language_id=extra.pop("language_id", "cpp"),
        version=extra.pop("version", 1),
        content=content,
        **extra,
    )


# -- capabilities ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_id", ["clangd", "pyright", "typescript"])
async def test_initialize_declares_code_intelligence_capabilities(tmp_path: Path, provider_id: str) -> None:
    provider: Any
    if provider_id == "clangd":
        provider = ClangdProvider(tmp_path)
    elif provider_id == "pyright":
        provider = PyrightProvider(tmp_path, current_executable=sys.executable)
    else:
        provider = TypeScriptProvider(tmp_path)
    client = FakeLspClient()

    await provider.initialize(client)

    text_document = client.sent("initialize")[0]["capabilities"]["textDocument"]
    assert text_document["definition"] == {"dynamicRegistration": False, "linkSupport": True}
    assert text_document["hover"]["contentFormat"] == ["markdown", "plaintext"]
    assert "references" in text_document
    assert text_document["documentSymbol"]["hierarchicalDocumentSymbolSupport"] is True
    semantic = text_document["semanticTokens"]
    assert semantic["requests"] == {"full": True, "range": False}
    assert semantic["formats"] == ["relative"]
    assert semantic["multilineTokenSupport"] is False and semantic["overlappingTokenSupport"] is False
    assert semantic["augmentsSyntaxTokens"] is True
    completion = text_document["completion"]
    assert completion["contextSupport"] is True
    assert completion["completionItem"]["snippetSupport"] is False
    assert completion["completionItem"]["insertReplaceSupport"] is False
    assert completion["completionItem"]["deprecatedSupport"] is True
    assert text_document["publishDiagnostics"] == {"relatedInformation": False, "versionSupport": True}
    assert ("inactiveRegionsCapabilities" in text_document) is (provider_id == "clangd")
    if provider_id == "clangd":
        assert text_document["inactiveRegionsCapabilities"] == {"inactiveRegions": True}

    features = provider.features
    assert features.hover and features.references and features.document_symbols
    assert features.semantic_tokens and features.completion
    assert features.semantic_token_types == ("variable", "function", "comment")
    assert features.completion_trigger_characters == {".", ":"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hover", "references", "documentSymbols", "semanticTokens", "completion"])
async def test_missing_server_capability_reports_unsupported_without_a_request(tmp_path: Path, kind: str) -> None:
    client = FakeLspClient(capabilities={"textDocumentSync": 1})
    provider = await _clangd(tmp_path, client)

    payload = await _query(provider, client, kind, tmp_path / "main.cpp", "int x;\n")

    assert payload["supported"] is False
    assert [name for name, _params in client.requests] == ["initialize"]
    assert client.notifications == [("initialized", {})]


@pytest.mark.asyncio
async def test_semantic_tokens_need_full_document_support(tmp_path: Path) -> None:
    capabilities = {
        **FULL_CAPABILITIES,
        "semanticTokensProvider": {"legend": {"tokenTypes": ["variable"], "tokenModifiers": []}, "range": True},
    }
    provider = await _clangd(tmp_path, FakeLspClient(capabilities=capabilities))

    assert provider.features.semantic_tokens is False
    assert provider.features.hover is True


# -- hover ----------------------------------------------------------------------------------


def test_hover_contents_normalize_every_lsp_shape() -> None:
    assert normalize_hover_contents({"kind": "plaintext", "value": "plain"}) == [
        {"kind": "plaintext", "value": "plain"}
    ]
    assert normalize_hover_contents("**bold**") == [{"kind": "markdown", "value": "**bold**"}]
    assert normalize_hover_contents(
        [{"language": "cpp", "value": "int add(int a)"}, "", {"language": "x", "value": "   "}, "docs", 7]
    ) == [
        {"kind": "markdown", "value": "```cpp\nint add(int a)\n```"},
        {"kind": "markdown", "value": "docs"},
    ]
    # A value that itself contains a fence gets a longer one.
    fenced = normalize_hover_contents({"language": "md", "value": "```\ncode\n```"})[0]["value"]
    assert fenced.startswith("````md\n") and fenced.endswith("\n````")
    assert normalize_hover_contents(None) == []


def test_hover_contents_are_capped_in_total() -> None:
    contents = normalize_hover_contents(["a" * (MAX_HOVER_CHARS - 10), "b" * 50, "c" * 50])

    assert [len(item["value"]) for item in contents] == [MAX_HOVER_CHARS - 10, 10]


@pytest.mark.asyncio
async def test_hover_syncs_the_document_and_converts_utf16_positions(tmp_path: Path) -> None:
    content = 'auto s = "😀字"; int total = add(1, 2);\n'
    # The emoji takes two UTF-16 units, so ``add`` (1-based column 28) starts at 0-based unit 28.
    assert content[27:30] == "add"
    client = FakeLspClient(
        responses={
            "textDocument/hover": {
                "contents": {"kind": "markdown", "value": "`int add(int, int)`"},
                "range": _lsp_range(0, 28, 0, 31),
            }
        }
    )
    provider = await _clangd(tmp_path, client)
    path = tmp_path / "main.cpp"

    payload = await _query(provider, client, "hover", path, content, line=1, column=28)

    assert payload == {
        "supported": True,
        "contents": [{"kind": "markdown", "value": "`int add(int, int)`"}],
        "range": _api_range(1, 28, 1, 31),
    }
    opened = [params for name, params in client.notifications if name == "textDocument/didOpen"]
    assert opened[0]["textDocument"]["uri"] == path.as_uri()
    assert opened[0]["textDocument"]["text"] == content
    assert client.sent("textDocument/hover") == [
        {"textDocument": {"uri": path.as_uri()}, "position": {"line": 0, "character": 28}}
    ]

    # An unchanged document is not re-sent; an edit goes out as didChange.
    await _query(provider, client, "hover", path, content, line=1, column=28)
    await _query(provider, client, "hover", path, content + "// edit\n", line=1, column=28, version=2)
    sync = [name for name, _params in client.notifications if name.startswith("textDocument/")]
    assert sync == ["textDocument/didOpen", "textDocument/didChange"]


@pytest.mark.asyncio
async def test_hover_without_result_is_supported_but_empty(tmp_path: Path) -> None:
    client = FakeLspClient(responses={"textDocument/hover": None})
    provider = await _clangd(tmp_path, client)

    payload = await _query(provider, client, "hover", tmp_path / "main.cpp", "int x;\n")

    assert payload == {"supported": True, "contents": [], "range": None}


# -- references -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_references_reuse_navigation_locations_and_add_previews(tmp_path: Path) -> None:
    active = tmp_path / "main.cpp"
    other = tmp_path / "src" / "util.cpp"
    other.parent.mkdir()
    other.write_text("// header\n    int value = add(1, 2);   \n", encoding="utf-8")
    active.write_text("stale on disk\n", encoding="utf-8")
    content = "int add(int a, int b);\nint twice = add(2, 2);\n"
    client = FakeLspClient(
        responses={
            "textDocument/references": [
                {"uri": active.as_uri(), "range": _lsp_range(0, 4, 0, 7)},
                {"uri": other.as_uri(), "range": _lsp_range(1, 16, 1, 19)},
                {"uri": (tmp_path / "missing.cpp").as_uri(), "range": _lsp_range(0, 0, 0, 1)},
            ]
        }
    )
    provider = await _clangd(tmp_path, client)

    payload = await _query(provider, client, "references", active, content, line=1, column=5)

    assert payload == {
        "supported": True,
        "truncated": False,
        "items": [
            {
                "target_type": "workspace",
                "path": "main.cpp",
                "provider": "clangd",
                "range": _api_range(1, 5, 1, 8),
                "selection_range": _api_range(1, 5, 1, 8),
                # The active editor content wins over what is on disk.
                "preview": "int add(int a, int b);",
            },
            {
                "target_type": "workspace",
                "path": "src/util.cpp",
                "provider": "clangd",
                "range": _api_range(2, 17, 2, 20),
                "selection_range": _api_range(2, 17, 2, 20),
                "preview": "int value = add(1, 2);",
            },
        ],
    }
    assert client.sent("textDocument/references")[0]["context"] == {"includeDeclaration": True}

    await _query(
        provider, client, "references", active, content, line=1, column=5, context={"includeDeclaration": False},
    )
    assert client.sent("textDocument/references")[1]["context"] == {"includeDeclaration": False}


@pytest.mark.asyncio
async def test_locations_after_a_form_feed_keep_their_line_and_column(tmp_path: Path) -> None:
    active = tmp_path / "main.c"
    # GNU-style sources separate sections with form feeds; LSP does not count them as lines.
    content = "int add(int a, int b);\n\x0c\nint twice = add(2, 2);\n"
    location = [{"uri": active.as_uri(), "range": _lsp_range(2, 12, 2, 15)}]
    client = FakeLspClient(
        responses={"textDocument/references": location, "textDocument/definition": location}
    )
    provider = await _clangd(tmp_path, client)

    references = await _query(provider, client, "references", active, content, line=3, column=13, language_id="c")
    definition = await provider.navigate(
        client, kind="definition", path=active, language_id="c", version=1, content=content, line=3, column=13,
    )

    assert references["items"][0]["range"] == _api_range(3, 13, 3, 16)
    assert references["items"][0]["preview"] == "int twice = add(2, 2);"
    assert definition[0]["range"] == _api_range(3, 13, 3, 16)
    assert client.sent("textDocument/definition")[0]["position"] == {"line": 2, "character": 12}


@pytest.mark.asyncio
async def test_references_are_capped_and_previews_bounded(tmp_path: Path) -> None:
    active = tmp_path / "main.cpp"
    content = "x" * 400 + "\n"
    client = FakeLspClient(
        responses={
            "textDocument/references": [
                {"uri": active.as_uri(), "range": _lsp_range(0, index % 300, 0, index % 300 + 1)}
                for index in range(MAX_REFERENCE_ITEMS + 5)
            ]
        }
    )
    provider = await _clangd(tmp_path, client)

    payload = await _query(provider, client, "references", active, content, line=1, column=1)

    assert payload["truncated"] is True
    assert len(payload["items"]) == MAX_REFERENCE_ITEMS
    assert len(payload["items"][0]["preview"]) == 200


# -- document symbols -----------------------------------------------------------------------


def test_document_symbols_keep_hierarchy_and_kind_names() -> None:
    index = TextIndex("struct 点 { int x; };\nint main();\n", "utf-16")
    response = [
        {
            "name": "点",
            "detail": "struct",
            "kind": 23,
            "range": _lsp_range(0, 0, 0, 19),
            "selectionRange": _lsp_range(0, 7, 0, 8),
            "children": [
                {"name": "x", "kind": 8, "range": _lsp_range(0, 11, 0, 16), "selectionRange": _lsp_range(0, 15, 0, 16)},
                {"name": "broken", "kind": 8},
            ],
        },
        {"name": "main", "kind": 12, "range": _lsp_range(1, 0, 1, 10), "selectionRange": _lsp_range(1, 4, 1, 8)},
        {"name": "odd", "kind": 99, "range": _lsp_range(1, 0, 1, 1)},
    ]

    items, truncated = normalize_document_symbols(response, index)

    assert truncated is False
    assert items == [
        {
            "name": "点",
            "detail": "struct",
            "kind": "struct",
            "range": _api_range(1, 1, 1, 20),
            "selection_range": _api_range(1, 8, 1, 9),
            "children": [
                {
                    "name": "x",
                    "detail": "",
                    "kind": "field",
                    "range": _api_range(1, 12, 1, 17),
                    "selection_range": _api_range(1, 16, 1, 17),
                    "children": [],
                }
            ],
        },
        {
            "name": "main",
            "detail": "",
            "kind": "function",
            "range": _api_range(2, 1, 2, 11),
            "selection_range": _api_range(2, 5, 2, 9),
            "children": [],
        },
        {
            "name": "odd",
            "detail": "",
            "kind": "variable",
            "range": _api_range(2, 1, 2, 2),
            "selection_range": _api_range(2, 1, 2, 2),
            "children": [],
        },
    ]


def test_flat_symbol_information_keeps_container_names() -> None:
    index = TextIndex("class A:\n    def run(self): ...\n", "utf-16")
    uri = "file:///workspace/a.py"
    response = [
        {"name": "A", "kind": 5, "location": {"uri": uri, "range": _lsp_range(0, 0, 1, 22)}},
        {"name": "run", "kind": 6, "containerName": "A", "location": {"uri": uri, "range": _lsp_range(1, 4, 1, 22)}},
        {"name": "elsewhere", "kind": 6, "location": {"uri": "file:///workspace/b.py", "range": _lsp_range(0, 0, 0, 1)}},
    ]

    items, truncated = normalize_document_symbols(response, index, active_uri=uri)

    assert truncated is False
    assert [(item["name"], item["kind"], item["container_name"], item["children"]) for item in items] == [
        ("A", "class", "", []),
        ("run", "method", "A", []),
    ]
    assert items[1]["range"] == items[1]["selection_range"] == _api_range(2, 5, 2, 23)


def test_document_symbols_cap_total_nodes() -> None:
    index = TextIndex("x\n", "utf-16")
    child = {"name": "c", "kind": 13, "range": _lsp_range(0, 0, 0, 1), "selectionRange": _lsp_range(0, 0, 0, 1)}
    response = [{**child, "name": f"p{number}", "children": [child, child, child]} for number in range(3)]

    items, truncated = normalize_document_symbols(response, index, limit=6)

    assert truncated is True
    assert sum(1 + len(item["children"]) for item in items) == 6


# -- semantic tokens ------------------------------------------------------------------------


def test_semantic_tokens_decode_relative_utf16_positions_to_code_points() -> None:
    #          1234567890123456789012345
    content = 'int a;\nauto s = "😀字"; int total = add;\n\tint 变量 = 1;\n'
    index = TextIndex(content, "utf-16")
    data = [
        0, 4, 1, 0, 1,   # a
        1, 5, 1, 0, 0,   # s
        0, 15, 5, 0, 2,  # total: the emoji makes the UTF-16 offset 20 where the code point offset is 19
        0, 8, 3, 1, 0,   # add
        1, 5, 2, 0, 3,   # 变量
        0, 2, 0, 0, 0,   # zero length is dropped
        0, 0, 1, 9, 0,   # unknown type index is dropped
    ]

    tokens, truncated = decode_semantic_tokens(data, index, type_count=3)

    assert truncated is False
    assert tokens == [
        1, 5, 1, 0, 1,
        2, 6, 1, 0, 0,
        2, 20, 5, 0, 2,
        2, 28, 3, 1, 0,
        3, 6, 2, 0, 3,
    ]
    lines = content.split("\n")
    texts = [lines[tokens[i] - 1][tokens[i + 1] - 1 : tokens[i + 1] - 1 + tokens[i + 2]] for i in range(0, len(tokens), 5)]
    assert texts == ["a", "s", "total", "add", "变量"]


def test_semantic_tokens_decode_utf8_positions_and_cap() -> None:
    content = 'x = "😀字"; total = 1\n'
    index = TextIndex(content, "utf-8")
    # UTF-8: quote(1) + emoji(4) + 字(3) + quote(1) + "; " puts ``total`` at byte 15, code point 10.
    tokens, truncated = decode_semantic_tokens([0, 0, 1, 0, 0, 0, 15, 5, 0, 0], index, type_count=1)
    assert truncated is False
    assert tokens == [1, 1, 1, 0, 0, 1, 11, 5, 0, 0]
    assert content[10:15] == "total"

    many = [0, 0, 1, 0, 0] + [0, 2, 1, 0, 0] * 9
    capped, truncated = decode_semantic_tokens(many, TextIndex("a " * 10, "utf-16"), limit=4)
    assert truncated is True
    assert len(capped) == 4 * 5


def test_text_index_only_breaks_lines_where_lsp_does() -> None:
    # A form feed (common in GNU sources) is not a line terminator for LSP or the editor.
    index = TextIndex("a\x0cb\r\nc\rd\ne", "utf-16")

    assert index.lines == ["a\x0cb", "c", "d", "e"]
    assert index.to_lsp_position(line=4, column=1) == {"line": 3, "character": 0}


@pytest.mark.asyncio
async def test_semantic_tokens_carry_legend_version_and_clangd_inactive_regions(tmp_path: Path) -> None:
    path = tmp_path / "main.cpp"
    content = "#if 0\nint off;\nint off2;\n#endif\nint on;\n"
    client = FakeLspClient(responses={"textDocument/semanticTokens/full": {"data": [4, 4, 2, 0, 1]}})
    provider = await _clangd(tmp_path, client)

    provider.handle_push_notification(
        "textDocument/inactiveRegions",
        {"textDocument": {"uri": path.as_uri()}, "regions": [_lsp_range(1, 0, 2, 9), _lsp_range(7, 0, 9, 0)]},
    )
    payload = await _query(provider, client, "semanticTokens", path, content, version=7)

    assert payload == {
        "supported": True,
        "legend": {"types": ["variable", "function", "comment"], "modifiers": ["declaration", "readonly"]},
        "tokens": [5, 5, 2, 0, 1],
        "truncated": False,
        "inactive_ranges": [{"start_line": 2, "end_line": 3}, {"start_line": 8, "end_line": 9}],
        "version": 7,
    }

    # The latest notification replaces the previous regions; closing forgets them.
    provider.handle_push_notification(
        "textDocument/inactiveRegions",
        {"textDocument": {"uri": path.as_uri()}, "regions": []},
    )
    assert (await _query(provider, client, "semanticTokens", path, content, version=7))["inactive_ranges"] == []
    provider.handle_push_notification(
        "textDocument/inactiveRegions",
        {"textDocument": {"uri": path.as_uri()}, "regions": [_lsp_range(1, 0, 2, 9)]},
    )
    assert await provider.close_documents(client, ["main.cpp"]) == ["main.cpp"]
    assert provider.pushed_state.document_count == 0


def test_inactive_regions_become_inclusive_line_spans() -> None:
    assert normalize_inactive_regions([(1, 0, 2, 9), (4, 0, 6, 0), (8, 3, 8, 3)]) == [
        {"start_line": 2, "end_line": 3},
        {"start_line": 5, "end_line": 6},
        {"start_line": 9, "end_line": 9},
    ]


# -- completion -----------------------------------------------------------------------------


def test_completion_items_are_normalized_and_sorted() -> None:
    index = TextIndex('s = "😀"; value.pu\n', "utf-16")
    response = {
        "isIncomplete": True,
        "items": [
            {"label": "zeta", "kind": 3, "sortText": "2", "insertText": "zeta()", "tags": [1]},
            {
                "label": "push_back",
                "kind": 2,
                "sortText": "1",
                "detail": "void",
                "labelDetails": {"detail": "(const T& value)", "description": "std::vector"},
                "documentation": {"kind": "markdown", "value": "d" * 5000},
                "filterText": "push_back",
                # InsertReplaceEdit: the insert range applies.
                "textEdit": {
                    "newText": "push_back",
                    "insert": _lsp_range(0, 16, 0, 18),
                    "replace": _lsp_range(0, 16, 0, 20),
                },
            },
            {"label": "plain", "kind": 99, "deprecated": True, "documentation": "text"},
            {"label": "snip", "kind": 15, "sortText": "3", "insertTextFormat": 2, "insertText": "for (${1:int i}; $2) {$0}"},
            {"kind": 3},
        ],
    }

    items, is_incomplete = normalize_completion(response, index)

    assert is_incomplete is True
    assert [item["label"] for item in items] == ["push_back", "zeta", "snip", "plain"]
    assert items[0] == {
        "label": "push_back",
        "kind": "method",
        "detail": "(const T& value) void std::vector",
        "documentation": "d" * 2000,
        "insert_text": "push_back",
        "filter_text": "push_back",
        "sort_text": "1",
        # UTF-16 unit 16 is code point 15 because of the emoji.
        "text_edit": {"range": _api_range(1, 16, 1, 18), "new_text": "push_back"},
        "deprecated": False,
    }
    assert items[1]["kind"] == "function" and items[1]["insert_text"] == "zeta()" and items[1]["deprecated"] is True
    assert items[1]["text_edit"] is None and items[1]["sort_text"] == "2" and items[1]["filter_text"] == "zeta"
    assert items[2]["kind"] == "snippet" and items[2]["insert_text"] == "for (int i; ) {}"
    assert items[3] == {
        "label": "plain",
        "kind": "text",
        "detail": "",
        "documentation": "text",
        "insert_text": "plain",
        "filter_text": "plain",
        "sort_text": "plain",
        "text_edit": None,
        "deprecated": True,
    }
    assert normalize_completion(None, index) == ([], False)
    assert normalize_completion([{"label": "bare"}], index)[1] is False


def test_completion_cap_keeps_entries_matching_the_typed_prefix() -> None:
    index = TextIndex("use\n", "utf-16")
    # tsserver-style: every global, unfiltered, with the wanted names sorted last.
    response = [{"label": f"name{number:04d}", "sortText": "11"} for number in range(MAX_COMPLETION_ITEMS + 50)]
    response += [
        {"label": "unSEt", "sortText": "14"},
        {"label": "useState", "sortText": "15"},
        {"label": "status", "sortText": "15"},
    ]

    # Prefix matches come first, then fuzzy (subsequence) matches; the rest is dropped.
    items, is_incomplete = normalize_completion(response, index, prefix="use")
    assert is_incomplete is True
    assert [item["label"] for item in items] == ["useState", "unSEt"]

    items, is_incomplete = normalize_completion(response, index)
    assert is_incomplete is True
    assert len(items) == MAX_COMPLETION_ITEMS
    assert items[0]["label"] == "name0000"


@pytest.mark.asyncio
async def test_completion_sends_trigger_context_only_for_advertised_characters(tmp_path: Path) -> None:
    path = tmp_path / "main.cpp"
    content = "value.\n"
    client = FakeLspClient(responses={"textDocument/completion": [{"label": "size", "kind": 2}]})
    provider = await _clangd(tmp_path, client)

    payload = await _query(
        provider, client, "completion", path, content, line=1, column=7, context={"triggerCharacter": "."},
    )
    await _query(provider, client, "completion", path, content, line=1, column=7, context={"triggerCharacter": "("})
    await _query(provider, client, "completion", path, content, line=1, column=7)

    assert payload["supported"] is True and payload["is_incomplete"] is False
    assert [item["label"] for item in payload["items"]] == ["size"]
    sent = client.sent("textDocument/completion")
    assert sent[0]["position"] == {"line": 0, "character": 6}
    assert [params["context"] for params in sent] == [
        {"triggerKind": 2, "triggerCharacter": "."},
        {"triggerKind": 1},
        {"triggerKind": 1},
    ]


# -- diagnostics ----------------------------------------------------------------------------


def _publish(provider: Any, path: Path, diagnostics: list[dict[str, Any]], version: int | None = None) -> None:
    params: dict[str, Any] = {"uri": path.as_uri(), "diagnostics": diagnostics}
    if version is not None:
        params["version"] = version
    provider.handle_push_notification("textDocument/publishDiagnostics", params)


async def _ticket(provider: Any, client: FakeLspClient, path: Path, content: str, version: int) -> Any:
    return await provider.prepare_diagnostics(client, path=path, language_id="cpp", version=version, content=content)


@pytest.mark.asyncio
async def test_diagnostics_are_normalized_and_matched_by_reported_version(tmp_path: Path) -> None:
    path = tmp_path / "main.cpp"
    content = 'auto s = "😀"; int x = nope;\n'
    client = FakeLspClient()
    provider = await _clangd(tmp_path, client)

    ticket = await _ticket(provider, client, path, content, 3)
    assert provider.diagnostics_snapshot(ticket) == {"items": [], "version": None, "ready": False}

    _publish(
        provider,
        path,
        [
            {
                "range": _lsp_range(0, 23, 0, 27),
                "severity": 1,
                "message": "m" * 3000,
                "source": "clang",
                "code": "undeclared_var_use",
            },
            {"range": _lsp_range(0, 0, 0, 4), "severity": 2, "message": "warn", "code": 42},
            {"range": _lsp_range(0, 0, 0, 4), "severity": 3, "message": "info"},
            {"range": _lsp_range(0, 0, 0, 4), "severity": 4, "message": "hint", "code": {"value": "x"}},
            {"range": _lsp_range(0, 0, 0, 4), "message": "default severity"},
            {"message": "no range"},
        ],
        version=3,
    )
    snapshot = provider.diagnostics_snapshot(ticket)

    assert snapshot["ready"] is True and snapshot["version"] == 3
    items = snapshot["items"]
    assert items[0] == {
        # The emoji takes two UTF-16 units: 0-based unit 23 is 1-based column 23.
        "range": _api_range(1, 23, 1, 27),
        "severity": "error",
        "message": "m" * 2000,
        "source": "clang",
        "code": "undeclared_var_use",
    }
    assert content[22:26] == "nope"
    assert [(item["severity"], item["code"], item["source"]) for item in items[1:]] == [
        ("warning", "42", ""),
        ("info", "", ""),
        ("hint", "", ""),
        ("error", "", ""),
    ]

    # An edit makes the stored result stale until the server reports the new version.
    edited = await _ticket(provider, client, path, content + "\n", 4)
    stale = provider.diagnostics_snapshot(edited)
    assert stale["ready"] is False and stale["version"] == 3 and len(stale["items"]) == 5
    _publish(provider, path, [], version=4)
    assert provider.diagnostics_snapshot(edited) == {"items": [], "version": 4, "ready": True}


@pytest.mark.asyncio
async def test_diagnostics_without_versions_count_when_received_after_the_sync(tmp_path: Path) -> None:
    path = tmp_path / "main.cpp"
    client = FakeLspClient()
    provider = await _clangd(tmp_path, client)

    first = await _ticket(provider, client, path, "int a;\n", 1)
    _publish(provider, path, [{"range": _lsp_range(0, 0, 0, 3), "severity": 2, "message": "w"}])
    assert provider.diagnostics_snapshot(first)["ready"] is True

    second = await _ticket(provider, client, path, "int b;\n", 2)
    assert provider.diagnostics_snapshot(second)["ready"] is False
    _publish(provider, path, [])
    assert provider.diagnostics_snapshot(second) == {"items": [], "version": 2, "ready": True}

    # Unchanged content sends nothing and reuses what is stored.
    sync_count = len(client.notifications)
    again = await _ticket(provider, client, path, "int b;\n", 2)
    assert len(client.notifications) == sync_count
    assert provider.diagnostics_snapshot(again)["ready"] is True


@pytest.mark.asyncio
async def test_waiting_for_diagnostics_returns_on_arrival_timeout_or_supersession(tmp_path: Path) -> None:
    path = tmp_path / "main.cpp"
    client = FakeLspClient()
    provider = await _clangd(tmp_path, client)
    loop = asyncio.get_running_loop()

    ticket = await _ticket(provider, client, path, "int a = b;\n", 1)
    waiter = asyncio.create_task(provider.wait_for_diagnostics(ticket, 5.0))
    await asyncio.sleep(0)
    assert not waiter.done()
    _publish(provider, path, [{"range": _lsp_range(0, 8, 0, 9), "severity": 1, "message": "undeclared"}], version=1)
    result = await asyncio.wait_for(waiter, timeout=1.0)
    assert result["ready"] is True and result["items"][0]["message"] == "undeclared"

    # Nothing arrives for the new version: the wait ends at the deadline with the stale result.
    edited = await _ticket(provider, client, path, "int a = c;\n", 2)
    started = loop.time()
    result = await provider.wait_for_diagnostics(edited, 0.05)
    assert loop.time() - started < 1.0
    assert result["ready"] is False and result["version"] == 1 and len(result["items"]) == 1

    # A newer edit supersedes the version being waited for.
    waiter = asyncio.create_task(provider.wait_for_diagnostics(edited, 5.0))
    await asyncio.sleep(0)
    await _ticket(provider, client, path, "int a = d;\n", 3)
    _publish(provider, path, [], version=3)
    result = await asyncio.wait_for(waiter, timeout=1.0)
    assert result["ready"] is False


@pytest.mark.asyncio
async def test_pushed_state_is_bounded_and_dropped_on_close(tmp_path: Path) -> None:
    client = FakeLspClient()
    provider = await _clangd(tmp_path, client)
    path = tmp_path / "main.cpp"

    for number in range(MAX_PUSHED_DOCUMENTS + 25):
        _publish(provider, tmp_path / f"file{number}.cpp", [{"range": _lsp_range(0, 0, 0, 1), "message": "x"}])
    assert provider.pushed_state.document_count == MAX_PUSHED_DOCUMENTS

    ticket = await _ticket(provider, client, path, "int a;\n", 1)
    _publish(
        provider,
        path,
        [{"range": _lsp_range(0, 0, 0, 1), "message": str(number)} for number in range(MAX_DIAGNOSTICS_PER_DOCUMENT + 40)],
        version=1,
    )
    assert len(provider.diagnostics_snapshot(ticket)["items"]) == MAX_DIAGNOSTICS_PER_DOCUMENT

    assert await provider.close_documents(client, ["main.cpp"]) == ["main.cpp"]
    assert provider.diagnostics_snapshot(ticket) == {"items": [], "version": None, "ready": False}
    # The empty "cleared" notification servers send after didClose is not kept.
    count = provider.pushed_state.document_count
    _publish(provider, path, [])
    assert provider.pushed_state.document_count == count

    # Malformed notifications are ignored.
    provider.handle_push_notification("textDocument/publishDiagnostics", None)
    provider.handle_push_notification("textDocument/publishDiagnostics", {"uri": "untitled:1", "diagnostics": []})
    provider.handle_push_notification("window/logMessage", {"type": 3, "message": "x" * 100})
    assert provider.pushed_state.document_count == count


# -- clangd configuration -------------------------------------------------------------------


def test_clangd_configuration_reports_how_build_settings_were_found(tmp_path: Path) -> None:
    fallback = describe_clangd_configuration(tmp_path)
    assert fallback["mode"] == "fallback"
    assert fallback["summary"] == "默认参数 -std=c++17"
    assert "compile_commands.json" in fallback["hint"] and "CMAKE_EXPORT_COMPILE_COMMANDS" in fallback["hint"]

    (tmp_path / "compile_flags.txt").write_text("-std=c++20\n", encoding="utf-8")
    assert describe_clangd_configuration(tmp_path) == {
        "mode": "project_config",
        "summary": "compile_flags.txt",
        "hint": "",
    }
    (tmp_path / ".clangd").write_text("CompileFlags:\n  Add: [-Wall]\n", encoding="utf-8")
    assert describe_clangd_configuration(tmp_path)["summary"] == ".clangd"

    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "compile_commands.json").write_text("[]", encoding="utf-8")
    assert describe_clangd_configuration(tmp_path) == {
        "mode": "compile_commands",
        "summary": "compile_commands.json (build) + .clangd",
        "hint": "",
    }
    (tmp_path / ".clangd").unlink()
    (tmp_path / "compile_flags.txt").unlink()
    (tmp_path / "compile_commands.json").write_text("[]", encoding="utf-8")
    assert describe_clangd_configuration(tmp_path)["summary"] == "compile_commands.json"

    # Discovery matches what the provider itself will use.
    provider = ClangdProvider(tmp_path)
    assert provider.compilation_database == tmp_path / "compile_commands.json"
    assert provider.using_fallback_flags is False
