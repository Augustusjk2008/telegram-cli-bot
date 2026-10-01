from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.runtime import PluginRuntime

REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLES_ROOT = REPO_ROOT / "examples" / "mermaid-visio-samples"

from mermaid_visio.flowchart_parser import FlowchartParseError, parse_flowchart
from mermaid_visio.converter import convert_source_to_vsdx
from mermaid_visio.graphviz_runtime import graphviz_status
from mermaid_visio.models import PluginConfig
from mermaid_visio.normalizer import normalize_ir
from mermaid_visio.source_extractor import extract_diagrams
from vsdx_assertions import assert_vsdx_package


def _read_sample(name: str) -> str:
    return (SAMPLES_ROOT / name).read_text(encoding="utf-8")


def _counts(code: str) -> tuple[int, int]:
    ir = normalize_ir(parse_flowchart(code), PluginConfig(layout_engine="simple"))
    return len(ir.nodes), len(ir.edges)


def _manifest_with_simple_layout():
    manifest = load_plugin_manifest(REPO_ROOT / "examples" / "plugins" / "mermaid-visio" / "plugin.json")
    return replace(
        manifest,
        config={
            **manifest.config,
            "layoutEngine": "simple",
            "allowSimpleLayoutFallback": True,
            "conversionTimeoutSeconds": 20,
        },
    )


def _artifact_id(result: dict) -> str:
    effects = result.get("hostEffects") or []
    for effect in effects:
        if effect.get("type") == "download_artifact":
            return str(effect.get("artifactId") or "")
    raise AssertionError(f"download artifact effect not found: {result}")


def test_sample_sources_are_extracted_with_expected_metadata_and_counts() -> None:
    basic = extract_diagrams("flowchart-basic.mmd", _read_sample("flowchart-basic.mmd"))
    styled = extract_diagrams("subgraph-styled.mermaid", _read_sample("subgraph-styled.mermaid"))
    markdown = extract_diagrams("markdown-multiple.md", _read_sample("markdown-multiple.md"))
    markdown_crlf = extract_diagrams("markdown-multiple.md", _read_sample("markdown-multiple.md").replace("\n", "\r\n"))

    assert [(item.source_id, item.title, item.start_line, item.suggested_filename, _counts(item.code)) for item in basic] == [
        ("diagram-1", "flowchart-basic", 1, "flowchart-basic.vsdx", (8, 8)),
    ]
    assert [(item.source_id, item.title, item.start_line, item.suggested_filename, _counts(item.code)) for item in styled] == [
        ("diagram-1", "subgraph-styled", 1, "subgraph-styled.vsdx", (7, 7)),
    ]
    assert [(item.source_id, item.title, item.start_line, item.suggested_filename, _counts(item.code)) for item in markdown] == [
        ("diagram-1", "业务流程", 6, "业务流程.vsdx", (5, 6)),
        ("diagram-2", "故障处理", 18, "故障处理.vsdx", (7, 7)),
    ]
    assert [(item.title, item.start_line) for item in markdown_crlf] == [("业务流程", 6), ("故障处理", 18)]


def test_normalizer_reports_node_and_edge_limits() -> None:
    too_many_nodes = parse_flowchart("flowchart TD\nA --> B\nB --> C\n")
    with pytest.raises(ValueError, match="节点数超过限制: 3 > 2"):
        normalize_ir(too_many_nodes, PluginConfig(max_nodes_per_diagram=2, layout_engine="simple"))

    too_many_edges = parse_flowchart("flowchart TD\nA --> B\nB --> C\nC --> D\n")
    with pytest.raises(ValueError, match="连线数超过限制: 3 > 2"):
        normalize_ir(too_many_edges, PluginConfig(max_edges_per_diagram=2, layout_engine="simple"))


def test_parser_reports_clear_errors_for_invalid_sources() -> None:
    with pytest.raises(FlowchartParseError, match="第一条有效语句必须是 flowchart 或 graph"):
        parse_flowchart("A --> B")
    with pytest.raises(FlowchartParseError, match="subgraph 未关闭"):
        parse_flowchart("flowchart TD\nsubgraph Group[Group]\nA --> B\n")
    with pytest.raises(FlowchartParseError, match="Mermaid 图为空"):
        parse_flowchart("flowchart TD\n")


def test_parser_accepts_direction_inside_subgraph() -> None:
    ir = parse_flowchart(
        "\n".join(
            [
                "flowchart TB",
                "subgraph APP[任务应用层]",
                "direction LR",
                "SEEK[导引头应用]",
                "FC[飞控应用]",
                "end",
                "SEEK --> FC",
            ]
        )
    )

    assert ir.groups["APP"].node_ids == ["SEEK", "FC"]
    assert [(edge.source, edge.target) for edge in ir.edges] == [("SEEK", "FC")]


def test_graphviz_failure_keeps_simple_layout_fallback(tmp_path: Path) -> None:
    source = extract_diagrams("fallback.mmd", "flowchart TD\nA[Start] --> B[End]\n")[0]
    output = tmp_path / "fallback.vsdx"

    warnings = convert_source_to_vsdx(
        source,
        PluginConfig(dot_path=str(tmp_path / "missing-dot.exe"), allow_simple_layout_fallback=True),
        output,
    )

    assert output.is_file()
    assert any("Graphviz 不可用" in warning for warning in warnings)


def test_graphviz_status_exposes_controlled_install_intent() -> None:
    status = graphviz_status(PluginConfig())

    assert status["installAvailable"] is True
    assert "graphvizRuntimeUrl" not in status


@pytest.mark.asyncio
async def test_graphviz_install_action_emits_only_host_install_intent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "fallback.mmd").write_text("flowchart TD\nA --> B\n", encoding="utf-8")
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=30,
    )
    manifest = _manifest_with_simple_layout()

    try:
        opened = await runtime.open_view("main", manifest, "mermaid-visio", {"path": "fallback.mmd"})
        install_action = next(
            action for action in opened["summary"]["actions"] if action["id"] == "install-graphviz"
        )
        assert install_action["confirm"] == {
            "title": "安装 Graphviz 运行时",
            "message": "将从受控官方来源下载并安装 Graphviz 16.1.0 运行时，是否继续？",
        }
        assert not {"url", "path", "runtimeId", "targetPath"} & set(install_action)
        result = await runtime.invoke_action(
            "main",
            manifest,
            view_id="mermaid-visio",
            session_id=opened["sessionId"],
            action_id="install-graphviz",
            payload={},
        )
    finally:
        await runtime.shutdown()

    assert result["refresh"] == "view"
    assert result["hostEffects"] == [{"type": "install_plugin_runtime"}]


def test_parser_expands_chained_edges() -> None:
    ir = parse_flowchart("flowchart TB\nL1[第一层] --> L2[第二层] --> L3[第三层]\n")

    assert list(ir.nodes) == ["L1", "L2", "L3"]
    assert [(edge.id, edge.source, edge.target) for edge in ir.edges] == [
        ("e1", "L1", "L2"),
        ("e2", "L2", "L3"),
    ]


@pytest.mark.asyncio
async def test_plugin_runtime_export_one_writes_valid_vsdx_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "flowchart-basic.mmd").write_text(_read_sample("flowchart-basic.mmd"), encoding="utf-8")
    store = ArtifactStore(tmp_path)
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(store),
        call_timeout_seconds=30,
    )
    manifest = _manifest_with_simple_layout()

    try:
        opened = await runtime.open_view("main", manifest, "mermaid-visio", {"path": "flowchart-basic.mmd"})
        result = await runtime.invoke_action(
            "main",
            manifest,
            view_id="mermaid-visio",
            session_id=opened["sessionId"],
            action_id="export-one",
            payload={"rowId": "diagram-1"},
        )
        record = store.get(bot_alias="main", artifact_id=_artifact_id(result))
        assert record.filename == "flowchart-basic.vsdx"
        assert record.content_type == "application/vnd.ms-visio.drawing"
        assert_vsdx_package(record.path.read_bytes(), min_shapes=8)
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_export_all_packages_multiple_valid_vsdx_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "markdown-multiple.md").write_text(_read_sample("markdown-multiple.md"), encoding="utf-8")
    store = ArtifactStore(tmp_path)
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(store),
        call_timeout_seconds=30,
    )
    manifest = _manifest_with_simple_layout()

    try:
        opened = await runtime.open_view("main", manifest, "mermaid-visio", {"path": "markdown-multiple.md"})
        result = await runtime.invoke_action(
            "main",
            manifest,
            view_id="mermaid-visio",
            session_id=opened["sessionId"],
            action_id="export-all",
            payload={},
        )
        record = store.get(bot_alias="main", artifact_id=_artifact_id(result))
        assert record.filename == "mermaid-visio-export.zip"
        assert record.content_type == "application/zip"

        with zipfile.ZipFile(record.path) as archive:
            names = sorted(archive.namelist())
            assert names == ["conversion-report.json", "业务流程.vsdx", "故障处理.vsdx"]
            report = json.loads(archive.read("conversion-report.json"))
            assert [item["ok"] for item in report] == [True, True]
            for name in names:
                if name.endswith(".vsdx"):
                    assert_vsdx_package(archive.read(name), min_shapes=5)
    finally:
        await runtime.shutdown()
