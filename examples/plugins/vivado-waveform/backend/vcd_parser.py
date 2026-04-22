from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class VcdSignal:
    id_code: str
    label: str
    width: int


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


def _scale_time(raw_time: int, factor: float) -> int | float:
    scaled = raw_time * factor
    rounded = round(scaled)
    if abs(scaled - rounded) < 1e-12:
        return int(rounded)
    return round(scaled, TIME_DECIMALS)


def _is_visible_scope(scope: list[tuple[str, str]]) -> bool:
    return not any(kind in EXCLUDED_SCOPE_KINDS for kind, _ in scope)


def _append_change(
    changes: dict[str, list[tuple[int, str]]],
    id_code: str,
    current_time: int,
    value: str,
) -> None:
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


def parse_vcd(path: Path) -> dict[str, object]:
    scope: list[tuple[str, str]] = []
    source_timescale_amount = 1.0
    source_timescale_unit = "ns"
    pending_timescale: list[str] | None = None
    signals: dict[str, VcdSignal] = {}
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
                signals[id_code] = VcdSignal(id_code=id_code, label=label, width=width)
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
                if id_code in signals:
                    _append_change(changes, id_code, current_time, value.lower())
                continue
            if line[0] in {"0", "1", "x", "X", "z", "Z"}:
                id_code = line[1:].strip()
                if id_code in signals:
                    _append_change(changes, id_code, current_time, line[0].lower())

    end_time_raw = max((items[-1][0] for items in changes.values() if items), default=0)
    duration_seconds = end_time_raw * source_timescale_amount * UNIT_SECONDS[source_timescale_unit]
    display_unit = _choose_display_unit(duration_seconds, source_timescale_unit)
    scale_factor = source_timescale_amount * UNIT_SECONDS[source_timescale_unit] / UNIT_SECONDS[display_unit]
    end_time = _scale_time(end_time_raw, scale_factor)

    tracks = []
    min_scalar_interval: int | float | None = None

    for id_code, signal in signals.items():
        raw_signal_changes = changes.get(id_code, [])
        if not raw_signal_changes:
            continue

        segments = []
        scaled_changes = [_scale_time(raw_time, scale_factor) for raw_time, _ in raw_signal_changes]
        values = [value for _, value in raw_signal_changes]

        for index, start in enumerate(scaled_changes):
            next_time = scaled_changes[index + 1] if index + 1 < len(scaled_changes) else end_time
            end = max(start, next_time)
            segments.append({"start": start, "end": end, "value": values[index]})

            interval = float(end) - float(start)
            if signal.width == 1 and interval > 0:
                if min_scalar_interval is None or interval < float(min_scalar_interval):
                    min_scalar_interval = interval

        tracks.append(
            {
                "signalId": signal.id_code,
                "label": signal.label,
                "width": signal.width,
                "segments": segments,
            }
        )

    return {
        "timescale": f"1{display_unit}",
        "startTime": 0,
        "endTime": end_time,
        "display": _display_options(end_time, min_scalar_interval),
        "tracks": tracks,
    }
