from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.web.theme_store import BUILTIN_THEME_ID, ThemeStore, ThemeStoreError


PRESET_NAMES = ["纸感日间", "雾蓝清晨", "青松纸笺", "暮海深蓝", "紫雾夜航"]


@pytest.fixture
def store(tmp_path: Path) -> ThemeStore:
    return ThemeStore(tmp_path / "themes" / "library.json")


def test_packaged_presets_are_loaded_as_readonly_themes(store: ThemeStore) -> None:
    library = store.list_library()

    assert [theme["name"] for theme in library["themes"]] == PRESET_NAMES
    assert all(theme["readonly"] is True for theme in library["themes"])
    assert library["selectedThemeId"] == BUILTIN_THEME_ID
    assert library["revision"] == 0
    assert not store.library_path.exists()

    library["themes"][1]["name"] = "外部修改"
    assert store.list_library()["themes"][1]["name"] == "雾蓝清晨"


def test_runtime_library_only_keeps_selection_and_cannot_override_presets(store: ThemeStore) -> None:
    preset_id = store.list_library()["themes"][2]["id"]
    store.library_path.parent.mkdir(parents=True)
    store.library_path.write_text(json.dumps({
        "schemaVersion": 1,
        "scope": "global",
        "revision": 41,
        "selectedThemeId": preset_id,
        "themes": [{
            "id": preset_id,
            "name": "被运行态覆盖",
            "readonly": False,
        }],
    }), encoding="utf-8")

    library = store.list_library()
    assert library["revision"] == 41
    assert library["selectedThemeId"] == preset_id
    assert library["themes"][2]["name"] == "青松纸笺"
    assert all(theme["readonly"] is True for theme in library["themes"])


def test_selection_is_the_only_persisted_theme_state(store: ThemeStore) -> None:
    library = store.list_library()
    selected_id = library["themes"][-1]["id"]

    selected = store.select({"themeId": selected_id, "expectedRevision": 0})

    assert selected["revision"] == 1
    assert selected["selectedThemeId"] == selected_id
    persisted = json.loads(store.library_path.read_text(encoding="utf-8"))
    assert persisted["selectedThemeId"] == selected_id
    assert all(theme["readonly"] is True for theme in persisted["themes"])


@pytest.mark.parametrize(
    "operation",
    [
        lambda store: store.create({}),
        lambda store: store.import_themes({}),
        lambda store: store.update(BUILTIN_THEME_ID, {}),
        lambda store: store.delete(BUILTIN_THEME_ID, {}),
    ],
)
def test_theme_mutations_are_rejected_without_creating_runtime_files(store: ThemeStore, operation) -> None:
    with pytest.raises(ThemeStoreError) as exc:
        operation(store)

    assert exc.value.status == 403
    assert exc.value.code == "theme_readonly"
    assert not store.library_path.exists()


def test_packaged_preset_file_contains_only_builtin_illustration_assets() -> None:
    path = Path(__file__).parents[1] / "bot" / "web" / "theme_presets.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert [theme["name"] for theme in data["themes"]] == PRESET_NAMES
    for theme in data["themes"]:
        for scene in theme["appearance"]["illustrations"]["scenes"].values():
            assert all(layer["asset"]["kind"] == "builtin" for layer in scene["layers"])
