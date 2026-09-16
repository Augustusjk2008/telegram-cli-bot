from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from bot.web.translation_config import TranslationConfigError, TranslationConfigStore


API_CONFIG = {
    "base_url": "https://provider.test/v1",
    "api_key": "sk-translation-secret",
    "model": "translator",
}


def test_config_persists_outside_repo_with_frozen_redacted_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path))
    store = TranslationConfigStore()
    initial = store.get_config()
    assert not initial.translate_user_enabled and not initial.translate_assistant_enabled
    assert initial.request_timeout_seconds == 15
    assert store.path == tmp_path / "chat-translation" / "config.json"
    assert not store.path.exists()

    public = store.update({**API_CONFIG, "translate_user_enabled": True})
    snapshot = store.get_config()
    with pytest.raises(FrozenInstanceError):
        snapshot.model = "changed"
    assert not initial.translate_user_enabled
    assert snapshot.translate_user_enabled and not snapshot.translate_assistant_enabled
    assert "api_key" not in public
    assert public["api_key_set"] is True
    assert API_CONFIG["api_key"] not in repr(snapshot)
    assert API_CONFIG["api_key"] not in json.dumps(store.get_public_config())
    assert TranslationConfigStore(store.path).get_config() == snapshot

    for payload in ({"model": "next"}, {"api_key": ""}, {"api_key": None}):
        assert store.update(payload)["api_key_set"] is True
        assert store.get_config().api_key == API_CONFIG["api_key"]
    assert snapshot.model == "translator"
    with pytest.raises(TranslationConfigError):
        store.update({"clear_api_key": True})
    public = store.update({"translate_user_enabled": False, "clear_api_key": True})
    assert public["api_key_set"] is False
    assert TranslationConfigStore(store.path).get_config().api_key == ""


@pytest.mark.parametrize("direction", ["user", "assistant"])
def test_each_direction_requires_only_its_language_and_api_config(tmp_path, direction):
    store = TranslationConfigStore(tmp_path / "config.json")
    enabled = f"translate_{direction}_enabled"
    language = f"{direction}_target_language"
    other_language = "assistant_target_language" if direction == "user" else "user_target_language"
    with pytest.raises(TranslationConfigError):
        store.update({enabled: True})
    with pytest.raises(TranslationConfigError):
        store.update({**API_CONFIG, enabled: True, language: ""})
    store.update({**API_CONFIG, enabled: True, language: "阿拉伯语（埃及口语）", other_language: ""})
    assert getattr(store.get_config(), language) == "阿拉伯语（埃及口语）"
    for field in API_CONFIG:
        payload = {"clear_api_key": True} if field == "api_key" else {field: ""}
        with pytest.raises(TranslationConfigError):
            store.update(payload)


@pytest.mark.parametrize("payload", [
    {"translate_user_enabled": "false"},
    {"translate_assistant_enabled": 1},
    {"clear_api_key": "true"},
    {"request_timeout_seconds": 0},
    {"request_timeout_seconds": -1},
    {"request_timeout_seconds": float("nan")},
    {"request_timeout_seconds": float("inf")},
    {"request_timeout_seconds": True},
    {"base_url": "file:///tmp/provider"},
    {"base_url": "https://name:secret@provider.test/v1"},
    {"base_url": "https://provider.test/v1?key=secret"},
    {"model": []},
])
def test_invalid_updates_leave_snapshot_and_file_unchanged(tmp_path, payload):
    store = TranslationConfigStore(tmp_path / "config.json")
    store.update(API_CONFIG)
    original = store.get_config()
    persisted = store.path.read_bytes()
    with pytest.raises(TranslationConfigError):
        store.update({"assistant_target_language": "日语", **payload})
    assert store.get_config() is original
    assert store.path.read_bytes() == persisted


def test_failed_atomic_write_keeps_persisted_and_in_memory_config(tmp_path, monkeypatch):
    store = TranslationConfigStore(tmp_path / "config.json")
    store.update(API_CONFIG)
    original = store.get_config()
    persisted = store.path.read_bytes()

    def reject_replace(*args):
        raise OSError("write failed")

    monkeypatch.setattr("bot.web.translation_config.os.replace", reject_replace)
    with pytest.raises(OSError):
        store.update({"model": "changed"})
    assert store.get_config() is original
    assert store.path.read_bytes() == persisted
    assert list(tmp_path.iterdir()) == [store.path]


def test_malformed_persisted_config_does_not_expose_contents(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{"api_key": "sk-secret"', encoding="utf-8")
    with pytest.raises(TranslationConfigError) as caught:
        TranslationConfigStore(path)
    assert "sk-secret" not in str(caught.value)
