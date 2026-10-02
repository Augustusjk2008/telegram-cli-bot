"""Session views over static HDL indexes and verified Host source locations."""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import islice
from uuid import uuid4

from hdl_models import SourceLocation
from hdl_project import ProjectIndex, ProjectScanner, READ_CHUNK_BYTES, ScanOptions, WorkspacePaths


COLUMNS = (
    ("kind", "类别"), ("name", "名称"), ("direction", "方向"), ("type", "类型"),
    ("width", "位宽/数组"), ("default", "默认值"), ("override", "实例覆盖"),
    ("context", "静态条件"), ("evidence", "推断依据"), ("source", "声明位置"),
)
SEARCH_LIMIT = 200
CHILD_LIMIT = 2000


@dataclass
class _Resource:
    index: ProjectIndex
    id: str = field(default_factory=lambda: str(uuid4()))
    references: int = 0


@dataclass(frozen=True)
class _Node:
    kind: str
    definition_id: str | None = None
    reference_id: str | None = None
    chain: tuple[str, ...] = ()
    cycle: bool = False
    diagnostic: int | None = None
    group: str | None = None
    search: bool = False


@dataclass(frozen=True)
class _Row:
    cells: dict
    location: SourceLocation


@dataclass
class _Session:
    view_id: str
    resource: _Resource
    id: str = field(default_factory=lambda: str(uuid4()))
    definition_id: str | None = None
    reference_id: str | None = None
    nodes: dict[str, _Node] = field(default_factory=dict)
    node_ids: dict[tuple, str] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    reference_ids: dict[str, str] = field(default_factory=dict)
    rows: dict[str, _Row] = field(default_factory=dict)


def _action(action_id: str, label: str, location: str, **payload) -> dict:
    return {"id": action_id, "label": label, "target": "plugin", "location": location, "payload": payload}


def _detail_title(index: ProjectIndex, definition_id: str, reference_id: str | None = None) -> str:
    name = index.definitions[definition_id].name
    if reference_id:
        name += f" ({index.references[reference_id].instance.name})"
    return f"{name} · 端口/参数"


def _page(params: dict, default: int = 50) -> tuple[int, int]:
    offset, limit = params.get("offset", 0), params.get("limit", default)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 必须为非负整数")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit 必须为正整数")
    return offset, min(limit, 500)


class HdlViews:
    def __init__(self, parser, host_call, context: dict, config: dict) -> None:
        host = deepcopy(context.get("host") or {})
        self._parser = parser
        self._host_call = host_call
        workspace_root = host.get("workspaceRoot")
        self._paths = WorkspacePaths(workspace_root) if workspace_root else None
        self._bot_alias = host.get("botAlias")
        self._options = ScanOptions.from_config(deepcopy(config))
        self._read_bytes = (host.get("limits") or {}).get("readBytes", self._options.max_file_bytes)
        self._sessions: dict[str, _Session] = {}
        self._resources: dict[str, _Resource] = {}

    def _check_context(self, params: dict) -> None:
        context = params.get("context") or {}
        if not isinstance(context, dict) or not isinstance(context.get("host", {}), dict):
            raise ValueError("无效的视图上下文")
        for scope in (context, context.get("host", {})):
            if "botAlias" in scope and scope["botAlias"] != self._bot_alias:
                raise ValueError("视图不属于当前 bot")

    def _session(self, params: dict) -> _Session:
        self._check_context(params)
        session_id = params.get("sessionId")
        if not isinstance(session_id, str) or session_id not in self._sessions:
            raise ValueError("视图会话不存在或已释放")
        return self._sessions[session_id]

    def _scan(self, path: str) -> ProjectIndex:
        return ProjectScanner(self._parser, self._host_call, self._paths.root, self._options,
                              host_read_bytes=self._read_bytes).scan(path)

    def open_view(self, params: dict) -> dict:
        self._check_context(params)
        if self._paths is None:
            raise ValueError("Host 未提供 workspaceRoot，无法打开项目视图")
        view_id = params.get("viewId")
        if view_id not in {"module-tree", "module-details"}:
            raise ValueError("不支持的 HDL 视图")
        input_payload = params.get("input", {})
        if not isinstance(input_payload, dict):
            raise ValueError("视图 input 必须为对象")
        reference_id = None
        if "parentSessionId" in input_payload:
            if view_id != "module-details":
                raise ValueError("只有模块详情可以复用父会话")
            parent = self._session({"sessionId": input_payload["parentSessionId"]})
            if parent.view_id != "module-tree":
                raise ValueError("父会话必须为模块树")
            resource = parent.resource
            path = self._paths.absolute(self._paths.root, input_payload.get("path", resource.index.root_path))
            if self._paths.key(path) != self._paths.key(resource.index.root_path):
                raise ValueError("详情目录与父会话不一致")
            if "referenceId" in input_payload:
                token = input_payload["referenceId"]
                if not isinstance(token, str) or token not in parent.references:
                    raise ValueError("实例引用不属于父会话")
                reference_id = parent.references[token]
        else:
            if "referenceId" in input_payload:
                raise ValueError("实例引用需要有效的父会话")
            resource = _Resource(self._scan(input_payload.get("path", ".")))
        session = _Session(view_id, resource, definition_id=input_payload.get("definitionId"), reference_id=reference_id)
        index = resource.index
        if view_id == "module-details":
            if not isinstance(session.definition_id, str) or session.definition_id not in index.definitions:
                raise ValueError("模块定义不在当前项目索引中")
            if reference_id and session.definition_id not in index.references[reference_id].candidate_ids:
                raise ValueError("实例引用与模块定义不匹配")
            self._build_rows(session)
            title = _detail_title(index, session.definition_id, reference_id)
            summary = {
                "columns": [{"id": key, "title": title, "sortable": True, "wrap": True} for key, title in COLUMNS],
                "totalRows": len(session.rows), "defaultPageSize": 50,
                "actions": [_action("open-definition", "打开定义", "toolbar")],
            }
            initial = self._table_window(session, {})
        else:
            title = "HDL 模块层级"
            summary = {"searchable": True, "searchPlaceholder": "搜索模块、实例或诊断", "statsText": self._stats(index),
                       "actions": [_action("refresh-project", "刷新项目", "toolbar")]}
            initial = {"op": "children", "nodeId": None, "nodes": self._roots(session), "statsText": self._stats(index)}
        resource.references += 1
        self._resources[resource.id] = resource
        self._sessions[session.id] = session
        return {"renderer": "tree" if view_id == "module-tree" else "table", "mode": "session",
                "dataProfile": "light" if view_id == "module-tree" else "heavy", "title": title,
                "sessionId": session.id, "summary": summary, "initialWindow": initial}

    def _node_id(self, session: _Session, key: tuple, node: _Node) -> str:
        if key not in session.node_ids:
            node_id = str(uuid4())
            session.node_ids[key] = node_id
            session.nodes[node_id] = node
        return session.node_ids[key]

    def _reference_token(self, session: _Session, reference_id: str) -> str:
        if reference_id not in session.reference_ids:
            token = str(uuid4())
            session.reference_ids[reference_id] = token
            session.references[token] = reference_id
        return session.reference_ids[reference_id]

    def _roots(self, session: _Session) -> list[dict]:
        index = session.resource.index
        groups = (("tops", "指定顶层" if self._options.top_modules else "候选顶层",
                   index.selected_top_ids if self._options.top_modules else index.candidate_top_ids),
                  ("all", "全部模块", index.definitions), ("diagnostics", "诊断", index.diagnostics))
        return [{"id": self._node_id(session, ("group", group), _Node("group", group=group)),
                 "label": label, "kind": "folder", "hasChildren": bool(items)} for group, label, items in groups]

    def _module_node(self, session: _Session, key: tuple, definition_id: str, chain: tuple[str, ...] = (),
                     reference_id: str | None = None, *, search: bool = False) -> dict:
        cycle = definition_id in chain
        node = _Node("module", definition_id, reference_id, (*chain, definition_id), cycle, search=search)
        return self._render_node(session, self._node_id(session, key, node))

    def _instance_node(self, session: _Session, key: tuple, reference_id: str, chain: tuple[str, ...],
                       *, search: bool = False) -> dict:
        reference = session.resource.index.references[reference_id]
        target = reference.candidate_ids[0] if reference.status == "resolved" else None
        token = self._reference_token(session, reference_id)
        node = _Node("instance", target, token, (*chain, target) if target else chain, target in chain, search=search)
        return self._render_node(session, self._node_id(session, key, node))

    def _diagnostic_node(self, session: _Session, number: int) -> dict:
        node_id = self._node_id(session, ("diagnostic", number), _Node("diagnostic", diagnostic=number))
        return self._render_node(session, node_id)

    def _render_node(self, session: _Session, node_id: str) -> dict:
        node, index = session.nodes[node_id], session.resource.index
        badges = []
        if node.kind == "diagnostic":
            item = index.diagnostics[node.diagnostic]
            label, location, contexts = item.message, item.location, ()
            badges.append({"text": item.code, "tone": "danger" if item.severity == "error" else "warning"})
            actions = ([_action("open-diagnostic", "打开位置", "node", nodeId=node_id)]
                       if any(self._paths.key(file.path) == self._paths.key(location.path) for file in index.files) else [])
            has_children = False
        elif node.kind == "module":
            item = index.definitions[node.definition_id]
            label, location, contexts = item.name, item.location, item.contexts
            has_children = bool(index.references_by_owner[node.definition_id]) and not node.cycle
            actions = [_action("open-details", "查看端口/参数", "node", nodeId=node_id),
                       _action("open-definition", "打开定义", "node", nodeId=node_id)]
            if item.incomplete:
                badges.append({"text": "解析不完整", "tone": "warning"})
        else:
            reference = index.references[session.references[node.reference_id]]
            item = reference.instance
            label, location, contexts = f"{item.name}{''.join(item.array_dimensions)} : {item.module_name}", item.location, item.contexts
            has_children = bool(reference.candidate_ids) and not node.cycle and (
                reference.status == "ambiguous" or bool(index.references_by_owner[node.definition_id]))
            actions = ([_action("open-details", "查看端口/参数", "node", nodeId=node_id)] if node.definition_id else [])
            actions.append(_action("open-instance", "打开实例化位置", "node", nodeId=node_id))
            if reference.status in {"ambiguous", "missing"}:
                badges.append({"text": "多个候选" if reference.status == "ambiguous" else "未解析", "tone": "warning"})
            if item.array_dimensions:
                badges.append({"text": "实例数组 " + " ".join(item.array_dimensions), "tone": "info"})
        if node.cycle:
            badges.append({"text": "循环引用", "tone": "warning"})
        badges.extend({"text": text, "tone": "info"} for text in contexts)
        return {"id": node_id, "label": label, "kind": "symbol", "secondaryText": self._location_label(session, location),
                "badges": badges, "hasChildren": has_children and not node.search, "actions": actions}

    def _location_label(self, session: _Session, location: SourceLocation, *, column: bool = False) -> str:
        prefix = session.resource.index.root_path.rstrip("/") + "/"
        path = location.path
        if self._paths.key(path).startswith(self._paths.key(prefix)):
            path = path[len(prefix):]
        return f"{path}:{location.start_line}" + (f":{location.start_column}" if column else "")

    def _children(self, session: _Session, node_id: str | None) -> list[dict]:
        if node_id is None or node_id == "":
            return self._roots(session)
        if not isinstance(node_id, str) or node_id not in session.nodes:
            raise ValueError("节点不属于当前会话")
        node, index = session.nodes[node_id], session.resource.index
        if node.kind == "group":
            if node.group == "diagnostics":
                return self._limited_children(node_id, range(len(index.diagnostics)),
                                              lambda number: self._diagnostic_node(session, number))
            definitions = (index.selected_top_ids if self._options.top_modules else index.candidate_top_ids) if node.group == "tops" else index.definitions
            return self._limited_children(node_id, definitions,
                                          lambda key: self._module_node(session, ("module", node_id, key), key))
        if node.cycle or node.kind == "diagnostic":
            return []
        if node.kind == "instance" and not node.definition_id:
            reference = index.references[session.references[node.reference_id]]
            return self._limited_children(node_id, reference.candidate_ids,
                lambda key: self._module_node(session, ("candidate", node_id, key), key, node.chain, node.reference_id))
        return self._limited_children(node_id, index.references_by_owner[node.definition_id],
            lambda reference: self._instance_node(session, ("instance", node_id, reference.id), reference.id, node.chain))

    @staticmethod
    def _limited_children(node_id: str, items, render) -> list[dict]:
        nodes = [render(item) for item in islice(items, CHILD_LIMIT)]
        if len(items) > CHILD_LIMIT:
            nodes.append({"id": f"truncated:{node_id}", "kind": "symbol", "hasChildren": False,
                          "label": f"仅显示前 {CHILD_LIMIT} / {len(items)} 个直接节点",
                          "secondaryText": "窗口已截断；使用搜索定位其余模块、实例或诊断。",
                          "badges": [{"text": "窗口截断", "tone": "warning"}]})
        return nodes

    @staticmethod
    def _stats(index: ProjectIndex) -> str:
        text = f"{len(index.files)} 个文件 · {len(index.definitions)} 个模块 · {len(index.references)} 个静态实例 · {len(index.diagnostics)} 条诊断"
        for status, label in (("missing", "未解析"), ("ambiguous", "多候选")):
            count = sum(item.status == status for item in index.references.values())
            if count:
                text += f" · {count} 个{label}引用"
        return text + (" · 分析不完整" if index.incomplete else "")

    def _search(self, session: _Session, params: dict) -> dict:
        query = params.get("query", "")
        if not isinstance(query, str):
            raise ValueError("query 必须为字符串")
        keyword = query.strip().casefold()
        if not keyword:
            return {"op": "search", "nodes": self._roots(session), "statsText": self._stats(session.resource.index)}
        _, limit = _page(params, SEARCH_LIMIT)
        index, nodes, matched = session.resource.index, [], 0
        for kind, items in (("module", index.definitions.items()), ("instance", index.references.items()),
                            ("diagnostic", enumerate(index.diagnostics))):
            for key, item in items:
                entity = item.instance if kind == "instance" else item
                text = (f"{entity.name} {entity.module_name}" if kind == "instance" else entity.name if kind == "module"
                        else f"{entity.code} {entity.message}")
                if keyword not in f"{text} {entity.location.path} {' '.join(getattr(entity, 'contexts', ()))}".casefold():
                    continue
                matched += 1
                if len(nodes) >= limit:
                    continue
                if kind == "module":
                    nodes.append(self._module_node(session, ("search-module", key), key, search=True))
                elif kind == "instance":
                    nodes.append(self._instance_node(session, ("search-instance", key), key, (item.owner_id,), search=True))
                else:
                    nodes.append(self._diagnostic_node(session, key))
        truncated = matched > len(nodes)
        return {"op": "search", "nodes": nodes, "stats": {"matched": matched, "returned": len(nodes), "truncated": truncated},
                "statsText": f"显示 {len(nodes)} / {matched} 个匹配" + (" · 结果已截断" if truncated else "")}

    def _build_rows(self, session: _Session) -> None:
        index = session.resource.index
        module = index.definitions[session.definition_id]
        parameters = sorted((item for item in module.parameters if item.kind == "parameter"), key=lambda item: item.location.start_byte)
        overrides = {}
        instance_contexts = ()
        if session.reference_id:
            instance = index.references[session.reference_id].instance
            instance_contexts = instance.contexts
            for item in instance.parameter_overrides:
                if item.name is not None:
                    for parameter in parameters:
                        if parameter.name == item.name:
                            overrides[parameter.location.start_byte] = item.expression
                elif item.position < len(parameters):
                    overrides[parameters[item.position].location.start_byte] = item.expression
        for port in module.ports:
            self._row(session, port.location, {"kind": "端口", "name": port.name, "direction": port.direction,
                      "type": port.type_expression, "width": " ".join(filter(None, (port.width_expression, *port.unpacked_dimensions))),
                      "default": port.default_expression, "override": None,
                      "context": " · ".join(dict.fromkeys((*instance_contexts, *port.contexts)))})
        for parameter in module.parameters:
            self._row(session, parameter.location, {"kind": parameter.kind, "name": parameter.name, "direction": None,
                      "type": parameter.type_expression, "width": "", "default": parameter.default_expression,
                      "override": overrides.get(parameter.location.start_byte),
                      "context": " · ".join(dict.fromkeys((*instance_contexts, *parameter.contexts)))})
        for signal in module.signals:
            self._row(session, signal.location, {
                "kind": "时钟候选" if signal.kind == "clock" else "复位候选",
                "name": signal.expression, "evidence": signal.evidence,
                "context": " · ".join(dict.fromkeys((*instance_contexts, *signal.contexts))),
            })

    def _row(self, session: _Session, location: SourceLocation, cells: dict) -> None:
        for key, _title in COLUMNS:
            cells.setdefault(key, None)
        cells["source"] = self._location_label(session, location, column=True)
        session.rows[str(uuid4())] = _Row(cells, location)

    def _table_window(self, session: _Session, params: dict) -> dict:
        offset, limit = _page(params)
        query = params.get("query", "")
        if not isinstance(query, str):
            raise ValueError("query 必须为字符串")
        keyword = query.strip().casefold()
        rows = [(key, row) for key, row in session.rows.items()
                if not keyword or any(keyword in str(value or "").casefold() for value in row.cells.values())]
        sort = params.get("sort")
        if sort is not None:
            if (not isinstance(sort, dict) or sort.get("columnId") not in {key for key, _ in COLUMNS}
                    or sort.get("direction") not in {"asc", "desc"}):
                raise ValueError("无效的表格排序")
            rows.sort(key=lambda item: str(item[1].cells[sort["columnId"]] or "").casefold(), reverse=sort["direction"] == "desc")
        payload = {"offset": offset, "limit": limit, "totalRows": len(rows), "rows": [
            {"id": key, "cells": dict(row.cells), "actions": [_action("open-declaration", "打开声明", "row", rowId=key)]}
            for key, row in rows[offset:offset + limit]
        ]}
        if sort is not None:
            payload["appliedSort"] = dict(sort)
        return payload

    def get_view_window(self, params: dict) -> dict:
        session = self._session(params)
        if session.view_id == "module-details":
            return self._table_window(session, params)
        op = params.get("op", "children")
        if op == "search":
            return self._search(session, params)
        if op != "children":
            raise ValueError("不支持的树操作")
        return {"op": "children", "nodeId": params.get("nodeId"), "nodes": self._children(session, params.get("nodeId"))}

    def _host(self, method: str, params: dict) -> dict:
        response = self._host_call(method, params)
        if not isinstance(response, dict) or response.get("error") or not isinstance(response.get("result"), dict):
            raise ValueError("Host 无法核验源码")
        return response["result"]

    def _source_action(self, session: _Session, location: SourceLocation) -> dict:
        try:
            file = next((item for item in session.resource.index.files
                         if self._paths.key(item.path) == self._paths.key(location.path)), None)
            if file is None:
                raise ValueError("位置不在源码索引中")
            def check_stat() -> None:
                metadata = self._host("host.workspace.stat", {"path": file.path})
                path = self._paths.absolute(self._paths.root, metadata["path"])
                if (self._paths.key(path) != self._paths.key(file.path) or not metadata.get("exists") or metadata.get("isDir")
                        or metadata["size"] != file.size_bytes or str(metadata["mtimeNs"]) != file.mtime_ns):
                    raise ValueError("源码身份或状态变化")
            check_stat()
            digest, offset = sha256(), 0
            while offset < file.size_bytes:
                length = min(READ_CHUNK_BYTES, file.size_bytes - offset)
                result = self._host("host.workspace.read_range", {"path": file.path, "offset": offset, "length": length})
                path = self._paths.absolute(self._paths.root, result["path"])
                if (self._paths.key(path) != self._paths.key(file.path) or result["fileSizeBytes"] != file.size_bytes
                        or str(result["mtimeNs"]) != file.mtime_ns or result["offset"] != offset):
                    raise ValueError("源码读取身份变化")
                encoded = result["contentBase64"]
                if not isinstance(encoded, str) or len(encoded) > ((length + 2) // 3) * 4:
                    raise ValueError("源码读取超过请求范围")
                chunk = base64.b64decode(encoded, validate=True)
                if len(chunk) != length or result["length"] != length or bool(result["eof"]) != (offset + length == file.size_bytes):
                    raise ValueError("源码读取不完整")
                digest.update(chunk)
                offset += length
            check_stat()
            if digest.hexdigest() != file.sha256:
                raise ValueError("源码内容变化")
        except (RuntimeError, ValueError, KeyError, TypeError):
            return {"message": "源码已变化或无法核验，请在层级视图点击“刷新项目”后重新打开详情。", "refresh": "none", "hostEffects": []}
        return {"refresh": "none", "hostEffects": [{"type": "open_file", "path": location.path,
                "line": location.start_line, "column": location.start_column}]}

    def invoke_action(self, params: dict) -> dict:
        session = self._session(params)
        if params.get("viewId") != session.view_id:
            raise ValueError("动作与视图不匹配")
        action_id, payload = params.get("actionId"), params.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("动作 payload 必须为对象")
        index = session.resource.index
        if action_id == "refresh-project" and session.view_id == "module-tree":
            # Host removes this view's cache/session before the frontend reopens it.
            return {"refresh": "view", "hostEffects": []}
        if session.view_id == "module-details":
            if action_id == "open-definition" and "rowId" not in payload and "nodeId" not in payload:
                return self._source_action(session, index.definitions[session.definition_id].location)
            row_id = payload.get("rowId")
            if action_id != "open-declaration" or not isinstance(row_id, str) or row_id not in session.rows:
                raise ValueError("声明行不属于当前会话或动作无效")
            return self._source_action(session, session.rows[row_id].location)
        node_id = payload.get("nodeId")
        if not isinstance(node_id, str) or node_id not in session.nodes:
            raise ValueError("节点不属于当前会话")
        node = session.nodes[node_id]
        if action_id == "open-details" and node.definition_id:
            input_payload = {"path": index.root_path, "parentSessionId": session.id, "definitionId": node.definition_id}
            if node.reference_id:
                input_payload["referenceId"] = node.reference_id
            return {"refresh": "none", "hostEffects": [{"type": "open_plugin_view", "pluginId": "hdl-workbench",
                    "viewId": "module-details", "title": _detail_title(index, node.definition_id,
                        session.references[node.reference_id] if node.reference_id else None),
                    "input": input_payload}]}
        if action_id == "open-definition" and node.kind == "module":
            return self._source_action(session, index.definitions[node.definition_id].location)
        if action_id == "open-instance" and node.kind == "instance":
            return self._source_action(session, index.references[session.references[node.reference_id]].instance.location)
        if action_id == "open-diagnostic" and node.kind == "diagnostic":
            return self._source_action(session, index.diagnostics[node.diagnostic].location)
        raise ValueError("节点不支持此动作")

    def dispose_view(self, params: dict) -> dict:
        self._check_context(params)
        session_id = params.get("sessionId")
        if not isinstance(session_id, str):
            raise ValueError("缺少会话 ID")
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {"disposed": False}
        session.resource.references -= 1
        if not session.resource.references:
            self._resources.pop(session.resource.id)
        return {"disposed": True}

    def shutdown(self) -> dict:
        for resource in self._resources.values():
            resource.references = 0
        self._sessions.clear()
        self._resources.clear()
        return {"ok": True}
