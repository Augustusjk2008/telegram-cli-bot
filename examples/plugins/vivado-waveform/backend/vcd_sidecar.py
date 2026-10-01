from __future__ import annotations

import hashlib
import json
import mmap
import os
import tempfile
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vcd_parser import VcdIndex, VcdSeries, VcdSignal, build_vcd_index

SIDECAR_VERSION = 2
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
    cache_hit: bool = False
    build_ms: float = 0.0

    def close(self) -> None:
        for item in self.arrays:
            item.close()
        self.arrays.clear()


def _cache_root() -> Path:
    root = Path(tempfile.gettempdir()) / "telegram-cli-bridge-vcd-index"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _identity_for_path(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    stat = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "sourcePath": str(resolved),
        "mtimeNs": str(stat.st_mtime_ns),
        "fileSize": int(stat.st_size),
        "sha256": digest.hexdigest(),
    }


def _key_for(path: Path, source_identity: dict[str, object] | None = None) -> str:
    identity = dict(source_identity or _identity_for_path(path))
    payload = json.dumps(
        {
            "version": SIDECAR_VERSION,
            "sourcePath": str(identity.get("sourcePath") or path.resolve()),
            "mtimeNs": str(identity.get("mtimeNs") or ""),
            "fileSize": int(identity.get("fileSize") or identity.get("fileSizeBytes") or 0),
            "sha256": str(identity.get("sha256") or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
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
        item: dict[str, Any] = {
            "id_code": signal.id_code,
            "signal_id": signal.signal_id,
            "label": signal.label,
            "scope_parts": list(signal.scope_parts),
            "name": signal.name,
            "width": signal.width,
            "kind": signal.kind,
            "recorded": signal.recorded,
            "change_count": signal.change_count,
            "first_change_time": signal.first_change_time,
            "last_change_time": signal.last_change_time,
            "count": 0,
            "value_table": [],
        }
        series = index.series_by_signal.get(signal.signal_id)
        if series is not None:
            times_file = _signal_filename(signal.signal_id, "times")
            values_file = _signal_filename(signal.signal_id, "values")
            _write_array(sidecar_dir / times_file, series.raw_times, "Q")
            _write_array(sidecar_dir / values_file, series.value_ids, "I")
            item.update(
                {
                    "scale_factor": series.scale_factor,
                    "count": len(series.raw_times),
                    "value_table": list(series.value_table),
                    "times_file": times_file,
                    "values_file": values_file,
                }
            )
        signals.append(item)
    return {
        "version": SIDECAR_VERSION,
        "path": str(index.path),
        "source_identity": dict(index.source_identity),
        "sourcePath": index.source_identity.get("sourcePath"),
        "mtimeNs": index.source_identity.get("mtimeNs"),
        "fileSize": index.source_identity.get("fileSize"),
        "sha256": index.source_identity.get("sha256"),
        "temporaryPath": index.source_identity.get("temporaryPath"),
        "timescale": index.timescale,
        "start_time": index.start_time,
        "end_time": index.end_time,
        "segment_end_time": index.segment_end_time,
        "display": index.display,
        "signals": signals,
        "overview": [dict(item) for item in index.overview],
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


def _write_sidecar(
    path: Path,
    sidecar_dir: Path,
    source_identity: dict[str, object] | None = None,
) -> float:
    started = time.perf_counter()
    tmp_dir = _cache_root() / f"{sidecar_dir.name}.tmp-{os.getpid()}"
    _remove_dir_files(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    index = build_vcd_index(path, source_identity=source_identity)
    metadata = _metadata_from_index(index, tmp_dir)
    (tmp_dir / "index.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    _remove_dir_files(sidecar_dir)
    tmp_dir.rename(sidecar_dir)
    _prune_cache_root()
    return (time.perf_counter() - started) * 1000


def build_or_load_sidecar(
    path: Path,
    *,
    source_identity: dict[str, object] | None = None,
) -> SidecarHandle:
    identity = dict(source_identity or _identity_for_path(path))
    key = _key_for(path, identity)
    sidecar_dir = _cache_root() / key
    metadata_path = sidecar_dir / "index.json"
    cache_hit = metadata_path.exists()
    build_ms = 0.0
    if not metadata_path.exists():
        build_ms = _write_sidecar(path, sidecar_dir, identity)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if int(metadata.get("version") or 0) != SIDECAR_VERSION:
        build_ms = _write_sidecar(path, sidecar_dir, identity)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        cache_hit = False

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
            scope_parts=tuple(str(value) for value in item.get("scope_parts") or []),
            name=str(item.get("name") or ""),
            recorded=bool(item.get("recorded", int(item.get("count", 0) or 0) > 0)),
            change_count=int(item.get("change_count", item.get("count", 0)) or 0),
            first_change_time=item.get("first_change_time"),
            last_change_time=item.get("last_change_time"),
        )
        count = int(item.get("count", 0) or 0)
        signals.append(signal)
        if signal.recorded and count:
            times = MmapArray(sidecar_dir / str(item["times_file"]), 8, count)
            values = MmapArray(sidecar_dir / str(item["values_file"]), 4, count)
            arrays.extend([times, values])
            series_by_signal[signal.signal_id] = VcdSeries(
                signal=signal,
                raw_times=times,
                value_ids=values,
                value_table=tuple(str(value) for value in list(item["value_table"])),
                scale_factor=float(item["scale_factor"]),
            )

    loaded_identity = dict(metadata.get("source_identity") or identity)
    if identity.get("temporaryPath"):
        loaded_identity["temporaryPath"] = identity["temporaryPath"]
    return SidecarHandle(
        index=VcdIndex(
            path=Path(str(metadata.get("path") or path)).resolve(),
            timescale=str(metadata["timescale"]),
            start_time=metadata["start_time"],
            end_time=metadata["end_time"],
            segment_end_time=metadata.get("segment_end_time", metadata["end_time"]),
            display=dict(metadata["display"]),
            signals=tuple(signals),
            series_by_signal=series_by_signal,
            overview=tuple(dict(item) for item in list(metadata.get("overview") or [])),
            source_identity=loaded_identity,
            index_cache_hit=cache_hit,
            index_build_ms=build_ms,
        ),
        arrays=arrays,
        cache_hit=cache_hit,
        build_ms=build_ms,
    )
