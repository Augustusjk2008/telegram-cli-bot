from __future__ import annotations

import math
from pathlib import Path

DEFAULT_MAX_PREVIEW_BYTES = 16 * 1024
DEFAULT_BYTES_PER_ROW = 16
DEFAULT_ENTROPY_BUCKETS = 48


def _ascii(byte: int) -> str:
    return chr(byte) if 32 <= byte <= 126 else "."


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _entropy(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    counts = [0] * 256
    for byte in chunk:
        counts[byte] += 1
    result = 0.0
    total = len(chunk)
    for count in counts:
        if count:
            probability = count / total
            result -= probability * math.log2(probability)
    return round(max(0.0, min(1.0, result / 8.0)), 4)


def _rows(content: bytes, bytes_per_row: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for offset in range(0, len(content), bytes_per_row):
        chunk = content[offset:offset + bytes_per_row]
        rows.append({
            "offset": offset,
            "hex": [f"{byte:02X}" for byte in chunk],
            "ascii": "".join(_ascii(byte) for byte in chunk),
        })
    return rows


def _entropy_buckets(content: bytes, bucket_count: int) -> list[dict[str, object]]:
    if not content:
        return [{"index": 0, "startOffset": 0, "endOffset": 0, "entropy": 0.0}]
    bucket_count = max(1, min(bucket_count, len(content)))
    step = max(1, math.ceil(len(content) / bucket_count))
    buckets: list[dict[str, object]] = []
    for index, start in enumerate(range(0, len(content), step)):
        end = min(len(content), start + step)
        buckets.append({
            "index": index,
            "startOffset": start,
            "endOffset": end,
            "entropy": _entropy(content[start:end]),
        })
    return buckets


def parse_hex_document(path: str, content: bytes, config: dict[str, object] | None = None) -> dict[str, object]:
    current_config = config or {}
    max_preview_bytes = _clamp_int(current_config.get("maxPreviewBytes"), DEFAULT_MAX_PREVIEW_BYTES, 256, 256 * 1024)
    bytes_per_row = _clamp_int(current_config.get("bytesPerRow"), DEFAULT_BYTES_PER_ROW, 8, 32)
    entropy_bucket_count = _clamp_int(current_config.get("entropyBuckets"), DEFAULT_ENTROPY_BUCKETS, 8, 256)

    preview = content[:max_preview_bytes]
    truncated = len(content) > len(preview)

    return {
        "path": path,
        "title": Path(path).name,
        "fileSizeBytes": len(content),
        "previewBytes": len(preview),
        "bytesPerRow": bytes_per_row,
        "truncated": truncated,
        "statsText": f"{len(content)} B · preview {len(preview)} B",
        "entropyBuckets": _entropy_buckets(preview, entropy_bucket_count),
        "rows": _rows(preview, bytes_per_row),
    }
