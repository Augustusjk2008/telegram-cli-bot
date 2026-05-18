from __future__ import annotations

import subprocess

from .models import FlowchartIR, LayoutEdge, LayoutNode, LayoutResult, PluginConfig

RANKDIR = {"TD": "TB", "TB": "TB", "BT": "BT", "LR": "LR", "RL": "RL"}
GV_SHAPES = {
    "process": "box",
    "terminator": "rect",
    "decision": "diamond",
    "circle": "circle",
    "database": "cylinder",
}


class LayoutTimeout(RuntimeError):
    pass


def build_dot(ir: FlowchartIR) -> str:
    lines = [
        "digraph G {",
        f'  graph [rankdir={RANKDIR.get(ir.direction, "TB")}, splines=ortho, nodesep=0.6, ranksep=0.8];',
        '  node [fontname="Microsoft YaHei", fontsize=12, margin="0.12,0.08"];',
    ]
    for node in ir.nodes.values():
        label = node.label.replace("\\", "\\\\").replace('"', '\\"')
        shape = GV_SHAPES.get(node.kind, "box")
        lines.append(f'  "{node.id}" [label="{label}", shape={shape}, width=1.2, height=0.5];')
    for edge in ir.edges:
        attrs = []
        if edge.label:
            attrs.append(f'label="{edge.label.replace("\\", "\\\\").replace(chr(34), "\\\"")}"')
        if edge.kind == "dotted":
            attrs.append("style=dotted")
        if edge.kind == "thick":
            attrs.append("penwidth=2")
        attr_text = f" [{', '.join(attrs)}]" if attrs else ""
        lines.append(f'  "{edge.source}" -> "{edge.target}"{attr_text};')
    lines.append("}")
    return "\n".join(lines) + "\n"


def run_graphviz_plain(dot: str, config: PluginConfig) -> LayoutResult:
    try:
        completed = subprocess.run(
            [config.dot_path, "-Tplain"],
            input=dot,
            text=True,
            capture_output=True,
            timeout=config.graphviz_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LayoutTimeout(f"Graphviz 超时: {config.graphviz_timeout_seconds}s") from exc
    except OSError as exc:
        raise RuntimeError(f"Graphviz 不可用: {config.dot_path}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Graphviz 失败: {completed.stderr.strip()}")
    return parse_plain(completed.stdout)


def parse_plain(text: str) -> LayoutResult:
    width = 1.0
    height = 1.0
    nodes: dict[str, LayoutNode] = {}
    edges: dict[str, LayoutEdge] = {}
    edge_index = 0
    for raw in text.splitlines():
        parts = raw.split()
        if not parts:
            continue
        if parts[0] == "graph":
            width = float(parts[2])
            height = float(parts[3])
        elif parts[0] == "node":
            nodes[parts[1].strip('"')] = LayoutNode(
                id=parts[1].strip('"'),
                x=float(parts[2]),
                y=float(parts[3]),
                width=float(parts[4]),
                height=float(parts[5]),
            )
        elif parts[0] == "edge":
            point_count = int(parts[3])
            coords = parts[4:4 + point_count * 2]
            points = [(float(coords[index]), float(coords[index + 1])) for index in range(0, len(coords), 2)]
            edge_index += 1
            label_pos = None
            if len(parts) >= 4 + point_count * 2 + 3:
                try:
                    label_pos = (float(parts[4 + point_count * 2 + 1]), float(parts[4 + point_count * 2 + 2]))
                except ValueError:
                    label_pos = None
            edges[f"e{edge_index}"] = LayoutEdge(id=f"e{edge_index}", source=parts[1], target=parts[2], points=points, label_pos=label_pos)
    return LayoutResult(width=width, height=height, nodes=nodes, edges=edges)
