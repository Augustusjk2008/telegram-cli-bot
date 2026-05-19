from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiagramSource:
    source_id: str
    title: str
    code: str
    start_line: int
    suggested_filename: str


@dataclass
class DiagramStatus:
    source: DiagramSource
    status: str = "ready"
    node_count: int = 0
    edge_count: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    artifact_filename: str = ""


@dataclass(frozen=True)
class PluginConfig:
    conversion_timeout_seconds: int = 45
    graphviz_timeout_seconds: int = 8
    max_source_bytes: int = 1048576
    max_diagrams_per_export: int = 20
    max_nodes_per_diagram: int = 200
    max_edges_per_diagram: int = 400
    layout_engine: str = "auto"
    allow_simple_layout_fallback: bool = True
    dot_path: str = "dot"
    bundled_graphviz_enabled: bool = True
    graphviz_runtime_version: str = ""
    graphviz_runtime_url: str = ""
    graphviz_runtime_sha256: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PluginConfig":
        def integer(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(payload.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        layout_engine = str(payload.get("layoutEngine") or "auto").strip()
        if layout_engine not in {"auto", "graphviz", "simple"}:
            layout_engine = "auto"
        return cls(
            conversion_timeout_seconds=integer("conversionTimeoutSeconds", 45, 2, 55),
            graphviz_timeout_seconds=integer("graphvizTimeoutSeconds", 8, 1, 30),
            max_source_bytes=integer("maxSourceBytes", 1048576, 4096, 10 * 1048576),
            max_diagrams_per_export=integer("maxDiagramsPerExport", 20, 1, 100),
            max_nodes_per_diagram=integer("maxNodesPerDiagram", 200, 1, 1000),
            max_edges_per_diagram=integer("maxEdgesPerDiagram", 400, 1, 2000),
            layout_engine=layout_engine,
            allow_simple_layout_fallback=bool(payload.get("allowSimpleLayoutFallback", True)),
            dot_path=str(payload.get("dotPath") or "dot").strip() or "dot",
            bundled_graphviz_enabled=bool(payload.get("bundledGraphvizEnabled", True)),
            graphviz_runtime_version=str(payload.get("graphvizRuntimeVersion") or "").strip(),
            graphviz_runtime_url=str(payload.get("graphvizRuntimeUrl") or "").strip(),
            graphviz_runtime_sha256=str(payload.get("graphvizRuntimeSha256") or "").strip().lower(),
        )


@dataclass
class FlowNode:
    id: str
    label: str
    kind: str = "process"
    group_id: str = ""
    style: dict[str, str] = field(default_factory=dict)


@dataclass
class FlowEdge:
    id: str
    source: str
    target: str
    label: str = ""
    kind: str = "solid"
    arrow: str = "end"


@dataclass
class FlowGroup:
    id: str
    label: str
    node_ids: list[str] = field(default_factory=list)


@dataclass
class FlowchartIR:
    direction: str
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    edges: list[FlowEdge] = field(default_factory=list)
    groups: dict[str, FlowGroup] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LayoutNode:
    id: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class LayoutEdge:
    id: str
    source: str
    target: str
    points: list[tuple[float, float]]
    label_pos: tuple[float, float] | None = None


@dataclass(frozen=True)
class LayoutResult:
    width: float
    height: float
    nodes: dict[str, LayoutNode]
    edges: dict[str, LayoutEdge]
    warnings: list[str] = field(default_factory=list)
