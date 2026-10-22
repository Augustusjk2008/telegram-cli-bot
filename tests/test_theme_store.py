from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bot import runtime_paths
from bot.web import theme_store
from bot.web.theme_store import BUILTIN_THEME_ID, ThemeStore, ThemeStoreError


def create_input(**changes):
    return {"schemaVersion": 1, "expectedRevision": 0, "sourceId": BUILTIN_THEME_ID, "name": "我的主题", **changes}


@pytest.fixture
def store(tmp_path):
    return ThemeStore(tmp_path / "themes" / "accounts")


def test_theme_path_follows_active_data_root_without_creating_it(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    monkeypatch.setenv("TCB_DATA_DIR", str(root))
    assert runtime_paths.get_theme_accounts_dir() == root / "themes" / "accounts"
    assert ThemeStore().accounts_dir == runtime_paths.get_theme_accounts_dir()
    assert not runtime_paths.get_theme_accounts_dir().exists()


def test_personal_crud_copy_normalization_and_selection_persist(store):
    assert store.list_for_account("alice")["selectedThemeId"] == BUILTIN_THEME_ID
    assert not store.accounts_dir.exists()
    library = store.create("alice", create_input(activate=True, appearance={"colors": {
        "scheme": "dark", "overrides": {"surface.base": "#123", "border": "#aBc8", "accent": "#abcdef"},
    }}))
    first = library["themes"][1]
    theme_id = first["id"]
    assert library["revision"] == 1
    assert library["selectedThemeId"] == theme_id
    assert first["appearance"]["colors"]["overrides"] == {
        "surface.base": "#112233FF", "border": "#AABBCC88", "accent": "#ABCDEFFF",
    }
    assert first["version"] == 1 and first["readonly"] is False
    reloaded = ThemeStore(store.accounts_dir)
    assert reloaded.list_for_account("alice") == library
    library = reloaded.create("alice", create_input(expectedRevision=1, sourceId=theme_id, name="复制"))
    copied_id = library["themes"][2]["id"]
    assert library["selectedThemeId"] == theme_id
    assert library["themes"][2]["appearance"] == first["appearance"]
    library = store.update("alice", copied_id, {"schemaVersion": 1, "expectedRevision": 2, "name": "重命名",
        "activate": True, "appearance": {"colors": {"scheme": "light", "overrides": {"border": "#abcdef00"}}}})
    assert library["revision"] == 3 and library["selectedThemeId"] == copied_id
    assert library["themes"][2]["id"] == copied_id and library["themes"][2]["version"] == 2
    assert library["themes"][2]["appearance"]["colors"]["overrides"] == {"border": "#ABCDEF00"}
    library = store.update("alice", theme_id, {"schemaVersion": 1, "expectedRevision": 3, "name": "另一个主题"})
    assert library["selectedThemeId"] == copied_id
    library = store.select("alice", {"themeId": theme_id, "expectedRevision": 4})
    assert library["selectedThemeId"] == theme_id
    library = store.delete("alice", copied_id, {"expectedRevision": 5})
    assert library["selectedThemeId"] == theme_id
    library = store.delete("alice", theme_id, {"expectedRevision": 6})
    assert library["revision"] == 7 and library["selectedThemeId"] == BUILTIN_THEME_ID
    assert len(library["themes"]) == 1
    assert reloaded.list_for_account("alice") == library
    stored = json.loads(next(store.accounts_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert stored["themes"] == []


def test_account_paths_are_hashed_and_library_results_are_detached(store):
    owner = "../../账户:alice"
    library = store.create(owner, create_input())
    library["themes"][1]["name"] = "外部修改"
    assert store.list_for_account(owner)["themes"][1]["name"] == "我的主题"
    assert len(store.list_for_account("bob")["themes"]) == 1
    files = list(store.accounts_dir.glob("*.json"))
    assert len(files) == 1 and len(files[0].stem) == 64
    assert files[0].parent == store.accounts_dir


@pytest.mark.parametrize("changes", [
    {"schemaVersion": 2}, {"schemaVersion": True}, {"expectedRevision": -1}, {"expectedRevision": True},
    {"expectedRevision": 1.5}, {"expectedRevision": "0"}, {"expectedRevision": 2**53},
    {"id": BUILTIN_THEME_ID}, {"baseId": "custom"}, {"accountId": "bob"}, {"readonly": False},
    {"name": " "}, {"name": "x" * 81}, {"name": "line\nbreak"}, {"name": 5},
    {"activate": "yes"}, {"sourceId": {}},
    {"appearance": None}, {"appearance": {"style": {}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {}}, "motion": {}}},
    {"appearance": {"colors": {"scheme": "invalid", "overrides": {}}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {}, "css": "body{}"}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": []}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {"unknown": "#FFFFFF"}}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {"surface.base": "url(https://example.com)"}}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {"surface.base": "#FFF; color:red"}}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {"surface.base": "#FFFFFF00"}}}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {"surface.base": "#FFFFF"}}}},
])
def test_invalid_inputs_never_write(store, changes):
    with pytest.raises(ThemeStoreError) as exc:
        store.create("alice", create_input(**changes))
    assert exc.value.status == 400
    assert store.list_for_account("alice")["revision"] == 0
    assert not store.accounts_dir.exists()


@pytest.mark.parametrize("field", ["schemaVersion", "expectedRevision", "sourceId", "name"])
def test_missing_required_create_fields_are_rejected(store, field):
    payload = create_input()
    del payload[field]
    with pytest.raises(ThemeStoreError, match="缺少字段"):
        store.create("alice", payload)


def test_guest_is_builtin_only_and_builtin_is_immutable(store):
    assert len(store.list_for_account("guest")["themes"]) == 1
    assert not store.accounts_dir.exists()
    with pytest.raises(ThemeStoreError) as exc:
        store.create("guest", create_input())
    assert exc.value.status == 403
    for operation in (
        lambda: store.update("alice", BUILTIN_THEME_ID, {"schemaVersion": 1, "expectedRevision": 0, "name": "覆盖"}),
        lambda: store.delete("alice", BUILTIN_THEME_ID, {"expectedRevision": 0}),
    ):
        with pytest.raises(ThemeStoreError) as exc:
            operation()
        assert exc.value.status == 403
    assert not store.accounts_dir.exists()


def test_foreign_ids_cannot_be_copied_updated_selected_or_deleted(store):
    theme_id = store.create("alice", create_input())["themes"][1]["id"]
    for operation in (
        lambda: store.create("bob", create_input(sourceId=theme_id)),
        lambda: store.update("bob", theme_id, {"schemaVersion": 1, "expectedRevision": 0, "name": "接管"}),
        lambda: store.select("bob", {"themeId": theme_id, "expectedRevision": 0}),
        lambda: store.delete("bob", theme_id, {"expectedRevision": 0}),
    ):
        with pytest.raises(ThemeStoreError) as exc:
            operation()
        assert exc.value.status == 404


def test_concurrent_store_instances_cannot_lose_updates(store):
    barrier = threading.Barrier(2)

    def create(index):
        other = ThemeStore(store.accounts_dir)
        barrier.wait()
        try:
            return other.create("alice", create_input(name=f"主题 {index}"))["revision"]
        except ThemeStoreError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, [1, 2])) == [1, 409]
    library = store.list_for_account("alice")
    assert library["revision"] == 1 and len(library["themes"]) == 2


def test_atomic_replace_failure_preserves_data_and_selection(store, monkeypatch):
    library = store.create("alice", create_input())
    theme_id = library["themes"][1]["id"]
    path = next(store.accounts_dir.glob("*.json"))
    before = path.read_bytes()

    def fail_replace(source, target):
        staged = json.loads(Path(source).read_text(encoding="utf-8"))
        assert staged["selectedThemeId"] == theme_id
        assert staged["themes"][0]["name"] == "新名字"
        raise OSError("disk unavailable")

    monkeypatch.setattr(theme_store.os, "replace", fail_replace)
    with pytest.raises(ThemeStoreError) as exc:
        store.update("alice", theme_id, {"schemaVersion": 1, "expectedRevision": 1, "name": "新名字", "activate": True})
    assert exc.value.code == "theme_store_write_failed"
    assert path.read_bytes() == before
    assert store.list_for_account("alice") == library
    assert list(store.accounts_dir.glob("*.tmp")) == []


@pytest.mark.parametrize("damage", ["json", "encoding", "schema", "unknown", "token", "readonly", "time"])
def test_damaged_file_is_preserved_and_write_is_blocked(store, damage):
    store.create("alice", create_input())
    path = next(store.accounts_dir.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    if damage == "json":
        raw = b'{"schemaVersion":'
    elif damage == "encoding":
        raw = b"\xff\xfe\x00"
    else:
        if damage == "schema":
            data["schemaVersion"] = 2
        elif damage == "unknown":
            data["futureField"] = True
        elif damage == "token":
            data["themes"][0]["appearance"]["colors"]["overrides"]["future.token"] = "#FFFFFFFF"
        elif damage == "readonly":
            data["themes"][0]["readonly"] = True
        elif damage == "time":
            data["themes"][0]["updatedAt"] = "invalid"
        raw = json.dumps(data).encode("utf-8")
    path.write_bytes(raw)
    library = store.list_for_account("alice")
    assert "原文件已保留" in library["error"]
    assert len(library["themes"]) == 1 and library["selectedThemeId"] == BUILTIN_THEME_ID
    with pytest.raises(ThemeStoreError) as exc:
        store.create("alice", create_input())
    assert exc.value.code == "theme_store_unreadable"
    assert path.read_bytes() == raw


def test_stale_selected_id_falls_back_without_discarding_personal_themes(store):
    store.create("alice", create_input())
    path = next(store.accounts_dir.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["selectedThemeId"] = "missing-theme"
    path.write_text(json.dumps(data), encoding="utf-8")
    library = store.list_for_account("alice")
    assert library["selectedThemeId"] == BUILTIN_THEME_ID and len(library["themes"]) == 2
    assert "error" not in library
