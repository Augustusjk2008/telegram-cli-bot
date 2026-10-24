from __future__ import annotations

import copy
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
    return ThemeStore(tmp_path / "themes" / "library.json")


def test_theme_path_follows_active_data_root_without_creating_it(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    monkeypatch.setenv("TCB_DATA_DIR", str(root))
    assert runtime_paths.get_theme_accounts_dir() == root / "themes" / "accounts"
    assert runtime_paths.get_theme_library_path() == root / "themes" / "library.json"
    assert ThemeStore().library_path == runtime_paths.get_theme_library_path()
    assert ThemeStore().legacy_accounts_dir == runtime_paths.get_theme_accounts_dir()
    assert not root.exists()


def test_global_crud_copy_normalization_and_selection_persist(store):
    assert store.list_library()["selectedThemeId"] == BUILTIN_THEME_ID
    assert not store.library_path.parent.exists()
    library = store.create(create_input(activate=True, appearance={"colors": {
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
    reloaded = ThemeStore(store.library_path)
    assert reloaded.list_library() == library
    library = reloaded.create(create_input(expectedRevision=1, sourceId=theme_id, name="复制"))
    copied_id = library["themes"][2]["id"]
    assert library["selectedThemeId"] == theme_id
    assert library["themes"][2]["appearance"] == first["appearance"]
    library = store.update(copied_id, {"schemaVersion": 1, "expectedRevision": 2, "name": "重命名",
        "activate": True, "appearance": {"colors": {"scheme": "light", "overrides": {"border": "#abcdef00"}}}})
    assert library["revision"] == 3 and library["selectedThemeId"] == copied_id
    assert library["themes"][2]["id"] == copied_id and library["themes"][2]["version"] == 2
    assert library["themes"][2]["appearance"]["colors"]["overrides"] == {"border": "#ABCDEF00"}
    library = store.update(theme_id, {"schemaVersion": 1, "expectedRevision": 3, "name": "另一个主题"})
    assert library["selectedThemeId"] == copied_id
    library = store.select({"themeId": theme_id, "expectedRevision": 4})
    assert library["selectedThemeId"] == theme_id
    library = store.delete(copied_id, {"expectedRevision": 5})
    assert library["selectedThemeId"] == theme_id
    library = store.delete(theme_id, {"expectedRevision": 6})
    assert library["revision"] == 7 and library["selectedThemeId"] == BUILTIN_THEME_ID
    assert len(library["themes"]) == 1
    assert reloaded.list_library() == library
    stored = json.loads(store.library_path.read_text(encoding="utf-8"))
    assert stored["themes"] == []


def test_chat_typography_is_stored_with_the_theme(store):
    typography = {
        "chatBodyFontFamily": "serif",
        "chatBodyFontSize": "large",
        "chatBodyLineHeight": "relaxed",
        "chatBodyParagraphSpacing": "tight",
    }
    library = store.create(create_input(appearance={
        "colors": {"scheme": "light", "overrides": {}},
        "typography": typography,
    }))
    assert library["themes"][1]["appearance"]["typography"] == typography
    assert ThemeStore(store.library_path).list_library()["themes"][1]["appearance"]["typography"] == typography


def test_library_results_are_detached(store):
    library = store.create(create_input())
    library["themes"][1]["name"] = "外部修改"
    assert store.list_library()["themes"][1]["name"] == "我的主题"
    assert not store.legacy_accounts_dir.exists()


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
    {"appearance": {"colors": {"scheme": "light", "overrides": {}}, "typography": {
        "chatBodyFontFamily": "serif", "chatBodyFontSize": "medium", "chatBodyLineHeight": "normal",
    }}},
    {"appearance": {"colors": {"scheme": "light", "overrides": {}}, "typography": {
        "chatBodyFontFamily": "serif", "chatBodyFontSize": "medium", "chatBodyLineHeight": "normal",
        "chatBodyParagraphSpacing": "normal", "future": "value",
    }}},
])
def test_invalid_inputs_never_write(store, changes):
    with pytest.raises(ThemeStoreError) as exc:
        store.create(create_input(**changes))
    assert exc.value.status == 400
    assert store.list_library()["revision"] == 0
    assert not store.library_path.parent.exists()


@pytest.mark.parametrize("field", ["schemaVersion", "expectedRevision", "sourceId", "name"])
def test_missing_required_create_fields_are_rejected(store, field):
    payload = create_input()
    del payload[field]
    with pytest.raises(ThemeStoreError, match="缺少字段"):
        store.create(payload)


def test_builtin_is_immutable(store):
    for operation in (
        lambda: store.update(BUILTIN_THEME_ID, {"schemaVersion": 1, "expectedRevision": 0, "name": "覆盖"}),
        lambda: store.delete(BUILTIN_THEME_ID, {"expectedRevision": 0}),
    ):
        with pytest.raises(ThemeStoreError) as exc:
            operation()
        assert exc.value.status == 403
    assert not store.library_path.parent.exists()


def test_missing_ids_cannot_be_copied_updated_selected_or_deleted(store):
    theme_id = "theme_" + "0" * 32
    for operation in (
        lambda: store.create(create_input(sourceId=theme_id)),
        lambda: store.update(theme_id, {"schemaVersion": 1, "expectedRevision": 0, "name": "接管"}),
        lambda: store.select({"themeId": theme_id, "expectedRevision": 0}),
        lambda: store.delete(theme_id, {"expectedRevision": 0}),
    ):
        with pytest.raises(ThemeStoreError) as exc:
            operation()
        assert exc.value.status == 404


def test_concurrent_store_instances_cannot_lose_updates(store):
    barrier = threading.Barrier(2)

    def create(index):
        other = ThemeStore(store.library_path)
        barrier.wait()
        try:
            return other.create(create_input(name=f"主题 {index}"))["revision"]
        except ThemeStoreError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, [1, 2])) == [1, 409]
    library = store.list_library()
    assert library["revision"] == 1 and len(library["themes"]) == 2


def test_atomic_replace_failure_preserves_data_and_selection(store, monkeypatch):
    library = store.create(create_input())
    theme_id = library["themes"][1]["id"]
    path = store.library_path
    before = path.read_bytes()

    def fail_replace(source, target):
        staged = json.loads(Path(source).read_text(encoding="utf-8"))
        assert staged["selectedThemeId"] == theme_id
        assert staged["themes"][0]["name"] == "新名字"
        raise OSError("disk unavailable")

    monkeypatch.setattr(theme_store.os, "replace", fail_replace)
    with pytest.raises(ThemeStoreError) as exc:
        store.update(theme_id, {"schemaVersion": 1, "expectedRevision": 1, "name": "新名字", "activate": True})
    assert exc.value.code == "theme_store_write_failed"
    assert path.read_bytes() == before
    assert store.list_library() == library
    assert list(store.library_path.parent.glob("*.tmp")) == []


@pytest.mark.parametrize("damage", ["json", "encoding", "schema", "unknown", "token", "readonly", "time"])
def test_damaged_file_is_preserved_and_write_is_blocked(store, damage):
    store.create(create_input())
    path = store.library_path
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
    library = store.list_library()
    assert "原文件已保留" in library["error"]
    assert len(library["themes"]) == 1 and library["selectedThemeId"] == BUILTIN_THEME_ID
    with pytest.raises(ThemeStoreError) as exc:
        store.create(create_input())
    assert exc.value.code == "theme_store_unreadable"
    assert path.read_bytes() == raw


def test_stale_selected_id_falls_back_without_discarding_custom_themes(store):
    store.create(create_input())
    path = store.library_path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["selectedThemeId"] = "missing-theme"
    path.write_text(json.dumps(data), encoding="utf-8")
    library = store.list_library()
    assert library["selectedThemeId"] == BUILTIN_THEME_ID and len(library["themes"]) == 2
    assert "error" not in library


def legacy_theme(index, **changes):
    return {
        "schemaVersion": 1, "id": f"theme_{index:032x}", "name": f"主题 {index}",
        "baseId": BUILTIN_THEME_ID, "appearance": {"colors": {
            "scheme": "dark", "overrides": {"surface.base": "#123456FF", "border": "#ABCDEF80"},
        }}, "readonly": False, "updatedAt": "2026-10-21T12:30:00+08:00", "version": index,
        **changes,
    }


def write_legacy(store, filename, themes, **changes):
    store.legacy_accounts_dir.mkdir(parents=True, exist_ok=True)
    path = store.legacy_accounts_dir / filename
    path.write_text(json.dumps({
        "schemaVersion": 1, "revision": 12, "selectedThemeId": themes[0]["id"] if themes else BUILTIN_THEME_ID,
        "themes": themes, **changes,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_migration_preserves_four_local_themes_and_other_accounts_once(store):
    local = [legacy_theme(index) for index in range(1, 5)]
    other = legacy_theme(5, name=local[0]["name"])
    # Filenames sort deterministically regardless of creation order.
    other_path = write_legacy(store, "b" * 64 + ".json", [local[0], other])
    local_path = write_legacy(store, "a" * 64 + ".json", local)
    originals = {path: path.read_bytes() for path in (local_path, other_path)}

    library = store.list_library()
    assert library["scope"] == "global" and "accountId" not in library
    assert library["themes"][1:] == [*local, other]
    assert library["selectedThemeId"] == BUILTIN_THEME_ID and library["revision"] == 0
    before = store.library_path.read_bytes()
    assert store.list_library() == ThemeStore(store.library_path).list_library() == library
    assert store.library_path.read_bytes() == before
    assert all(path.read_bytes() == raw for path, raw in originals.items())

    # Once global storage exists, later writes from old versions are never imported.
    write_legacy(store, "c" * 64 + ".json", [legacy_theme(6)])
    other_path.write_bytes(b"broken legacy file")
    assert ThemeStore(store.library_path).list_library() == library
    selected = store.select({"themeId": local[3]["id"], "expectedRevision": 0})
    assert selected["revision"] == 1 and selected["selectedThemeId"] == local[3]["id"]


def test_id_conflicts_preserve_distinct_versions_and_deduplicate_each_variant(store, tmp_path):
    original = legacy_theme(1)
    conflict = legacy_theme(1, version=3, name="同 ID 的另一份", appearance={
        "colors": {"scheme": "light", "overrides": {"accent": "#AABBCCFF"}},
    })
    paths = [write_legacy(store, filename, themes) for filename, themes in (
        ("c.json", [conflict]), ("b.json", [conflict]), ("a.json", [original]),
    )]
    originals = {path: path.read_bytes() for path in paths}
    library = store.list_library()
    assert len(library["themes"]) == 3 and library["themes"][1] == original
    duplicate = library["themes"][2]
    assert duplicate["id"] != original["id"]
    assert {**duplicate, "id": original["id"]} == conflict
    assert all(path.read_bytes() == raw for path, raw in originals.items())

    isolated = ThemeStore(tmp_path / "another-root" / "library.json", legacy_accounts_dir=store.legacy_accounts_dir)
    assert isolated.list_library() == library
    assert ThemeStore(store.library_path).list_library() == library


@pytest.mark.parametrize("operation", ["list", "create"])
def test_first_access_migrates_all_sources_before_use(store, operation):
    theme = legacy_theme(1)
    source = write_legacy(store, "old.json", [theme])
    before = source.read_bytes()
    if operation == "list":
        library = store.list_library()
        assert library["revision"] == 0
    else:
        library = store.create(create_input(sourceId=theme["id"], activate=True))
        assert library["revision"] == 1
        assert library["selectedThemeId"] == library["themes"][2]["id"]
        assert library["themes"][2]["appearance"] == theme["appearance"]
    assert library["themes"][1] == theme and source.read_bytes() == before


@pytest.mark.parametrize("damage", ["json", "encoding", "schema", "theme_schema", "token", "duplicate_id"])
def test_damaged_legacy_source_blocks_entire_migration_and_preserves_sources(store, damage):
    valid = write_legacy(store, "a.json", [legacy_theme(1)])
    invalid = write_legacy(store, "b.json", [legacy_theme(2)])
    data = json.loads(invalid.read_text(encoding="utf-8"))
    if damage == "json":
        raw = b'{"schemaVersion":'
    elif damage == "encoding":
        raw = b"\xff\xfe\x00"
    else:
        if damage == "schema":
            data["schemaVersion"] = 2
        elif damage == "theme_schema":
            data["themes"][0]["schemaVersion"] = 2
        elif damage == "token":
            data["themes"][0]["appearance"]["colors"]["overrides"]["unknown"] = "#FFFFFFFF"
        elif damage == "duplicate_id":
            data["themes"].append(copy.deepcopy(data["themes"][0]))
        raw = json.dumps(data).encode("utf-8")
    invalid.write_bytes(raw)
    originals = {path: path.read_bytes() for path in (valid, invalid)}
    library = store.list_library()
    assert "原文件已保留" in library["error"] and len(library["themes"]) == 1
    assert library["scope"] == "global"
    with pytest.raises(ThemeStoreError) as exc:
        store.create(create_input())
    assert exc.value.code == "theme_store_unreadable"
    assert not store.library_path.exists()
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_failed_atomic_migration_publishes_nothing_and_can_retry(store, monkeypatch):
    paths = [write_legacy(store, f"{index}.json", [legacy_theme(index)]) for index in (1, 2)]
    originals = {path: path.read_bytes() for path in paths}
    replace = theme_store.os.replace

    def fail_replace(source, target):
        staged = json.loads(Path(source).read_text(encoding="utf-8"))
        assert len(staged["themes"]) == 2
        assert staged["selectedThemeId"] == BUILTIN_THEME_ID
        raise OSError("disk unavailable")

    monkeypatch.setattr(theme_store.os, "replace", fail_replace)
    with pytest.raises(ThemeStoreError) as exc:
        store.list_library()
    assert exc.value.code == "theme_store_write_failed"
    assert not store.library_path.exists()
    assert list(store.library_path.parent.glob("*.tmp")) == []
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    monkeypatch.setattr(theme_store.os, "replace", replace)
    library = store.list_library()
    assert library["themes"][1:] == [legacy_theme(1), legacy_theme(2)]
    assert ThemeStore(store.library_path).list_library() == library


def test_existing_global_library_is_authoritative_even_when_legacy_data_is_invalid(store):
    library = store.create(create_input(activate=True))
    before = store.library_path.read_bytes()
    legacy = write_legacy(store, "old.json", [legacy_theme(1)])
    legacy.write_bytes(b"invalid legacy JSON")
    assert ThemeStore(store.library_path).list_library() == library
    assert store.library_path.read_bytes() == before

    store.library_path.write_bytes(b'{"schemaVersion":2}')
    before = store.library_path.read_bytes()
    write_legacy(store, "old.json", [legacy_theme(1)])
    assert "error" in store.list_library()
    with pytest.raises(ThemeStoreError):
        store.create(create_input())
    assert store.library_path.read_bytes() == before
