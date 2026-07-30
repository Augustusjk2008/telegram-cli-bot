from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from bot.language_server.document_store import (
    LanguageDocument,
    LanguageDocumentError,
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


def test_store_versioned_close_requires_the_current_version_but_unversioned_close_forces(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    current = _document("v3", version=3)
    reopened = _document("v1", version=1)

    store.sync_documents(key, [_document("v2", version=2)])
    store.sync_documents(key, [current])

    stale_close = store.close_documents(key, [{"path": "main.py", "version": 2}])

    assert stale_close.closed_count == 0
    assert store.get(key, "main.py") == current

    matching_close = store.close_documents(key, [{"path": "main.py", "version": 3}])

    assert matching_close.closed == (current,)
    assert store.get(key, "main.py") is None
    assert store.sync_documents(key, [reopened]).accepted == (reopened,)
    assert store.close_documents(key, [{"path": "main.py"}]).closed == (reopened,)


def test_store_rejects_an_explicitly_missing_close_version(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    current = _document("v3", version=3)
    store.sync_documents(key, [current])

    with pytest.raises(LanguageDocumentError, match="关闭项版本无效"):
        store.close_documents(key, [{"path": "main.py", "version": None}])

    assert store.get(key, "main.py") == current


@pytest.mark.parametrize(
    "version",
    [True, False, 3.5, -3.5, float("nan"), float("inf"), float("-inf")],
    ids=("true", "false", "fractional", "negative-fractional", "nan", "positive-infinity", "negative-infinity"),
)
def test_store_rejects_non_integral_or_boolean_explicit_close_versions(tmp_path: Path, version: object) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    current = _document("v3", version=3)
    store.sync_documents(key, [current])

    with pytest.raises(LanguageDocumentError, match="关闭项版本无效"):
        store.close_documents(key, [{"path": "main.py", "version": version}])

    assert store.get(key, "main.py") == current


@pytest.mark.parametrize(
    "version",
    [Decimal("3"), Fraction(3, 1), Fraction(7, 2)],
    ids=("decimal", "integral-fraction", "fractional-fraction"),
)
def test_store_rejects_non_protocol_mapping_close_versions(tmp_path: Path, version: object) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    current = _document("v3", version=3)
    store.sync_documents(key, [current])

    with pytest.raises(LanguageDocumentError, match="关闭项版本无效"):
        store.close_documents(key, [{"path": "main.py", "version": version}])

    assert store.get(key, "main.py") == current


@pytest.mark.parametrize(
    ("version", "current_version"),
    [
        (True, 1),
        (False, 0),
        (None, 3),
        (Decimal("3"), 3),
        (Fraction(3, 1), 3),
        (Fraction(7, 2), 3),
        (3.5, 3),
        (float("nan"), 3),
        (float("inf"), 3),
    ],
    ids=("true", "false", "none", "decimal", "integral-fraction", "fractional-fraction", "fractional", "nan", "infinity"),
)
def test_store_rejects_invalid_language_document_close_versions(
    tmp_path: Path,
    version: object,
    current_version: int,
) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    current = _document("current", version=current_version)
    store.sync_documents(key, [current])
    malformed = LanguageDocument("main.py", "python", version, "close")  # type: ignore[arg-type]

    with pytest.raises(LanguageDocumentError, match="关闭项版本无效"):
        store.close_documents(key, [malformed])

    assert store.get(key, "main.py") == current


def test_store_preview_close_keeps_a_newer_snapshot_when_committing_an_old_plan(tmp_path: Path) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    v2 = _document("v2", version=2)
    v3 = _document("v3", version=3)
    store.sync_documents(key, [v2])

    plan = store.preview_close_documents(key, [{"path": "main.py", "version": 2}])

    assert plan.candidates == (v2,)
    assert store.get(key, "main.py") == v2
    store.sync_documents(key, [v3])
    committed = store.commit_close_documents(key, plan.candidates)

    assert committed.closed == ()
    assert committed.missing == ("main.py",)
    assert store.get(key, "main.py") == v3


@pytest.mark.parametrize("version", [3, 3.0, "3"], ids=("integer", "integral-float", "integer-string"))
def test_store_accepts_integral_explicit_close_versions(tmp_path: Path, version: object) -> None:
    store = LanguageDocumentStore()
    key = _key(tmp_path)
    current = _document("v3", version=3)
    store.sync_documents(key, [current])

    result = store.close_documents(key, [{"path": "main.py", "version": version}])

    assert result.closed == (current,)
    assert store.get(key, "main.py") is None


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
