from __future__ import annotations

import os

import pytest

from bot.web import files_service


def _entries(root, **kwargs):
    listing = files_service.list_directory_entries(str(root), **kwargs)
    return {item["name"]: item for item in listing["entries"]}


def test_listing_reports_single_child_directory_chains(tmp_path):
    (tmp_path / "java" / "com" / "acme" / "app").mkdir(parents=True)
    (tmp_path / "java" / "com" / "acme" / "app" / "Main.java").write_text("", encoding="utf-8")
    (tmp_path / "java" / "com" / "acme" / "app" / "Util.java").write_text("", encoding="utf-8")
    (tmp_path / "mixed" / "only").mkdir(parents=True)
    (tmp_path / "mixed" / "note.txt").write_text("", encoding="utf-8")
    (tmp_path / "leaf").mkdir()
    (tmp_path / "leaf" / "note.txt").write_text("", encoding="utf-8")
    (tmp_path / "hollow" / "inner").mkdir(parents=True)

    entries = _entries(tmp_path, include_child_counts=True)

    assert entries["java"]["child_count"] == 1
    assert entries["java"]["compact_chain"] == [
        {"name": "com", "child_count": 1},
        {"name": "acme", "child_count": 1},
        {"name": "app", "child_count": 2},
    ]
    assert entries["hollow"]["compact_chain"] == [{"name": "inner", "child_count": 0}]
    assert "compact_chain" not in entries["mixed"]
    assert "compact_chain" not in entries["leaf"]
    assert "compact_chain" not in _entries(tmp_path)["java"]


def test_listing_never_follows_a_link_into_a_chain(tmp_path):
    (tmp_path / "loop").mkdir()
    try:
        os.symlink(tmp_path / "loop", tmp_path / "loop" / "again", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    entry = _entries(tmp_path, include_child_counts=True)["loop"]

    assert entry["child_count"] == 1
    assert "compact_chain" not in entry
