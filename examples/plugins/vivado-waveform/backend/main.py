from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from log_parser import parse_vivado_log
from session_store import WaveformSessionStore
from vcd_parser import build_waveform_summary, inspect_waveform, parse_vcd, query_waveform_window

INITIAL_PIXEL_WIDTH = 1200
INITIAL_WINDOW_SPAN = 120
READ_CHUNK_BYTES = 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
SESSION_STORE = WaveformSessionStore()
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
NEXT_HOST_REQUEST_ID = 9000


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def write_response(request_id: object, *, result: dict[str, object] | None = None, error: str | None = None) -> None:
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    emit(payload)


def call_host(method: str, params: dict[str, Any]) -> dict[str, Any]:
    global NEXT_HOST_REQUEST_ID
    request_id = NEXT_HOST_REQUEST_ID
    NEXT_HOST_REQUEST_ID += 1
    emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    while True:
        raw_line = sys.stdin.readline()
        if not raw_line:
            raise RuntimeError("Host API 连接已关闭")
        message = json.loads(raw_line)
        if message.get("method"):
            continue
        if int(message.get("id") or 0) == request_id:
            if message.get("error"):
                detail = message["error"]
                raise RuntimeError(str(detail.get("message") or "Host API 请求失败"))
            return dict(message.get("result") or {})


def _coerce_time(value: object) -> int | float:
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").strip()
    if not text:
        return 0
    return float(text) if "." in text else int(text)


def _plugin_config() -> dict[str, object]:
    try:
        payload = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    config = payload.get("config")
    return dict(config) if isinstance(config, dict) else {}


def _lod_enabled() -> bool:
    return bool(_plugin_config().get("lodEnabled", True))


def _cleanup_temp_path(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
        if path.parent.name.startswith("vivado-waveform-"):
            path.parent.rmdir()
    except OSError:
        pass


def _materialize_host_file(source_path: str, *, max_bytes: int | None = None) -> tuple[Path, dict[str, object], bool]:
    stat = call_host("host.workspace.stat", {"path": source_path})
    if not bool(stat.get("exists")):
        raise FileNotFoundError(source_path)
    if bool(stat.get("isDir")):
        raise ValueError(f"路径不是普通文件: {source_path}")
    file_size = int(stat.get("size") or 0)
    mtime_ns = str(stat.get("mtimeNs") or "0")
    read_size = file_size if max_bytes is None else min(file_size, max_bytes)
    temp_dir = Path(tempfile.mkdtemp(prefix="vivado-waveform-"))
    temporary_path = temp_dir / (Path(source_path).name or "source.bin")
    digest = hashlib.sha256()
    offset = 0
    try:
        with temporary_path.open("wb") as handle:
            while offset < read_size:
                length = min(READ_CHUNK_BYTES, read_size - offset)
                response = call_host("host.workspace.read_range", {"path": source_path, "offset": offset, "length": length})
                content = base64.b64decode(str(response.get("contentBase64") or "").encode("ascii"))
                actual = int(response.get("length") or len(content))
                if actual != len(content) or actual <= 0 or actual > length:
                    raise ValueError("Host API 返回了无效的分段数据")
                response_size = response.get("fileSizeBytes")
                response_mtime = response.get("mtimeNs")
                if response_size is not None and int(response_size) != file_size:
                    raise ValueError("源文件在读取期间发生变化")
                if response_mtime is not None and str(response_mtime) != mtime_ns:
                    raise ValueError("源文件在读取期间发生变化")
                handle.write(content)
                digest.update(content)
                offset += actual
                if bool(response.get("eof")) and offset < read_size:
                    raise ValueError("Host API 在文件结束前返回 eof")
        identity = {
            "sourcePath": str(stat.get("path") or source_path),
            "mtimeNs": mtime_ns,
            "fileSize": file_size,
            "sha256": digest.hexdigest(),
            "temporaryPath": str(temporary_path),
        }
        return temporary_path, identity, read_size < file_size
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _matching_log_path(source_path: str) -> str:
    return str(Path(source_path).with_suffix(".vivado.log"))


def _read_log(source_path: str) -> dict[str, Any]:
    log_path = _matching_log_path(source_path)
    try:
        temporary_path, _identity, truncated = _materialize_host_file(log_path, max_bytes=MAX_LOG_BYTES)
    except FileNotFoundError:
        return {"logPath": log_path, "testStatus": "unknown", "events": [], "missingSignals": [], "warnings": ["Vivado log not found"]}
    try:
        parsed = parse_vivado_log(temporary_path.read_text(encoding="utf-8", errors="replace"))
        if truncated:
            parsed.setdefault("warnings", []).append(f"Vivado log truncated at {MAX_LOG_BYTES} bytes")
        parsed["logPath"] = log_path
        return parsed
    finally:
        _cleanup_temp_path(temporary_path)


def _summary(index: Any, source_path: str, *, lod_enabled: bool) -> dict[str, Any]:
    summary = build_waveform_summary(index, path=Path(source_path), lod_enabled=lod_enabled)
    summary["log"] = _read_log(source_path)
    return summary


def render_view(input_payload: dict[str, object]) -> dict[str, object]:
    source_path = str(input_payload.get("path") or "").strip()
    if not source_path:
        raise ValueError("缺少 VCD 路径")
    temporary_path, identity, _truncated = _materialize_host_file(source_path)
    try:
        payload = parse_vcd(temporary_path, lod_enabled=_lod_enabled())
        resolved_source_path = str(identity.get("sourcePath") or source_path)
        return {"renderer": "waveform", "title": Path(resolved_source_path).name, "payload": {"path": resolved_source_path, **payload}}
    finally:
        _cleanup_temp_path(temporary_path)


def open_view(input_payload: dict[str, object]) -> dict[str, object]:
    source_path = str(input_payload.get("path") or "").strip()
    if not source_path:
        raise ValueError("缺少 VCD 路径")
    temporary_path, identity, _truncated = _materialize_host_file(source_path)
    resolved_source_path = str(identity.get("sourcePath") or source_path)
    try:
        session_id, index = SESSION_STORE.open(temporary_path, source_identity=identity, temporary_path=temporary_path)
    except Exception:
        _cleanup_temp_path(temporary_path)
        raise
    try:
        lod_enabled = _lod_enabled()
        summary = _summary(index, resolved_source_path, lod_enabled=lod_enabled)
        initial_end = min(float(summary["endTime"]), float(summary["startTime"]) + INITIAL_WINDOW_SPAN)
        initial_window = query_waveform_window(index, start_time=summary["startTime"], end_time=_coerce_time(initial_end), signal_ids=list(summary["defaultSignalIds"]), pixel_width=INITIAL_PIXEL_WIDTH, lod_enabled=lod_enabled)
        return {"renderer": "waveform", "title": Path(resolved_source_path).name, "mode": "session", "sessionId": session_id, "summary": summary, "initialWindow": initial_window}
    except Exception:
        SESSION_STORE.dispose(session_id)
        raise


def get_view_window(params: dict[str, object]) -> dict[str, object]:
    session_id = str(params.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId 不能为空")
    signal_ids = [str(item) for item in list(params.get("signalIds") or [])]
    start_time = _coerce_time(params.get("startTime"))
    end_time = _coerce_time(params.get("endTime"))
    pixel_width = int(params.get("pixelWidth") or INITIAL_PIXEL_WIDTH)
    lod_enabled = _lod_enabled()
    if str(params.get("op") or "") == "inspect":
        return inspect_view(params)
    cache_key = (session_id, start_time, end_time, tuple(signal_ids), pixel_width, lod_enabled)
    cached = SESSION_STORE.get_window_cache(cache_key)
    if cached is not None:
        return cached
    index = SESSION_STORE.get_index(session_id)
    payload = query_waveform_window(index, start_time=start_time, end_time=end_time, signal_ids=signal_ids, pixel_width=pixel_width, lod_enabled=lod_enabled)
    SESSION_STORE.remember_window_cache(cache_key, payload)
    return payload


def inspect_view(params: dict[str, object]) -> dict[str, object]:
    session_id = str(params.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId 不能为空")
    index = SESSION_STORE.get_index(session_id)
    return inspect_waveform(index, time=_coerce_time(params.get("time")), signal_ids=[str(item) for item in list(params.get("signalIds") or [])])


def dispose_view(params: dict[str, object]) -> dict[str, object]:
    session_id = str(params.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId 不能为空")
    return {"disposed": SESSION_STORE.dispose(session_id)}


def run_stdio() -> None:
    try:
        for raw_line in sys.stdin:
            request = json.loads(raw_line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params") or {}
            try:
                if method == "plugin.initialize":
                    write_response(request_id, result={"ok": True, "name": "vivado-waveform"})
                elif method == "plugin.render_view":
                    write_response(request_id, result=render_view(dict(params.get("input") or {})))
                elif method == "plugin.open_view":
                    write_response(request_id, result=open_view(dict(params.get("input") or {})))
                elif method == "plugin.get_view_window":
                    write_response(request_id, result=get_view_window(dict(params)))
                elif method == "plugin.inspect":
                    write_response(request_id, result=inspect_view(dict(params)))
                elif method == "plugin.dispose_view":
                    write_response(request_id, result=dispose_view(dict(params)))
                elif method == "plugin.shutdown":
                    SESSION_STORE.close_all()
                    write_response(request_id, result={"ok": True})
                else:
                    write_response(request_id, error=f"unsupported method: {method}")
            except Exception as exc:  # pragma: no cover - exercised by runtime integration
                write_response(request_id, error=str(exc))
    finally:
        SESSION_STORE.close_all()


if __name__ == "__main__":
    run_stdio()
