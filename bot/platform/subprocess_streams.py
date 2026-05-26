"""Subprocess stream cleanup helpers."""

from __future__ import annotations

from typing import Any


def close_process_streams(process: Any) -> None:
    if process is None or getattr(process, "_tcb_streams_closed", False) is True:
        return
    try:
        setattr(process, "_tcb_streams_closed", True)
    except Exception:
        pass

    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, name, None)
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
