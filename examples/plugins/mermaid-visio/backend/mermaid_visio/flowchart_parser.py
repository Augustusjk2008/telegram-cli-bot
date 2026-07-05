from __future__ import annotations

import re

from .models import FlowEdge, FlowGroup, FlowNode, FlowchartIR

DIRECTION_RE = re.compile(r"^\s*(flowchart|graph)\s+(TD|TB|BT|LR|RL)\s*;?\s*$", re.IGNORECASE)
NODE_ID_RE = re.compile(r"^[A-Za-z_][\w:.-]*$")
STYLE_RE = re.compile(r"^\s*style\s+([A-Za-z_][\w:.-]*)\s+(.+?)\s*;?\s*$", re.IGNORECASE)
SUBGRAPH_RE = re.compile(r"^\s*subgraph\s+([A-Za-z_][\w:.-]*)(?:\[(.*?)\])?\s*;?\s*$", re.IGNORECASE)
EDGE_LINE_RE = re.compile(r"^(.+?)\s*(-\.->|==>|-->|---)\s*(?:\|(.*?)\|)?\s*(.+?)\s*;?\s*$")
TEXT_LABEL_EDGE_RE = re.compile(r"^(.+?)\s+--\s+(.+?)\s+-->\s+(.+?)\s*;?\s*$")


class FlowchartParseError(ValueError):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


def parse_node_expr(expr: str) -> FlowNode:
    text = expr.strip().rstrip(";").strip()
    patterns = [
        (r"^(.+?)\[\((.*?)\)\]$", "database"),
        (r"^(.+?)\(\((.*?)\)\)$", "circle"),
        (r"^(.+?)\((.*?)\)$", "terminator"),
        (r"^(.+?)\{(.*?)\}$", "decision"),
        (r"^(.+?)\[(.*?)\]$", "process"),
    ]
    for pattern, kind in patterns:
        match = re.match(pattern, text)
        if match:
            node_id = match.group(1).strip()
            label = match.group(2).strip() or node_id
            if not NODE_ID_RE.match(node_id):
                raise ValueError(f"节点 ID 无效: {node_id}")
            return FlowNode(id=node_id, label=label, kind=kind)
    if not NODE_ID_RE.match(text):
        raise ValueError(f"节点表达式无效: {expr}")
    return FlowNode(id=text, label=text, kind="process")


def parse_flowchart(code: str) -> FlowchartIR:
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ir = FlowchartIR(direction="TD")
    group_stack: list[str] = []
    edge_index = 0
    saw_header = False
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        header = DIRECTION_RE.match(line)
        if header:
            ir.direction = header.group(2).upper()
            saw_header = True
            continue
        if not saw_header:
            raise FlowchartParseError(line_no, "第一条有效语句必须是 flowchart 或 graph")
        subgraph = SUBGRAPH_RE.match(line)
        if subgraph:
            group_id = subgraph.group(1)
            ir.groups[group_id] = FlowGroup(id=group_id, label=subgraph.group(2) or group_id)
            group_stack.append(group_id)
            continue
        if line.lower().rstrip(";") == "end":
            if not group_stack:
                raise FlowchartParseError(line_no, "end 没有匹配的 subgraph")
            group_stack.pop()
            continue
        style_match = STYLE_RE.match(line)
        if style_match:
            node_id = style_match.group(1)
            style = {}
            for item in style_match.group(2).split(","):
                if ":" in item:
                    key, value = item.split(":", 1)
                    style[key.strip()] = value.strip()
            ir.nodes.setdefault(node_id, FlowNode(id=node_id, label=node_id)).style.update(style)
            continue
        parsed = _parse_edge_line(line, edge_index)
        if parsed is not None:
            source_node, edge, target_node = parsed
            edge_index += 1
            for node in (source_node, target_node):
                existing = ir.nodes.get(node.id)
                if existing is None or existing.label == existing.id:
                    node.group_id = group_stack[-1] if group_stack else ""
                    ir.nodes[node.id] = node
                if node.group_id and node.id not in ir.groups[node.group_id].node_ids:
                    ir.groups[node.group_id].node_ids.append(node.id)
            ir.edges.append(edge)
            continue
        try:
            node = parse_node_expr(line)
        except ValueError as exc:
            raise FlowchartParseError(line_no, str(exc)) from exc
        node.group_id = group_stack[-1] if group_stack else ""
        ir.nodes[node.id] = node
        if node.group_id and node.id not in ir.groups[node.group_id].node_ids:
            ir.groups[node.group_id].node_ids.append(node.id)
    if group_stack:
        raise FlowchartParseError(len(lines), "subgraph 未关闭")
    if not ir.nodes and not ir.edges:
        raise FlowchartParseError(1, "Mermaid 图为空")
    return ir


def _parse_edge_line(line: str, edge_index: int) -> tuple[FlowNode, FlowEdge, FlowNode] | None:
    text_label = TEXT_LABEL_EDGE_RE.match(line)
    if text_label:
        source = parse_node_expr(text_label.group(1))
        target = parse_node_expr(text_label.group(3))
        edge = FlowEdge(
            id=f"e{edge_index + 1}",
            source=source.id,
            target=target.id,
            label=text_label.group(2).strip(),
        )
        return source, edge, target

    normal = EDGE_LINE_RE.match(line)
    if not normal:
        return None
    left, operator, label, right = normal.groups()
    source = parse_node_expr(left)
    target = parse_node_expr(right)
    kind = "dotted" if operator == "-.->" else "thick" if operator == "==>" else "solid"
    arrow = "none" if operator == "---" else "end"
    edge = FlowEdge(
        id=f"e{edge_index + 1}",
        source=source.id,
        target=target.id,
        label=(label or "").strip(),
        kind=kind,
        arrow=arrow,
    )
    return source, edge, target
