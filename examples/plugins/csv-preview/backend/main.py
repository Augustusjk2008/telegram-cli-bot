from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from csv_parser import CsvTableIndex, query_csv_window
from csv_source import CsvSourceIdentity, TemporaryCsvSource, copy_csv_source
from plugin_sdk import PluginServer

SESSION_COUNTER = 0
server = PluginServer("csv-preview")


@dataclass
class CsvResource:
    source: TemporaryCsvSource
    index: CsvTableIndex
    references: int = 0


@dataclass
class CsvSession:
    session_id: str
    source_path: str
    resource_key: tuple[CsvSourceIdentity, int, str]
    resource: CsvResource


SESSIONS: dict[str, CsvSession] = {}
RESOURCES: dict[tuple[CsvSourceIdentity, int, str], CsvResource] = {}


def call_host(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return server.host_call(method, params)


def resolve_path(input_payload: dict[str, Any]) -> str:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 CSV 路径")
    return str(Path(path))


def release_resource(
    key: tuple[CsvSourceIdentity, int, str], resource: CsvResource
) -> None:
    resource.references -= 1
    if resource.references == 0:
        RESOURCES.pop(key, None)
        try:
            resource.index.close()
        finally:
            resource.source.close()


def open_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    path = resolve_path(input_payload)
    config = ((context.get("plugin") or {}).get("config") or {})
    default_page_size = max(1, min(500, int(config.get("defaultPageSize", 50))))
    header_mode = str(config.get("headerMode") or "auto")
    if header_mode not in {"auto", "header", "no-header"}:
        raise ValueError(f"无效的 CSV 表头模式: {header_mode}")

    source = copy_csv_source(path, context, call_host)
    key = (source.identity, default_page_size, header_mode)
    resource = RESOURCES.get(key)
    if resource is not None:
        source.close()
    else:
        try:
            index = CsvTableIndex.build(
                source.temporary_path,
                Path(source.directory.name) / "table.sqlite",
                title=Path(path).name,
                default_page_size=default_page_size,
                header_mode=header_mode,
            )
        except BaseException:
            source.close()
            raise
        resource = CsvResource(source, index)
        RESOURCES[key] = resource
    resource.references += 1
    try:
        index = resource.index
        initial_window = query_csv_window(index, offset=0, limit=default_page_size)
        SESSION_COUNTER += 1
        session_id = (
            f"{((context.get('host') or {}).get('botAlias') or 'main')}"
            f"-csv-{SESSION_COUNTER}"
        )
        SESSIONS[session_id] = CsvSession(session_id, path, key, resource)
        return {
            "renderer": "table",
            "title": index.title,
            "mode": "session",
            "sessionId": session_id,
            "summary": {
                "columns": index.columns,
                "totalRows": index.total_rows,
                "defaultPageSize": default_page_size,
                "actions": [],
                "metadata": index.metadata,
            },
            "initialWindow": initial_window,
        }
    except BaseException:
        release_resource(key, resource)
        raise


def render_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    opened = open_view(input_payload, context)
    try:
        return {
            "renderer": "table",
            "title": opened["title"],
            "payload": {
                "columns": opened["summary"]["columns"],
                "rows": opened["initialWindow"]["rows"],
                "actions": opened["summary"]["actions"],
            },
        }
    finally:
        dispose_view({"sessionId": opened["sessionId"]})


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS[str(params.get("sessionId") or "")]
    table = session.resource.index
    return query_csv_window(
        table,
        offset=int(params.get("offset") or 0),
        limit=int(params.get("limit") or table.metadata["defaultPageSize"]),
        query=str(params.get("query") or ""),
        sort=params.get("sort") if isinstance(params.get("sort"), dict) else None,
    )


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS.pop(str(params.get("sessionId") or ""), None)
    if session is not None:
        release_resource(session.resource_key, session.resource)
    return {"disposed": session is not None}


def shutdown() -> None:
    for session_id in list(SESSIONS):
        dispose_view({"sessionId": session_id})
    for key, resource in list(RESOURCES.items()):
        RESOURCES.pop(key, None)
        try:
            resource.index.close()
        finally:
            resource.source.close()


def render_request(params: dict[str, Any]) -> dict[str, Any]:
    context = params.get("context") if isinstance(params.get("context"), dict) else {}
    return render_view(dict(params.get("input") or {}), context)


def open_request(params: dict[str, Any]) -> dict[str, Any]:
    context = params.get("context") if isinstance(params.get("context"), dict) else {}
    return open_view(dict(params.get("input") or {}), context)


server.register_handler("plugin.render_view", render_request)
server.register_handler("plugin.open_view", open_request)
server.register_handler("plugin.get_view_window", get_view_window)
server.register_handler("plugin.dispose_view", dispose_view)


def main() -> None:
    server.run(shutdown=shutdown)


if __name__ == "__main__":
    main()
