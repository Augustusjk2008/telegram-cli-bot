from __future__ import annotations

import codecs
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_TEXT_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "big5",
    "shift_jis",
)

_BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str


class UnsupportedTextEncoding(ValueError):
    pass


_HEAD_READ_BLOCK_SIZE = 4096


def normalize_text_encoding(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if not normalized:
        return None
    aliases = {
        "utf8": "utf-8",
        "utf8-sig": "utf-8-sig",
        "utf16": "utf-16",
        "utf16-le": "utf-16-le",
        "utf16-be": "utf-16-be",
        "gbk": "gb18030",
        "gb2312": "gb18030",
        "sjis": "shift_jis",
        "shift-jis": "shift_jis",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_TEXT_ENCODINGS:
        raise UnsupportedTextEncoding(normalized)
    return normalized


def _looks_binary(text: str) -> bool:
    if "\x00" in text:
        return True
    if not text:
        return False
    control_count = sum(1 for char in text if ord(char) < 32 and char not in "\t\r\n\f\b")
    return control_count / max(len(text), 1) > 0.02


def _decode_with_encoding(data: bytes, encoding: str) -> DecodedText | None:
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    if _looks_binary(text):
        return None
    return DecodedText(text=text, encoding=encoding)


def _decode_prefix_with_encoding(data: bytes, encoding: str) -> DecodedText | None:
    try:
        decoder = codecs.getincrementaldecoder(encoding)()
        text = decoder.decode(data, final=False)
    except (LookupError, UnicodeDecodeError):
        return None
    if _looks_binary(text):
        return None
    return DecodedText(text=text, encoding=encoding)


def _looks_like_utf16_without_bom(data: bytes, encoding: str) -> bool:
    if len(data) < 8 or len(data) % 2 != 0:
        return False
    if encoding == "utf-16-le":
        probe = data[1::2]
    else:
        probe = data[0::2]
    return probe.count(0) / max(len(probe), 1) >= 0.6


def decode_text_bytes(data: bytes, requested_encoding: str | None = None) -> DecodedText:
    requested = normalize_text_encoding(requested_encoding)
    if requested:
        decoded = _decode_with_encoding(data, requested)
        if decoded is None:
            raise UnsupportedTextEncoding(requested)
        return decoded

    for bom, encoding in _BOM_ENCODINGS:
        if data.startswith(bom):
            decoded = _decode_with_encoding(data, encoding)
            if decoded is None:
                raise UnsupportedTextEncoding(encoding)
            return decoded

    for encoding in ("utf-8", "gb18030", "big5", "shift_jis"):
        decoded = _decode_with_encoding(data, encoding)
        if decoded is not None:
            return decoded
    for encoding in ("utf-16-le", "utf-16-be"):
        if not _looks_like_utf16_without_bom(data, encoding):
            continue
        decoded = _decode_with_encoding(data, encoding)
        if decoded is not None:
            return decoded
    raise UnsupportedTextEncoding("")


def decode_text_prefix_bytes(data: bytes, requested_encoding: str | None = None) -> DecodedText:
    requested = normalize_text_encoding(requested_encoding)
    if requested:
        decoded = _decode_prefix_with_encoding(data, requested)
        if decoded is None:
            raise UnsupportedTextEncoding(requested)
        return decoded

    for bom, encoding in _BOM_ENCODINGS:
        if data.startswith(bom):
            decoded = _decode_prefix_with_encoding(data, encoding)
            if decoded is None:
                raise UnsupportedTextEncoding(encoding)
            return decoded

    for encoding in ("utf-8", "gb18030", "big5", "shift_jis"):
        decoded = _decode_prefix_with_encoding(data, encoding)
        if decoded is not None:
            return decoded
    for encoding in ("utf-16-le", "utf-16-be"):
        if not _looks_like_utf16_without_bom(data, encoding):
            continue
        decoded = _decode_prefix_with_encoding(data, encoding)
        if decoded is not None:
            return decoded
    raise UnsupportedTextEncoding("")


def read_text_file(path: str | Path, requested_encoding: str | None = None) -> DecodedText:
    return decode_text_bytes(Path(path).read_bytes(), requested_encoding)


def _read_bytes_prefix(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _read_text_file_head_requested(path: Path, lines: int, requested_encoding: str) -> DecodedText:
    encoding = normalize_text_encoding(requested_encoding)
    if encoding is None:
        raise UnsupportedTextEncoding(requested_encoding)

    newline_count = 0
    consumed = b""
    with path.open("rb") as handle:
        while newline_count < lines:
            chunk = handle.read(_HEAD_READ_BLOCK_SIZE)
            if not chunk:
                break
            consumed += chunk
            newline_count += chunk.count(b"\n")

    decoded = _decode_prefix_with_encoding(consumed, encoding)
    if decoded is None:
        raise UnsupportedTextEncoding(encoding)
    return decoded


def read_text_file_head(
    path: str | Path,
    lines: int,
    requested_encoding: str | None = None,
) -> DecodedText:
    target = Path(path)
    line_limit = max(0, int(lines))
    if line_limit <= 0:
        return DecodedText(text="", encoding=normalize_text_encoding(requested_encoding) or "utf-8")

    requested = normalize_text_encoding(requested_encoding)
    if requested:
        return _read_text_file_head_requested(target, line_limit, requested)

    prefix_limit = max(_HEAD_READ_BLOCK_SIZE, line_limit * 256)
    prefix = _read_bytes_prefix(target, prefix_limit)
    detected = decode_text_prefix_bytes(prefix)
    if detected.text.count("\n") >= line_limit or len(prefix) < prefix_limit:
        return detected
    return _read_text_file_head_requested(target, line_limit, detected.encoding)


def write_text_file(path: str | Path, content: str, encoding: str | None) -> None:
    target_encoding = normalize_text_encoding(encoding) or "utf-8"
    Path(path).write_bytes(content.encode(target_encoding))
