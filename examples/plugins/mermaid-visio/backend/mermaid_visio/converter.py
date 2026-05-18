from __future__ import annotations

from pathlib import Path

from .dot_layout import build_dot, run_graphviz_plain
from .flowchart_parser import parse_flowchart
from .models import DiagramSource, PluginConfig
from .normalizer import normalize_ir
from .simple_layout import simple_layout
from .vsdx_writer import write_vsdx


def convert_source_to_vsdx(source: DiagramSource, config: PluginConfig, output_path: Path) -> list[str]:
    ir = normalize_ir(parse_flowchart(source.code), config)
    warnings = list(ir.warnings)
    if config.layout_engine == "simple":
        layout = simple_layout(ir)
    else:
        try:
            layout = run_graphviz_plain(build_dot(ir), config)
        except Exception as exc:
            if config.layout_engine == "graphviz" or not config.allow_simple_layout_fallback:
                raise
            layout = simple_layout(ir)
            warnings.append(str(exc))
    warnings.extend(layout.warnings)
    write_vsdx(ir, layout, output_path)
    return warnings
