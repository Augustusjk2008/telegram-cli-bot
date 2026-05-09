from pathlib import Path

from bot.assistant.shared.json_store import read_json_file, write_json_file
from bot.assistant.shared.text import clip_text, parse_iso_datetime


def test_clip_text_limits_length():
    assert clip_text("abcdef", limit=3) == "abc"


def test_parse_iso_datetime_returns_none_for_invalid_value():
    assert parse_iso_datetime("not-a-date") is None


def test_json_store_round_trip(tmp_path: Path):
    path = tmp_path / "data.json"
    write_json_file(path, {"ok": True})
    assert read_json_file(path) == {"ok": True}
