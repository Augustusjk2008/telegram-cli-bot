from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from vcd_parser import VcdIndex
from vcd_sidecar import SidecarHandle, build_or_load_sidecar

MAX_INDEXES = 2


@dataclass(frozen=True)
class WaveformSession:
    session_id: str
    index_key: tuple[str, str, int, str]
    temporary_path: Path | None = None


@dataclass
class _IndexEntry:
    handle: SidecarHandle
    ref_count: int = 0


class WaveformSessionStore:
    def __init__(self) -> None:
        self._counter = 0
        self._indexes: OrderedDict[tuple[str, str, int, str], _IndexEntry] = OrderedDict()
        self._sessions: dict[str, WaveformSession] = {}
        self._window_cache: OrderedDict[tuple[object, ...], dict[str, object]] = OrderedDict()

    @staticmethod
    def _index_key(source: Any) -> tuple[str, str, int, str]:
        if isinstance(source, Path):
            resolved = source.resolve()
            stat = resolved.stat()
            return (str(resolved), str(stat.st_mtime_ns), stat.st_size, "")
        identity = dict(source)
        return (
            str(identity.get("sourcePath") or identity.get("path") or ""),
            str(identity.get("mtimeNs") or ""),
            int(identity.get("fileSize") or identity.get("fileSizeBytes") or 0),
            str(identity.get("sha256") or ""),
        )

    def open(
        self,
        path: Path,
        *,
        source_identity: dict[str, object] | None = None,
        temporary_path: Path | None = None,
    ) -> tuple[str, VcdIndex]:
        identity = source_identity or {}
        key = self._index_key(identity if identity else path)
        entry = self._indexes.get(key)
        if entry is None:
            entry = _IndexEntry(handle=build_or_load_sidecar(path, source_identity=identity or None))
            self._indexes[key] = entry
        elif not entry.handle.index.index_cache_hit:
            entry.handle.index = replace(entry.handle.index, index_cache_hit=True, index_build_ms=0.0)
        self._indexes.move_to_end(key)
        entry.ref_count += 1
        self._counter += 1
        session_id = f"wave-session-{self._counter}"
        self._sessions[session_id] = WaveformSession(
            session_id=session_id,
            index_key=key,
            temporary_path=temporary_path,
        )
        self._evict_idle_indexes()
        return session_id, entry.handle.index

    def get_index(self, session_id: str) -> VcdIndex:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("waveform session expired")
        entry = self._indexes.get(session.index_key)
        if entry is None:
            raise ValueError("waveform session expired")
        self._indexes.move_to_end(session.index_key)
        return entry.handle.index

    def dispose(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        self._cleanup_temporary_path(session.temporary_path)
        for cache_key in list(self._window_cache.keys()):
            if cache_key and cache_key[0] == session_id:
                self._window_cache.pop(cache_key, None)
        entry = self._indexes.get(session.index_key)
        if entry is not None:
            entry.ref_count = max(0, entry.ref_count - 1)
        self._evict_idle_indexes(force=True)
        return True

    @staticmethod
    def _cleanup_temporary_path(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
            parent = path.parent
            if parent.name.startswith("vivado-waveform-"):
                parent.rmdir()
        except OSError:
            pass

    def close_all(self) -> None:
        for session_id in list(self._sessions):
            self.dispose(session_id)
        for entry in self._indexes.values():
            entry.handle.close()
        self._indexes.clear()
        self._window_cache.clear()

    def get_window_cache(self, key: tuple[object, ...]) -> dict[str, object] | None:
        cached = self._window_cache.get(key)
        if cached is None:
            return None
        self._window_cache.move_to_end(key)
        return cached

    def remember_window_cache(self, key: tuple[object, ...], payload: dict[str, object]) -> None:
        self._window_cache[key] = payload
        self._window_cache.move_to_end(key)
        while len(self._window_cache) > 32:
            self._window_cache.popitem(last=False)

    def _evict_idle_indexes(self, *, force: bool = False) -> None:
        for key in list(self._indexes.keys()):
            if len(self._indexes) <= MAX_INDEXES and not force:
                break
            entry = self._indexes[key]
            if entry.ref_count > 0:
                continue
            self._indexes.pop(key)
            entry.handle.close()
