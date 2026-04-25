from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from vcd_parser import VcdIndex
from vcd_sidecar import SidecarHandle, build_or_load_sidecar

MAX_INDEXES = 2


@dataclass(frozen=True)
class WaveformSession:
    session_id: str
    index_key: tuple[str, int, int]


@dataclass
class _IndexEntry:
    handle: SidecarHandle
    ref_count: int = 0


class WaveformSessionStore:
    def __init__(self) -> None:
        self._counter = 0
        self._indexes: OrderedDict[tuple[str, int, int], _IndexEntry] = OrderedDict()
        self._sessions: dict[str, WaveformSession] = {}
        self._window_cache: OrderedDict[tuple[object, ...], dict[str, object]] = OrderedDict()

    @staticmethod
    def _index_key(path: Path) -> tuple[str, int, int]:
        resolved = path.resolve()
        stat = resolved.stat()
        return (str(resolved), stat.st_mtime_ns, stat.st_size)

    def open(self, path: Path) -> tuple[str, VcdIndex]:
        key = self._index_key(path)
        entry = self._indexes.get(key)
        if entry is None:
            entry = _IndexEntry(handle=build_or_load_sidecar(path))
            self._indexes[key] = entry
        self._indexes.move_to_end(key)
        entry.ref_count += 1
        self._counter += 1
        session_id = f"wave-session-{self._counter}"
        self._sessions[session_id] = WaveformSession(session_id=session_id, index_key=key)
        self._evict_idle_indexes()
        return session_id, entry.handle.index

    def get_index(self, session_id: str) -> VcdIndex:
        session = self._sessions[session_id]
        entry = self._indexes[session.index_key]
        self._indexes.move_to_end(session.index_key)
        return entry.handle.index

    def dispose(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        for cache_key in list(self._window_cache.keys()):
            if cache_key and cache_key[0] == session_id:
                self._window_cache.pop(cache_key, None)
        entry = self._indexes.get(session.index_key)
        if entry is not None:
            entry.ref_count = max(0, entry.ref_count - 1)
        self._evict_idle_indexes(force=True)
        return True

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
