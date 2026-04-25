from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from session_store import WaveformSessionStore
from vcd_parser import build_waveform_summary, parse_vcd, query_waveform_window

INITIAL_PIXEL_WIDTH = 1200
INITIAL_WINDOW_SPAN = 120
SESSION_STORE = WaveformSessionStore()
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _coerce_time(value: object) -> int | float:
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").strip()
    if not text:
        return 0
    if "." in text:
        return float(text)
    return int(text)


def _plugin_config() -> dict[str, object]:
    try:
        payload = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    config = payload.get("config")
    return dict(config) if isinstance(config, dict) else {}


def _lod_enabled() -> bool:
    return bool(_plugin_config().get("lodEnabled", True))


def render_view(input_payload: dict[str, object]) -> dict[str, object]:
    path = Path(str(input_payload["path"])).resolve()
    parsed = parse_vcd(path, lod_enabled=_lod_enabled())
    return {
        "renderer": "waveform",
        "title": path.name,
        "payload": {
            "path": str(path),
            **parsed,
        },
    }


def open_view(input_payload: dict[str, object]) -> dict[str, object]:
    path = Path(str(input_payload["path"])).resolve()
    session_id, index = SESSION_STORE.open(path)
    summary = build_waveform_summary(index, path=path)
    initial_end = min(float(summary["endTime"]), float(summary["startTime"]) + INITIAL_WINDOW_SPAN)
    initial_window = query_waveform_window(
        index,
        start_time=summary["startTime"],
        end_time=_coerce_time(initial_end),
        signal_ids=list(summary["defaultSignalIds"]),
        pixel_width=INITIAL_PIXEL_WIDTH,
        lod_enabled=_lod_enabled(),
    )
    return {
        "renderer": "waveform",
        "title": path.name,
        "mode": "session",
        "sessionId": session_id,
        "summary": summary,
        "initialWindow": initial_window,
    }


def get_view_window(params: dict[str, object]) -> dict[str, object]:
    session_id = str(params.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId 不能为空")
    signal_ids = [str(item) for item in list(params.get("signalIds") or [])]
    start_time = _coerce_time(params.get("startTime"))
    end_time = _coerce_time(params.get("endTime"))
    pixel_width = int(params.get("pixelWidth") or INITIAL_PIXEL_WIDTH)
    lod_enabled = _lod_enabled()
    cache_key = (
        session_id,
        start_time,
        end_time,
        tuple(signal_ids),
        pixel_width,
        lod_enabled,
    )
    cached = SESSION_STORE.get_window_cache(cache_key)
    if cached is not None:
        return cached
    index = SESSION_STORE.get_index(session_id)
    payload = query_waveform_window(
        index,
        start_time=start_time,
        end_time=end_time,
        signal_ids=signal_ids,
        pixel_width=pixel_width,
        lod_enabled=lod_enabled,
    )
    SESSION_STORE.remember_window_cache(cache_key, payload)
    return payload


def dispose_view(params: dict[str, object]) -> dict[str, object]:
    session_id = str(params.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId 不能为空")
    return {"disposed": SESSION_STORE.dispose(session_id)}


def write_response(request_id: object, *, result: dict[str, object] | None = None, error: str | None = None) -> None:
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    try:
        if method == "plugin.initialize":
            write_response(request_id, result={"ok": True, "name": "vivado-waveform"})
        elif method == "plugin.render_view":
            view_input = dict(params.get("input") or {})
            write_response(request_id, result=render_view(view_input))
        elif method == "plugin.open_view":
            view_input = dict(params.get("input") or {})
            write_response(request_id, result=open_view(view_input))
        elif method == "plugin.get_view_window":
            write_response(request_id, result=get_view_window(dict(params)))
        elif method == "plugin.dispose_view":
            write_response(request_id, result=dispose_view(dict(params)))
        elif method == "plugin.shutdown":
            write_response(request_id, result={"ok": True})
        else:
            write_response(request_id, error=f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover - plugin runtime catches via stdio
        write_response(request_id, error=str(exc))
