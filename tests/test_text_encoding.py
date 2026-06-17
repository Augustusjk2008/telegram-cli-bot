from __future__ import annotations

from pathlib import Path

import bot.web.text_encoding as text_encoding


def test_read_text_file_head_requested_handles_partial_utf8_char(tmp_path, monkeypatch):
    monkeypatch.setattr(text_encoding, "_HEAD_READ_BLOCK_SIZE", 6)

    path = Path(tmp_path) / "sample.md"
    path.write_bytes("a\n测试\n".encode("utf-8-sig"))

    decoded = text_encoding._read_text_file_head_requested(path, 1, "utf-8-sig")

    assert decoded.encoding == "utf-8-sig"
    assert decoded.text == "a\n"


def test_read_text_file_head_detects_partial_utf8_prefix(tmp_path, monkeypatch):
    path = Path(tmp_path) / "sample.md"
    content = "\n".join(f"line{i}-{'x' * 60}测" for i in range(90)) + "\n"
    path.write_bytes(content.encode("utf-8-sig"))

    decoded = text_encoding.read_text_file_head(path, 80)

    assert decoded.encoding == "utf-8-sig"
    assert decoded.text.startswith("line0-")
    assert len(decoded.text.splitlines()) >= 80
