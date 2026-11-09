"""Portable quota-sample files for merging one quota curve across machines.

Quota percentages are account-wide, so samples taken on different machines
are observations of the same series: an import merges points and never sums.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .models import (
    CodexRateLimitSample,
    UsageProvider,
    datetime_from_epoch_milliseconds,
    datetime_from_epoch_seconds,
    day_number,
    epoch_milliseconds,
    epoch_seconds,
    normalize_origin_label,
    normalize_usage_provider,
)
from .store import IMPORTED_ORIGIN_FALLBACK


EXPORT_FORMAT = "orbit-quota-samples"
EXPORT_VERSION = 1
MAX_IMPORT_SAMPLES = 200_000
_MAX_TEXT_FIELD_LENGTH = 128
# 9999-12-30T00:00:00Z keeps a local-calendar day computable in every zone.
_MAX_EPOCH_SECONDS = 253_402_128_000
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class SampleDocumentError(ValueError):
    """The uploaded content is not a supported quota-sample export."""


@dataclass(frozen=True, slots=True)
class ParsedSampleDocument:
    samples: tuple[tuple[UsageProvider, CodexRateLimitSample], ...]
    invalid: int

    @property
    def total(self) -> int:
        return len(self.samples) + self.invalid


def local_origin_label() -> str:
    """Label this machine by its fixed-forwarding node ID, else its hostname."""

    try:
        from bot import config

        node_id = str(getattr(config, "TCB_NODE_ID", "") or "")
    except Exception:
        node_id = ""
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    return normalize_origin_label(node_id) or normalize_origin_label(hostname) or "local"


def export_filename(source: str, exported_at: datetime) -> str:
    safe_source = _FILENAME_UNSAFE.sub("-", source).strip("-.")
    stamp = exported_at.astimezone().strftime("%Y%m%d-%H%M%S")
    parts = ["orbit-quota-samples", safe_source, stamp] if safe_source else ["orbit-quota-samples", stamp]
    return "-".join(parts) + ".json"


def build_export_document(
    samples: Sequence[tuple[UsageProvider, CodexRateLimitSample]],
    *,
    source: str,
    exported_at: datetime,
) -> dict[str, Any]:
    """Serialize samples with exact integer timestamps so imports deduplicate."""

    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": exported_at.astimezone(timezone.utc).isoformat(),
        "source": source,
        "samples": [
            {
                "provider": provider,
                "limit_id": sample.limit_id,
                "window_minutes": sample.window_minutes,
                "sampled_at_ms": epoch_milliseconds(sample.sampled_at),
                "used_percent": sample.used_percent,
                "resets_at": epoch_seconds(sample.resets_at),
                "plan_type": sample.plan_type,
                "credits_balance": sample.credits_balance,
                # Imported samples keep the machine that originally took them.
                "origin": sample.origin or source,
            }
            for provider, sample in samples
        ],
    }


def parse_import_document(document: object) -> ParsedSampleDocument:
    """Validate an export file; malformed rows are counted and skipped."""

    if not isinstance(document, Mapping) or document.get("format") != EXPORT_FORMAT:
        raise SampleDocumentError("不是 Orbit 额度样本导出文件")
    version = document.get("version")
    if type(version) is not int or version < 1:
        raise SampleDocumentError("额度样本文件版本无效")
    if version > EXPORT_VERSION:
        raise SampleDocumentError("额度样本文件来自更新的 Orbit 版本，请先升级本机")
    raw_samples = document.get("samples")
    if not isinstance(raw_samples, list):
        raise SampleDocumentError("额度样本文件缺少 samples 列表")
    if len(raw_samples) > MAX_IMPORT_SAMPLES:
        raise SampleDocumentError(f"单次最多导入 {MAX_IMPORT_SAMPLES} 条额度样本")
    fallback_origin = normalize_origin_label(document.get("source")) or IMPORTED_ORIGIN_FALLBACK
    samples: list[tuple[UsageProvider, CodexRateLimitSample]] = []
    invalid = 0
    for raw_sample in raw_samples:
        parsed = _parse_sample(raw_sample, fallback_origin)
        if parsed is None:
            invalid += 1
        else:
            samples.append(parsed)
    return ParsedSampleDocument(samples=tuple(samples), invalid=invalid)


def _strict_int(value: object, maximum: int) -> int | None:
    if type(value) is not int or not 0 <= value <= maximum:
        return None
    return value


def _bounded_text(value: object) -> bool:
    return isinstance(value, str) and len(value) <= _MAX_TEXT_FIELD_LENGTH


def _parse_sample(
    raw: object,
    fallback_origin: str,
) -> tuple[UsageProvider, CodexRateLimitSample] | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        provider = normalize_usage_provider(raw.get("provider"))
    except ValueError:
        return None
    sampled_at_ms = _strict_int(raw.get("sampled_at_ms"), _MAX_EPOCH_SECONDS * 1_000)
    resets_at = _strict_int(raw.get("resets_at"), _MAX_EPOCH_SECONDS)
    limit_id = raw.get("limit_id")
    plan_type = raw.get("plan_type")
    if (
        sampled_at_ms is None
        or resets_at is None
        or not _bounded_text(limit_id)
        or (plan_type is not None and not _bounded_text(plan_type))
    ):
        return None
    try:
        sample = CodexRateLimitSample(
            sampled_at=datetime_from_epoch_milliseconds(sampled_at_ms),
            used_percent=raw.get("used_percent"),  # type: ignore[arg-type]
            window_minutes=raw.get("window_minutes"),  # type: ignore[arg-type]
            resets_at=datetime_from_epoch_seconds(resets_at),
            plan_type=plan_type,  # type: ignore[arg-type]
            limit_id=limit_id,  # type: ignore[arg-type]
            credits_balance=raw.get("credits_balance"),  # type: ignore[arg-type]
            origin=normalize_origin_label(raw.get("origin")) or fallback_origin,
        )
        day_number(sample.sampled_at)
    except (OverflowError, TypeError, ValueError):
        return None
    return provider, sample


__all__ = [
    "EXPORT_FORMAT",
    "EXPORT_VERSION",
    "MAX_IMPORT_SAMPLES",
    "ParsedSampleDocument",
    "SampleDocumentError",
    "build_export_document",
    "export_filename",
    "local_origin_label",
    "parse_import_document",
]
