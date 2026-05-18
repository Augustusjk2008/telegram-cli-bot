from __future__ import annotations

from .models import FlowNode, FlowchartIR, PluginConfig


def normalize_ir(ir: FlowchartIR, config: PluginConfig) -> FlowchartIR:
    for edge in ir.edges:
        if edge.source not in ir.nodes:
            ir.nodes[edge.source] = FlowNode(id=edge.source, label=edge.source)
        if edge.target not in ir.nodes:
            ir.nodes[edge.target] = FlowNode(id=edge.target, label=edge.target)
    if len(ir.nodes) > config.max_nodes_per_diagram:
        raise ValueError(f"节点数超过限制: {len(ir.nodes)} > {config.max_nodes_per_diagram}")
    if len(ir.edges) > config.max_edges_per_diagram:
        raise ValueError(f"连线数超过限制: {len(ir.edges)} > {config.max_edges_per_diagram}")
    for group in ir.groups.values():
        group.node_ids = [node_id for node_id in group.node_ids if node_id in ir.nodes]
    return ir
