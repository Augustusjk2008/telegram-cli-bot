from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from docx_parser import inspect_docx_document, parse_docx_document, parse_docx_section
from plugin_sdk import PluginServer

SESSION_COUNTER = 0
SESSIONS: dict[str, dict[str, Any]] = {}
server = PluginServer("docx-preview")


def host_limits() -> dict[str, int]:
    limits = dict((server.context.get("host") or {}).get("limits") or {})
    return {key: int(value) for key, value in limits.items() if str(value).isdigit()}


def read_docx_bytes(path: str) -> bytes:
    return server.read_bytes(path, error_message="读取 DOCX 失败")


def write_artifact(filename: str, content: bytes, content_type: str) -> dict[str, Any]:
    return server.write_artifact(
        filename,
        content,
        content_type,
        error_message="写入插件图片失败",
    )


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 DOCX 路径")
    payload = parse_docx_document(
        path,
        read_docx_bytes(path),
        write_artifact=write_artifact,
        artifact_limits=host_limits(),
    )
    return {
        "renderer": "document",
        "title": str(payload.get("title") or Path(path).name),
        "payload": payload,
    }


def _write_temp_docx(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(prefix="tcb-docx-", suffix=".docx", delete=False) as handle:
        handle.write(content)
        return handle.name


def _dispose_session(session_id: str) -> bool:
    session = SESSIONS.pop(session_id, None)
    if session is None:
        return False
    try:
        Path(str(session["temporaryPath"])).unlink(missing_ok=True)
    except OSError:
        pass
    return True


def open_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 DOCX 路径")
    temporary_path = _write_temp_docx(read_docx_bytes(path))
    try:
        metadata = inspect_docx_document(path, temporary_path, artifact_limits=host_limits())
        sections = list(metadata.get("_sections") or [])
        if not sections:
            raise RuntimeError("DOCX 没有可预览章节")
        SESSION_COUNTER += 1
        session_id = f"docx-preview-{SESSION_COUNTER}"
        SESSIONS[session_id] = {
            "temporaryPath": temporary_path,
            "path": path,
            "sections": {str(section["id"]): section for section in sections},
        }
        first = sections[0]
        initial = parse_docx_section(
            path,
            temporary_path,
            first,
            write_artifact=write_artifact,
            artifact_limits=host_limits(),
        )
        summary = {
            "path": path,
            "title": metadata.get("title") or Path(path).name,
            "statsText": metadata.get("statsText") or "",
            "sections": metadata.get("sections") or [],
        }
        return {
            "renderer": "document",
            "title": str(summary["title"]),
            "mode": "session",
            "sessionId": session_id,
            "summary": summary,
            "initialWindow": initial,
        }
    except Exception:
        Path(temporary_path).unlink(missing_ok=True)
        raise


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    session = SESSIONS.get(session_id)
    if session is None:
        raise RuntimeError("未知 DOCX 会话")
    section_id = str(params.get("sectionId") or "")
    section = session["sections"].get(section_id)
    if section is None:
        raise RuntimeError("未知 DOCX 章节")
    return parse_docx_section(
        str(session["path"]),
        str(session["temporaryPath"]),
        section,
        write_artifact=write_artifact,
        artifact_limits=host_limits(),
    )


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    return {"disposed": _dispose_session(session_id)}


def shutdown() -> None:
    for session_id in list(SESSIONS):
        _dispose_session(session_id)


server.register_handler("plugin.get_view_window", get_view_window)
server.register_handler("plugin.dispose_view", dispose_view)

if __name__ == "__main__":
    server.run(render_view, open_view=open_view, shutdown=shutdown)
