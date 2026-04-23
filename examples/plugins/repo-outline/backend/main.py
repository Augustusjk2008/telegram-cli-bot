from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

SESSION_COUNTER = 0
NEXT_REQUEST_ID = 9000
SESSIONS: dict[str, "SessionState"] = {}
RUNTIME_CONTEXT: dict[str, Any] = {}


@dataclass
class SessionState:
    session_id: str
    root_path: str
    include_hidden: bool
    max_files: int
    max_symbols_per_file: int
    code_extensions: set[str]
    directory_entries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    directory_children: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    file_symbols: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    search_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    seen_files: set[str] = field(default_factory=set)


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(request_id: Any, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    emit(payload)


def call_host(method: str, params: dict[str, Any]) -> dict[str, Any]:
    global NEXT_REQUEST_ID
    request_id = NEXT_REQUEST_ID
    NEXT_REQUEST_ID += 1
    emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        message = json.loads(line)
        if message.get("method"):
            continue
        if int(message.get("id") or 0) == request_id:
            return message


def host_result(method: str, params: dict[str, Any], error_message: str) -> dict[str, Any]:
    response = call_host(method, params)
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or error_message))
    return dict(response.get("result") or {})


def normalize_path(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text or text == ".":
        return "."
    normalized = PurePosixPath(text).as_posix()
    return normalized[2:] if normalized.startswith("./") else normalized


def plugin_config(context: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest_path = Path(__file__).resolve().parents[1] / "plugin.json"
    file_config: dict[str, Any] = {}
    try:
        file_config = dict(json.loads(manifest_path.read_text(encoding="utf-8")).get("config") or {})
    except Exception:
        file_config = {}
    source = context if isinstance(context, dict) else RUNTIME_CONTEXT
    plugin = source.get("plugin") if isinstance(source.get("plugin"), dict) else {}
    runtime_config = dict(plugin.get("config") or {})
    return {**file_config, **runtime_config}


def bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def parse_extensions(raw_value: Any) -> set[str]:
    parts = str(raw_value or "").split(",")
    extensions = set()
    for part in parts:
        text = part.strip().lower()
        if not text:
            continue
        extensions.add(text if text.startswith(".") else f".{text}")
    return extensions or {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".md"}


def build_session(session_id: str, context: dict[str, Any], input_payload: dict[str, Any]) -> SessionState:
    config = plugin_config(context)
    root_path = normalize_path(str(input_payload.get("path") or input_payload.get("rootPath") or "."))
    return SessionState(
        session_id=session_id,
        root_path=root_path,
        include_hidden=bool(config.get("includeHidden", False)),
        max_files=bounded_int(config.get("maxFiles"), 2000, 200, 20000),
        max_symbols_per_file=bounded_int(config.get("maxSymbolsPerFile"), 200, 20, 1000),
        code_extensions=parse_extensions(config.get("codeExtensions")),
    )


def should_include_file(session: SessionState, path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in session.code_extensions


def stats_text(file_count: int, symbol_count: int) -> str:
    return f"{file_count} 文件 · {symbol_count} 符号"


def build_dir_node(path: str) -> dict[str, Any]:
    pure_path = PurePosixPath(path)
    parent = pure_path.parent.as_posix()
    return {
        "id": f"dir:{path}",
        "label": pure_path.name or path,
        "kind": "folder",
        "secondaryText": "" if parent in {"", "."} else parent,
        "hasChildren": True,
        "payload": {"path": path, "nodeType": "directory"},
    }


def build_file_node(path: str, symbol_count: int | None = None) -> dict[str, Any]:
    pure_path = PurePosixPath(path)
    parent = pure_path.parent.as_posix()
    badges = [{"text": f"{symbol_count} symbols"}] if symbol_count is not None else []
    return {
        "id": f"file:{path}",
        "label": pure_path.name,
        "kind": "file",
        "secondaryText": "" if parent in {"", "."} else parent,
        "badges": badges,
        "hasChildren": True,
        "payload": {"path": path, "nodeType": "file"},
        "actions": [
            {
                "id": "open-file",
                "label": "打开文件",
                "target": "host",
                "location": "node",
                "hostAction": {"type": "open_file", "path": path},
            }
        ],
    }


def normalize_symbol_kind(value: Any) -> str:
    kind = str(value or "symbol").strip().lower()
    return kind if kind in {"class", "function", "method", "heading"} else "symbol"


def build_symbol_node(path: str, item: dict[str, Any]) -> dict[str, Any]:
    line = max(1, int(item.get("line") or 1))
    name = str(item.get("name") or "").strip()
    kind = normalize_symbol_kind(item.get("kind"))
    return {
        "id": f"symbol:{path}:{name}:{line}",
        "label": name,
        "kind": kind,
        "secondaryText": f"{kind} · line {line}",
        "payload": {"path": path, "line": line, "symbol": name, "nodeType": "symbol"},
        "actions": [
            {
                "id": "jump-definition",
                "label": "跳到定义",
                "target": "host",
                "location": "node",
                "hostAction": {"type": "open_file", "path": path, "line": line},
            }
        ],
    }


def update_file_badges(nodes: list[dict[str, Any]], path: str, symbol_count: int) -> None:
    for node in nodes:
        if node.get("id") == f"file:{path}":
            node["badges"] = [{"text": f"{symbol_count} symbols"}]
        children = node.get("children")
        if isinstance(children, list):
            update_file_badges(children, path, symbol_count)


def sync_cached_file_badges(session: SessionState, path: str, symbol_count: int) -> None:
    for nodes in session.directory_children.values():
        update_file_badges(nodes, path, symbol_count)
    for payload in session.search_cache.values():
        cached_nodes = payload.get("nodes")
        if isinstance(cached_nodes, list):
            update_file_badges(cached_nodes, path, symbol_count)


def get_directory_entries(session: SessionState, path: str) -> list[dict[str, Any]]:
    normalized = normalize_path(path)
    cached = session.directory_entries.get(normalized)
    if cached is not None:
        return cached

    host_path = "." if normalized == "." else normalized
    payload = host_result("host.workspace.list_dir", {"path": host_path}, "读取目录失败")
    items: list[dict[str, Any]] = []
    for entry in list(payload.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        if not session.include_hidden and name.startswith("."):
            continue
        relative_path = name if normalized == "." else f"{normalized}/{name}"
        if bool(entry.get("isDir")):
            items.append({"name": name, "path": normalize_path(relative_path), "isDir": True})
            continue
        normalized_file = normalize_path(relative_path)
        if not should_include_file(session, normalized_file):
            continue
        if normalized_file not in session.seen_files and len(session.seen_files) >= session.max_files:
            continue
        session.seen_files.add(normalized_file)
        items.append({"name": name, "path": normalized_file, "isDir": False})

    items.sort(key=lambda item: (not item["isDir"], item["name"].lower()))
    session.directory_entries[normalized] = items
    return items


def get_directory_children(session: SessionState, path: str) -> list[dict[str, Any]]:
    normalized = normalize_path(path)
    cached = session.directory_children.get(normalized)
    if cached is not None:
        return cached

    nodes: list[dict[str, Any]] = []
    for entry in get_directory_entries(session, normalized):
        relative_path = str(entry["path"])
        if entry["isDir"]:
            nodes.append(build_dir_node(relative_path))
            continue
        cached_symbols = session.file_symbols.get(relative_path)
        nodes.append(build_file_node(relative_path, len(cached_symbols) if cached_symbols is not None else None))
    session.directory_children[normalized] = nodes
    session.search_cache.clear()
    return nodes


def get_file_symbols(session: SessionState, path: str) -> list[dict[str, Any]]:
    normalized = normalize_path(path)
    cached = session.file_symbols.get(normalized)
    if cached is not None:
        return cached

    try:
        payload = host_result("host.workspace.outline", {"path": normalized}, "读取文件大纲失败")
    except Exception:
        session.file_symbols[normalized] = []
        sync_cached_file_badges(session, normalized, 0)
        session.search_cache.clear()
        return []
    items: list[dict[str, Any]] = []
    for raw_item in list(payload.get("items") or []):
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        if not name:
            continue
        items.append(build_symbol_node(normalized, raw_item))
        if len(items) >= session.max_symbols_per_file:
            break

    session.file_symbols[normalized] = items
    sync_cached_file_badges(session, normalized, len(items))
    session.search_cache.clear()
    return items


def collect_workspace_files(session: SessionState) -> list[str]:
    files: list[str] = []
    stack = [session.root_path]
    visited: set[str] = set()
    while stack and len(files) < session.max_files:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        entries = get_directory_entries(session, current)
        directory_paths = [str(entry["path"]) for entry in entries if entry["isDir"]]
        for directory_path in reversed(directory_paths):
            stack.append(directory_path)
        for entry in entries:
            if entry["isDir"]:
                continue
            files.append(str(entry["path"]))
            if len(files) >= session.max_files:
                break
    return files


def search_workspace(session: SessionState, query: str) -> dict[str, Any]:
    keyword = query.strip().lower()
    if not keyword:
        root_nodes = get_directory_children(session, session.root_path)
        visible_files = sum(1 for node in root_nodes if str(node.get("id") or "").startswith("file:"))
        return {
            "op": "search",
            "nodes": root_nodes,
            "statsText": stats_text(visible_files, 0),
        }

    cached = session.search_cache.get(keyword)
    if cached is not None:
        return cached

    nodes: list[dict[str, Any]] = []
    matched_symbol_count = 0
    for path in collect_workspace_files(session):
        path_lower = path.lower()
        file_match = keyword in path_lower or keyword in PurePosixPath(path).name.lower()
        symbols = get_file_symbols(session, path)
        matched_symbols = [symbol for symbol in symbols if keyword in str(symbol.get("label") or "").lower()]
        if not file_match and not matched_symbols:
            continue
        file_node = build_file_node(path, len(symbols))
        if matched_symbols:
            file_node["children"] = matched_symbols
            matched_symbol_count += len(matched_symbols)
        nodes.append(file_node)
        if len(nodes) >= 200:
            break

    payload = {
        "op": "search",
        "nodes": nodes,
        "statsText": stats_text(len(nodes), matched_symbol_count),
    }
    session.search_cache[keyword] = payload
    return payload


def toolbar_actions() -> list[dict[str, Any]]:
    return [
        {"id": "refresh-tree", "label": "刷新", "target": "plugin", "location": "toolbar"},
        {"id": "collapse-all", "label": "折叠全部", "target": "plugin", "location": "toolbar"},
    ]


def root_stats(session: SessionState, nodes: list[dict[str, Any]]) -> str:
    visible_files = sum(1 for node in nodes if str(node.get("id") or "").startswith("file:"))
    visible_symbols = sum(len(session.file_symbols.get(str(node.get("payload", {}).get("path") or ""), [])) for node in nodes)
    return stats_text(visible_files, visible_symbols)


def open_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER, RUNTIME_CONTEXT
    RUNTIME_CONTEXT = context
    SESSION_COUNTER += 1
    bot_alias = str(((context.get("host") or {}).get("botAlias")) or "main")
    session_id = f"{bot_alias}-repo-outline-{SESSION_COUNTER}"
    session = build_session(session_id, context, input_payload)
    SESSIONS[session_id] = session
    root_nodes = get_directory_children(session, session.root_path)
    stats = root_stats(session, root_nodes)
    return {
        "renderer": "tree",
        "title": "文件夹大纲",
        "mode": "session",
        "sessionId": session_id,
        "summary": {
            "searchable": True,
            "searchPlaceholder": "搜当前文件夹目录、文件、符号",
            "emptySearchText": "未找到匹配目录、文件、符号",
            "statsText": stats,
            "actions": toolbar_actions(),
        },
        "initialWindow": {
            "op": "children",
            "nodeId": None,
            "nodes": root_nodes,
            "statsText": stats,
        },
    }


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS[str(params.get("sessionId") or "")]
    op = str(params.get("op") or params.get("kind") or "")
    if op == "children":
        node_id = str(params.get("nodeId") or "")
        if not node_id:
            nodes = get_directory_children(session, session.root_path)
            return {"op": "children", "nodeId": None, "nodes": nodes, "statsText": root_stats(session, nodes)}
        if node_id.startswith("dir:"):
            path = node_id.split(":", 1)[1]
            return {"op": "children", "nodeId": node_id, "nodes": get_directory_children(session, path)}
        if node_id.startswith("file:"):
            path = node_id.split(":", 1)[1]
            symbols = get_file_symbols(session, path)
            return {
                "op": "children",
                "nodeId": node_id,
                "nodes": symbols,
                "statsText": stats_text(1, len(symbols)),
            }
        return {"op": "children", "nodeId": node_id, "nodes": []}
    if op == "search":
        return search_workspace(session, str(params.get("query") or ""))
    raise RuntimeError(f"unsupported tree op: {op}")


def invoke_action(params: dict[str, Any]) -> dict[str, Any]:
    action_id = str(params.get("actionId") or "")
    if action_id == "refresh-tree":
        return {"message": "已刷新", "refresh": "session"}
    if action_id == "collapse-all":
        return {"message": "已折叠"}
    return {"message": "已执行"}


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    return {"disposed": SESSIONS.pop(session_id, None) is not None}


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    context = params.get("context") if isinstance(params.get("context"), dict) else {}
    try:
        if method == "plugin.initialize":
            RUNTIME_CONTEXT = context
            respond(request_id, {"ok": True, "name": "repo-outline"})
        elif method == "plugin.render_view":
            respond(request_id, open_view(dict(params.get("input") or {}), context))
        elif method == "plugin.open_view":
            respond(request_id, open_view(dict(params.get("input") or {}), context))
        elif method == "plugin.get_view_window":
            respond(request_id, get_view_window(dict(params)))
        elif method == "plugin.invoke_action":
            respond(request_id, invoke_action(dict(params)))
        elif method == "plugin.dispose_view":
            respond(request_id, dispose_view(dict(params)))
        elif method == "plugin.shutdown":
            respond(request_id, {"ok": True})
        else:
            respond(request_id, error=f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover
        respond(request_id, error=str(exc))
