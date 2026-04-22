from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VcdSignal:
    id_code: str
    label: str
    width: int


def parse_vcd(path: Path) -> dict[str, object]:
    scope: list[str] = []
    timescale = "1ns"
    signals: dict[str, VcdSignal] = {}
    changes: dict[str, list[tuple[int, str]]] = {}
    current_time = 0

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("$timescale"):
            timescale = line.replace("$timescale", "").replace("$end", "").strip() or "1ns"
            continue
        if line.startswith("$scope"):
            parts = line.split()
            if len(parts) >= 3:
                scope.append(parts[2])
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
            id_code = parts[3]
            name = parts[4]
            label = ".".join([*scope, name]) if scope else name
            signals[id_code] = VcdSignal(id_code=id_code, label=label, width=width)
            changes.setdefault(id_code, [])
            continue
        if line.startswith("#"):
            current_time = int(line[1:] or 0)
            continue
        if line.startswith("b"):
            value, id_code = line[1:].split(" ", 1)
            changes.setdefault(id_code, []).append((current_time, value))
            continue
        if line[0] in {"0", "1", "x", "z"}:
            changes.setdefault(line[1:], []).append((current_time, line[0]))

    end_time = max((items[-1][0] for items in changes.values() if items), default=0)
    tracks = []
    for id_code, signal in signals.items():
        signal_changes = changes.get(id_code, [])
        if not signal_changes:
            continue
        segments = []
        for index, (start, value) in enumerate(signal_changes):
            next_time = signal_changes[index + 1][0] if index + 1 < len(signal_changes) else end_time
            end = max(start, next_time)
            segments.append({"start": start, "end": end, "value": value})
        tracks.append(
            {
                "signalId": signal.id_code,
                "label": signal.label,
                "width": signal.width,
                "segments": segments,
            }
        )
    return {
        "timescale": timescale,
        "startTime": 0,
        "endTime": end_time,
        "display": {
            "defaultZoom": 1,
            "zoomLevels": [0.5, 0.75, 1, 1.5, 2, 3, 4],
            "showTimeAxis": True,
            "busStyle": "cross",
            "labelWidth": 220,
            "minWaveWidth": 840,
            "pixelsPerTime": 18,
            "axisHeight": 42,
            "trackHeight": 64,
        },
        "tracks": tracks,
    }
