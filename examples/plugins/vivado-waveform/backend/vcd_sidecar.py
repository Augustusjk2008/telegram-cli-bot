from __future__ import annotations

import hashlib
import json
import mmap
import os
import tempfile
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vcd_parser import VcdIndex, VcdSeries, VcdSignal, build_vcd_index

SIDECAR_VERSION = 1
MAX_SIDECAR_DIRS = 24


class MmapArray:
    def __init__(self, path: Path, item_size: int, count: int) -> None:
        self.path = path
        self.item_size = item_size
        self.count = count
        self._handle = path.open("rb")
        self._mmap = mmap.mmap(self._handle.fileno(), 0, access=mmap.ACCESS_READ)

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self.count)
            return [self[item] for item in range(start, stop, step)]
        if index < 0:
            index += self.count
        if index < 0 or index >= self.count:
            raise IndexError(index)
        offset = index * self.item_size
        return int.from_bytes(self._mmap[offset : offset + self.item_size], "little", signed=False)

    def close(self) -> None:
        self._mmap.close()
        self._handle.close()


@dataclass
class SidecarHandle:
    index: VcdIndex
    arrays: list[MmapArray]

    def close(self) -> None:
        for item in self.arrays:
            item.close()
        self.arrays.clear()


def _cache_root() -> Path:
    root = Path(tempfile.gettempdir()) / "telegram-cli-bridge-vcd-index"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key_for(path: Path) -> str:
    resolved = path.resolve()
    stat = resolved.stat()
    payload = f"{SIDECAR_VERSION}|{resolved}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _signal_filename(signal_id: str, suffix: str) -> str:
    digest = hashlib.sha1(signal_id.encode("utf-8")).hexdigest()
    return f"{digest}.{suffix}.bin"


def _write_array(path: Path, values: Any, typecode: str) -> None:
    data = array(typecode, values)
    with path.open("wb") as handle:
        data.tofile(handle)


def _metadata_from_index(index: VcdIndex, sidecar_dir: Path) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    for signal in index.signals:
        series = index.series_by_signal[signal.signal_id]
        times_file = _signal_filename(signal.signal_id, "times")
        values_file = _signal_filename(signal.signal_id, "values")
        _write_array(sidecar_dir / times_file, series.raw_times, "Q")
        _write_array(sidecar_dir / values_file, series.value_ids, "I")
        signals.append(
            {
                "id_code": signal.id_code,
                "signal_id": signal.signal_id,
                "label": signal.label,
                "width": signal.width,
                "kind": signal.kind,
                "scale_factor": series.scale_factor,
                "count": len(series.raw_times),
                "value_table": list(series.value_table),
                "times_file": times_file,
                "values_file": values_file,
            }
        )
    return {
        "version": SIDECAR_VERSION,
        "path": str(index.path),
        "timescale": index.timescale,
        "start_time": index.start_time,
        "end_time": index.end_time,
        "display": index.display,
        "signals": signals,
    }


def _remove_dir_files(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink()
    path.rmdir()


def _prune_cache_root() -> None:
    root = _cache_root()
    dirs = [item for item in root.iterdir() if item.is_dir() and not item.name.endswith(".tmp")]
    stale_dirs = sorted(dirs, key=lambda item: item.stat().st_mtime_ns)[:-MAX_SIDECAR_DIRS]
    for stale in stale_dirs:
        try:
            _remove_dir_files(stale)
        except OSError:
            continue


def _write_sidecar(path: Path, sidecar_dir: Path) -> None:
    tmp_dir = _cache_root() / f"{sidecar_dir.name}.tmp-{os.getpid()}"
    _remove_dir_files(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    index = build_vcd_index(path)
    metadata = _metadata_from_index(index, tmp_dir)
    (tmp_dir / "index.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    _remove_dir_files(sidecar_dir)
    tmp_dir.rename(sidecar_dir)
    _prune_cache_root()


def build_or_load_sidecar(path: Path) -> SidecarHandle:
    key = _key_for(path)
    sidecar_dir = _cache_root() / key
    metadata_path = sidecar_dir / "index.json"
    if not metadata_path.exists():
        _write_sidecar(path, sidecar_dir)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if int(metadata.get("version") or 0) != SIDECAR_VERSION:
        _write_sidecar(path, sidecar_dir)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    arrays: list[MmapArray] = []
    signals: list[VcdSignal] = []
    series_by_signal: dict[str, VcdSeries] = {}
    for item in list(metadata["signals"]):
        signal = VcdSignal(
            id_code=str(item["id_code"]),
            signal_id=str(item["signal_id"]),
            label=str(item["label"]),
            width=int(item["width"]),
            kind=str(item["kind"]),
        )
        count = int(item["count"])
        times = MmapArray(sidecar_dir / str(item["times_file"]), 8, count)
        values = MmapArray(sidecar_dir / str(item["values_file"]), 4, count)
        arrays.extend([times, values])
        signals.append(signal)
        series_by_signal[signal.signal_id] = VcdSeries(
            signal=signal,
            raw_times=times,
            value_ids=values,
            value_table=tuple(str(value) for value in list(item["value_table"])),
            scale_factor=float(item["scale_factor"]),
        )

    return SidecarHandle(
        index=VcdIndex(
            path=Path(str(metadata["path"])).resolve(),
            timescale=str(metadata["timescale"]),
            start_time=metadata["start_time"],
            end_time=metadata["end_time"],
            display=dict(metadata["display"]),
            signals=tuple(signals),
            series_by_signal=series_by_signal,
        ),
        arrays=arrays,
    )
