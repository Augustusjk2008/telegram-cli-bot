from __future__ import annotations

from pathlib import Path

import pytest

from bot.language_server.document_store import (
    LanguageDocument,
    LanguageDocumentLimitError,
    LanguageDocumentRuntimeKey,
    LanguageDocumentStore,
    build_content_change,
)
from bot.language_server.manager import LanguageServerRuntimeManager


class _NoCommandCatalog:
    enabled = True
    installer = None

    def command_for(self, _provider_id: str) -> None:
        return None


def _key(tmp_path: Path, user_id: int = 100) -> LanguageDocumentRuntimeKey:
    return LanguageDocumentRuntimeKey("main", user_id, tmp_path, "pyright")


def _document(content: str, version: int = 1, path: str = "main.py") -> LanguageDocument:
    return LanguageDocument(path, "python", version, content)


def test_store_rejects_out_of_order_versions_without_overwriting(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)

    first = store.sync_documents(key, [_document("first", version=4)])
    stale = store.sync_documents(key, [_document("stale", version=2)])
    repeat = store.sync_documents(key, [_document("first", version=4)])

    assert first.accepted_count == 1
    assert stale.rejected_count == 1
    assert repeat.unchanged == (_document("first", version=4),)
    assert store.get(key, "main.py") == _document("first", version=4)


def test_store_isolates_users_and_workspaces(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    user_key = _key(tmp_path, 100)
    other_user_key = _key(tmp_path, 200)
    other_workspace_key = _key(tmp_path / "other", 100)

    store.sync_documents(user_key, [_document("private")])
    store.sync_documents(other_user_key, [_document("other-user")])
    store.sync_documents(other_workspace_key, [_document("other-workspace")])

    assert store.get(user_key, "main.py").content == "private"
    assert store.get(other_user_key, "main.py").content == "other-user"
    assert store.get(other_workspace_key, "main.py").content == "other-workspace"


def test_store_close_removes_only_selected_documents(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    store.sync_documents(key, [_document("one", path="one.py"), _document("two", path="two.py")])

    result = store.close_documents(key, [{"path": "one.py"}, {"path": "missing.py"}])

    assert result.closed_count == 1
    assert result.missing == ("missing.py",)
    assert store.get(key, "one.py") is None
    assert store.get(key, "two.py") is not None


def test_store_normalizes_equivalent_workspace_paths(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)

    store.sync_documents(key, [_document("draft", path="./src/../main.py")])

    assert store.get(key, "main.py") == _document("draft", path="main.py")
    assert store.close_documents(key, [".\\main.py"]).closed_count == 1


def test_store_enforces_document_and_batch_limits(tmp_path: Path) -> None:
    store = LanguageDocumentStore(max_document_bytes=4, max_batch_bytes=6)
    key = _key(tmp_path)

    with pytest.raises(LanguageDocumentLimitError, match="单个文档"):
        store.sync_documents(key, [_document("12345")])
    with pytest.raises(LanguageDocumentLimitError, match="批次"):
        store.sync_documents(key, [_document("1234", path="a.py"), _document("1234", path="b.py")])


@pytest.mark.asyncio
async def test_manager_enforces_batch_limit_before_provider_grouping(tmp_path: Path) -> None:
    manager = LanguageServerRuntimeManager(_NoCommandCatalog())  # type: ignore[arg-type]
    manager.document_store = LanguageDocumentStore(max_document_bytes=10, max_batch_bytes=12)

    with pytest.raises(LanguageDocumentLimitError, match="批次"):
        await manager.sync_documents(
            bot_alias="main",
            user_id=100,
            workspace_root=tmp_path,
            documents=[
                LanguageDocument("main.py", "python", 1, "12345678"),
                LanguageDocument("main.ts", "typescript", 1, "12345678"),
            ],
        )


def test_incremental_change_uses_utf16_units() -> None:
    change = build_content_change("😀old\n", "😀new\n", change_kind=2, encoding="utf-16")

    assert change["range"] == {
        "start": {"line": 0, "character": 2},
        "end": {"line": 0, "character": 5},
    }
    assert change["text"] == "new"
