from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vcd_parser import VcdIndex, build_vcd_index


@dataclass(frozen=True)
class WaveformSession:
    session_id: str
    index_key: tuple[str, int, int]


class WaveformSessionStore:
    def __init__(self) -> None:
        self._counter = 0
        self._indexes: dict[tuple[str, int, int], VcdIndex] = {}
        self._sessions: dict[str, WaveformSession] = {}

    @staticmethod
    def _index_key(path: Path) -> tuple[str, int, int]:
        resolved = path.resolve()
        stat = resolved.stat()
        return (str(resolved), stat.st_mtime_ns, stat.st_size)

    def open(self, path: Path) -> tuple[str, VcdIndex]:
        key = self._index_key(path)
        index = self._indexes.get(key)
        if index is None:
            index = build_vcd_index(path)
            self._indexes = {
                current_key: current_index
                for current_key, current_index in self._indexes.items()
                if current_key[0] != key[0]
            }
            self._indexes[key] = index
        self._counter += 1
        session_id = f"wave-session-{self._counter}"
        self._sessions[session_id] = WaveformSession(session_id=session_id, index_key=key)
        return session_id, index

    def get_index(self, session_id: str) -> VcdIndex:
        session = self._sessions[session_id]
        return self._indexes[session.index_key]

    def dispose(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None
