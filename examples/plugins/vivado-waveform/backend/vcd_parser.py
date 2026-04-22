from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any


UNIT_SECONDS = {
    "fs": 1e-15,
    "ps": 1e-12,
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
}
UNIT_ORDER = ("fs", "ps", "ns", "us", "ms", "s")
MAX_DISPLAY_TIME = 10_000
MAX_CONTENT_WIDTH = 24_000
DEFAULT_PIXELS_PER_TIME = 18
DEFAULT_ZOOM_LEVELS = [1, 2, 4, 8, 16, 32, 64]
TIME_DECIMALS = 12
EXCLUDED_SCOPE_KINDS = {"task", "function"}
TARGET_MIN_PULSE_PIXELS = 1.0
MAX_DEFAULT_SIGNAL_COUNT = 12
MAX_WINDOW_SEGMENTS_PER_TRACK = 320
MAX_PARSE_SEGMENTS_PER_TRACK = 4000


@dataclass(frozen=True)
class VcdSignal:
    id_code: str
    signal_id: str
    label: str
    width: int
    kind: str


@dataclass(frozen=True)
class VcdSeries:
    signal: VcdSignal
    times: tuple[int | float, ...]
    values: tuple[str, ...]


@dataclass(frozen=True)
class VcdIndex:
    path: Path
    timescale: str
    start_time: int | float
    end_time: int | float
    display: dict[str, object]
    signals: tuple[VcdSignal, ...]
    series_by_signal: dict[str, VcdSeries]


def _parse_timescale(value: str) -> tuple[float, str]:
    normalized = " ".join(value.replace("$timescale", "").replace("$end", "").split())
    match = re.match(r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>fs|ps|ns|us|ms|s)\b", normalized)
    if not match:
        return 1.0, "ns"
    return float(match.group("amount")), match.group("unit")


def _choose_display_unit(duration_seconds: float, fallback_unit: str) -> str:
    if duration_seconds <= 0:
        return fallback_unit if fallback_unit in UNIT_SECONDS else "ns"
    for unit in UNIT_ORDER:
        if duration_seconds / UNIT_SECONDS[unit] <= MAX_DISPLAY_TIME:
            return unit
    return "s"


def _round_time(value: float) -> int | float:
    rounded = round(value)
    if abs(value - rounded) < 1e-12:
        return int(rounded)
    return round(value, TIME_DECIMALS)


def _scale_time(raw_time: int, factor: float) -> int | float:
    return _round_time(raw_time * factor)


def _is_visible_scope(scope: list[tuple[str, str]]) -> bool:
    return not any(kind in EXCLUDED_SCOPE_KINDS for kind, _ in scope)


def _append_change(changes: dict[str, list[tuple[int, str]]], id_code: str, current_time: int, value: str) -> None:
    bucket = changes.setdefault(id_code, [])
    if bucket and bucket[-1][0] == current_time:
        bucket[-1] = (current_time, value)
        return
    if bucket and bucket[-1][1] == value:
        return
    bucket.append((current_time, value))


def _build_zoom_levels(default_zoom: int) -> list[int]:
    zoom_levels = sorted(set([*DEFAULT_ZOOM_LEVELS, default_zoom]))
    return [level for level in zoom_levels if level >= 1]


def _choose_default_zoom(pixels_per_time: float, min_interval: int | float | None) -> int:
    if min_interval is None or min_interval <= 0:
        return 1
    required_zoom = TARGET_MIN_PULSE_PIXELS / max(pixels_per_time * float(min_interval), 1e-12)
    zoom = 1
    for level in DEFAULT_ZOOM_LEVELS:
        zoom = level
        if level >= required_zoom:
            return level
    return zoom


def _display_options(end_time: int | float, min_scalar_interval: int | float | None) -> dict[str, object]:
    time_range = max(1.0, float(end_time))
    pixels_per_time = min(DEFAULT_PIXELS_PER_TIME, MAX_CONTENT_WIDTH / time_range)
    pixels_per_time = max(0.001, pixels_per_time)
    default_zoom = _choose_default_zoom(pixels_per_time, min_scalar_interval)
    return {
        "defaultZoom": default_zoom,
        "zoomLevels": _build_zoom_levels(default_zoom),
        "showTimeAxis": True,
        "busStyle": "cross",
        "labelWidth": 220,
        "minWaveWidth": 840,
        "pixelsPerTime": pixels_per_time,
        "axisHeight": 42,
        "trackHeight": 64,
    }


def _window_segments(
    series: VcdSeries,
    window_start: int | float,
    window_end: int | float,
    overall_end: int | float,
) -> list[dict[str, int | float | str]]:
    if not series.times:
        return []
    times = series.times
    values = series.values
    start = float(window_start)
    end = float(window_end)
    if end < start:
        start, end = end, start
    index = max(0, bisect_right(times, start) - 1)
    segments: list[dict[str, int | float | str]] = []
    while index < len(times):
        segment_start = max(start, float(times[index]))
        next_time = float(times[index + 1]) if index + 1 < len(times) else float(overall_end)
        segment_end = min(end, next_time)
        if segment_end > segment_start:
            segments.append(
                {
                    "start": _round_time(segment_start),
                    "end": _round_time(segment_end),
                    "value": values[index],
                }
            )
        if next_time >= end:
            break
        index += 1
    return segments


def _compress_segments(
    segments: list[dict[str, int | float | str]],
    *,
    start_time: int | float,
    end_time: int | float,
    max_segments: int,
    signal_kind: str,
) -> list[dict[str, int | float | str]]:
    if len(segments) <= max_segments:
        return segments
    start = float(start_time)
    end = float(end_time)
    if end <= start:
        return segments[:1]
    bucket_width = (end - start) / max(max_segments, 1)
    if bucket_width <= 0:
        return segments[:max_segments]

    compressed: list[dict[str, int | float | str]] = []
    segment_index = 0
    for bucket in range(max_segments):
        bucket_start = start + bucket * bucket_width
        bucket_end = end if bucket == max_segments - 1 else min(end, bucket_start + bucket_width)
        values: list[str] = []
        while segment_index < len(segments) and float(segments[segment_index]["end"]) <= bucket_start:
            segment_index += 1
        probe = segment_index
        while probe < len(segments) and float(segments[probe]["start"]) < bucket_end:
            values.append(str(segments[probe]["value"]))
            probe += 1
        if not values:
            continue
        unique_values = set(values)
        if len(unique_values) == 1:
            value = values[0]
        elif signal_kind == "scalar":
            value = "x"
        else:
            value = values[-1]
        if compressed and compressed[-1]["value"] == value:
            compressed[-1]["end"] = _round_time(bucket_end)
        else:
            compressed.append(
                {
                    "start": _round_time(bucket_start),
                    "end": _round_time(bucket_end),
                    "value": value,
                }
            )
    return [segment for segment in compressed if float(segment["end"]) > float(segment["start"])]


def build_vcd_index(path: Path) -> VcdIndex:
    scope: list[tuple[str, str]] = []
    source_timescale_amount = 1.0
    source_timescale_unit = "ns"
    pending_timescale: list[str] | None = None
    signals_by_code: dict[str, VcdSignal] = {}
    changes: dict[str, list[tuple[int, str]]] = {}
    current_time = 0

    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if pending_timescale is not None:
                if "$end" in line:
                    pending_timescale.append(line.replace("$end", "").strip())
                    source_timescale_amount, source_timescale_unit = _parse_timescale(" ".join(pending_timescale))
                    pending_timescale = None
                else:
                    pending_timescale.append(line)
                continue
            if line.startswith("$timescale"):
                value = line.replace("$timescale", "").strip()
                if "$end" in value:
                    source_timescale_amount, source_timescale_unit = _parse_timescale(value)
                else:
                    pending_timescale = [value] if value else []
                continue
            if line.startswith("$scope"):
                parts = line.split()
                if len(parts) >= 3:
                    scope.append((parts[1], parts[2]))
                continue
            if line.startswith("$upscope"):
                if scope:
                    scope.pop()
                continue
            if line.startswith("$var"):
                parts = line.split()
                if len(parts) < 5:
                    continue
                width = int(parts[2])
                if width <= 0 or not _is_visible_scope(scope):
                    continue
                id_code = parts[3]
                name = parts[4]
                label = ".".join([name_part for _, name_part in scope] + [name]) if scope else name
                signals_by_code[id_code] = VcdSignal(
                    id_code=id_code,
                    signal_id=label,
                    label=label,
                    width=width,
                    kind="bus" if width > 1 else "scalar",
                )
                changes.setdefault(id_code, [])
                continue
            if line.startswith("#"):
                current_time = int(line[1:] or 0)
                continue
            if line[0] in {"b", "B"}:
                parts = line[1:].split(maxsplit=1)
                if len(parts) != 2:
                    continue
                value, id_code = parts
                if id_code in signals_by_code:
                    _append_change(changes, id_code, current_time, value.lower())
                continue
            if line[0] in {"0", "1", "x", "X", "z", "Z"}:
                id_code = line[1:].strip()
                if id_code in signals_by_code:
                    _append_change(changes, id_code, current_time, line[0].lower())

    end_time_raw = max((items[-1][0] for items in changes.values() if items), default=0)
    duration_seconds = end_time_raw * source_timescale_amount * UNIT_SECONDS[source_timescale_unit]
    display_unit = _choose_display_unit(duration_seconds, source_timescale_unit)
    scale_factor = source_timescale_amount * UNIT_SECONDS[source_timescale_unit] / UNIT_SECONDS[display_unit]
    end_time = _scale_time(end_time_raw, scale_factor)

    signals: list[VcdSignal] = []
    series_by_signal: dict[str, VcdSeries] = {}
    min_scalar_interval: int | float | None = None

    for id_code, signal in signals_by_code.items():
        raw_signal_changes = changes.get(id_code, [])
        if not raw_signal_changes:
            continue
        scaled_times = tuple(_scale_time(raw_time, scale_factor) for raw_time, _ in raw_signal_changes)
        values = tuple(value for _, value in raw_signal_changes)
        for index, start in enumerate(scaled_times[:-1]):
            interval = float(scaled_times[index + 1]) - float(start)
            if signal.width == 1 and interval > 0:
                if min_scalar_interval is None or interval < float(min_scalar_interval):
                    min_scalar_interval = interval
        signals.append(signal)
        series_by_signal[signal.signal_id] = VcdSeries(signal=signal, times=scaled_times, values=values)

    return VcdIndex(
        path=path.resolve(),
        timescale=f"1{display_unit}",
        start_time=0,
        end_time=end_time,
        display=_display_options(end_time, min_scalar_interval),
        signals=tuple(signals),
        series_by_signal=series_by_signal,
    )


def build_waveform_summary(index: VcdIndex, *, path: Path | None = None) -> dict[str, Any]:
    default_signal_ids = [signal.signal_id for signal in index.signals[:MAX_DEFAULT_SIGNAL_COUNT]]
    return {
        "path": str((path or index.path).resolve()),
        "timescale": index.timescale,
        "startTime": index.start_time,
        "endTime": index.end_time,
        "display": dict(index.display),
        "signals": [
            {
                "signalId": signal.signal_id,
                "label": signal.label,
                "width": signal.width,
                "kind": signal.kind,
            }
            for signal in index.signals
        ],
        "defaultSignalIds": default_signal_ids,
    }


def query_waveform_window(
    index: VcdIndex,
    *,
    start_time: int | float,
    end_time: int | float,
    signal_ids: list[str],
    pixel_width: int,
    max_segments_per_track: int = MAX_WINDOW_SEGMENTS_PER_TRACK,
) -> dict[str, Any]:
    start = start_time
    end = end_time if float(end_time) >= float(start_time) else start_time
    requested_signal_ids = signal_ids or [signal.signal_id for signal in index.signals[:MAX_DEFAULT_SIGNAL_COUNT]]
    max_segments = max(64, min(max_segments_per_track, max(64, int(pixel_width) if pixel_width else max_segments_per_track)))
    tracks: list[dict[str, Any]] = []
    for signal_id in requested_signal_ids:
        series = index.series_by_signal.get(signal_id)
        if series is None:
            continue
        segments = _window_segments(series, start, end, index.end_time)
        segments = _compress_segments(
            segments,
            start_time=start,
            end_time=end,
            max_segments=max_segments,
            signal_kind=series.signal.kind,
        )
        tracks.append(
            {
                "signalId": series.signal.signal_id,
                "label": series.signal.label,
                "width": series.signal.width,
                "segments": segments,
            }
        )
    return {
        "startTime": start,
        "endTime": end,
        "tracks": tracks,
    }


def parse_vcd(path: Path) -> dict[str, Any]:
    index = build_vcd_index(path)
    summary = build_waveform_summary(index, path=path)
    full_window = query_waveform_window(
        index,
        start_time=summary["startTime"],
        end_time=summary["endTime"],
        signal_ids=[signal["signalId"] for signal in summary["signals"]],
        pixel_width=MAX_PARSE_SEGMENTS_PER_TRACK,
        max_segments_per_track=MAX_PARSE_SEGMENTS_PER_TRACK,
    )
    return {
        "timescale": summary["timescale"],
        "startTime": summary["startTime"],
        "endTime": summary["endTime"],
        "display": summary["display"],
        "tracks": full_window["tracks"],
    }
