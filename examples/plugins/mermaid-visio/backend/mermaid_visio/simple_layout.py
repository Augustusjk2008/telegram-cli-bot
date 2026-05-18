from __future__ import annotations

from collections import defaultdict, deque

from .models import FlowchartIR, LayoutEdge, LayoutNode, LayoutResult


def simple_layout(ir: FlowchartIR) -> LayoutResult:
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in ir.nodes}
    for edge in ir.edges:
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] = indegree.get(edge.target, 0) + 1
    queue = deque([node_id for node_id, count in indegree.items() if count == 0])
    remaining = set(ir.nodes)
    ranks: dict[str, int] = {}
    cycle_detected = False
    while remaining:
        if not queue:
            cycle_detected = True
            queue.append(next(node_id for node_id in ir.nodes if node_id in remaining))
        node_id = queue.popleft()
        if node_id not in remaining:
            continue
        remaining.remove(node_id)
        rank = ranks.get(node_id, 0)
        for target in outgoing[node_id]:
            if target not in remaining:
                continue
            ranks[target] = max(ranks.get(target, 0), rank + 1)
            indegree[target] -= 1
            if indegree[target] <= 0:
                queue.append(target)
    buckets: dict[int, list[str]] = defaultdict(list)
    for node_id in ir.nodes:
        buckets[ranks.get(node_id, 0)].append(node_id)

    max_rank = max(buckets.keys(), default=0)
    horizontal = ir.direction in {"LR", "RL"}
    reverse = ir.direction in {"RL", "TD", "TB"}
    nodes: dict[str, LayoutNode] = {}
    for rank, node_ids in buckets.items():
        display_rank = max_rank - rank if reverse else rank
        for index, node_id in enumerate(node_ids):
            width, height = _node_size(ir.nodes[node_id].label, ir.nodes[node_id].kind)
            x = 1.0 + (display_rank * 2.2 if horizontal else index * 2.4)
            y = 1.0 + (index * 1.3 if horizontal else display_rank * 1.4)
            nodes[node_id] = LayoutNode(id=node_id, x=x, y=y, width=width, height=height)

    edges = {
        edge.id: LayoutEdge(
            id=edge.id,
            source=edge.source,
            target=edge.target,
            points=[(nodes[edge.source].x, nodes[edge.source].y), (nodes[edge.target].x, nodes[edge.target].y)],
            label_pos=((nodes[edge.source].x + nodes[edge.target].x) / 2, (nodes[edge.source].y + nodes[edge.target].y) / 2)
            if edge.label else None,
        )
        for edge in ir.edges
        if edge.source in nodes and edge.target in nodes
    }
    width = max((node.x + node.width / 2 for node in nodes.values()), default=1.0) + 1.0
    height = max((node.y + node.height / 2 for node in nodes.values()), default=1.0) + 1.0
    warnings = ["已使用简单布局"]
    if cycle_detected:
        warnings.append("检测到回环，已按简单布局处理")
    return LayoutResult(width=width, height=height, nodes=nodes, edges=edges, warnings=warnings)


def _node_size(label: str, kind: str) -> tuple[float, float]:
    width = max(1.2, min(3.2, 0.25 + len(label) * 0.14))
    height = 0.8 if kind == "decision" else 0.6
    return width, height
