from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterator

import pytest

from bot.plugins.service import PluginService


PLUGIN_SOURCE = Path(__file__).resolve().parents[1] / "examples" / "plugins" / "mermaid-visio"
BACKEND_SOURCE = PLUGIN_SOURCE / "backend"


@contextlib.contextmanager
def plugin_backend_path() -> Iterator[None]:
    backend = str(BACKEND_SOURCE)
    inserted = backend not in sys.path
    if inserted:
        sys.path.insert(0, backend)
    try:
        yield
    finally:
        if inserted:
            sys.path.remove(backend)


def _copy_plugin(tmp_path: Path) -> Path:
    plugins_root = tmp_path / "plugins"
    plugins_root.mkdir()
    shutil.copytree(PLUGIN_SOURCE, plugins_root / "mermaid-visio")
    return plugins_root


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("design.md", "# 总图\n```mermaid\nflowchart TD\nA --> B\n```\n"),
        ("design.mmd", "flowchart TD\nA --> B\n"),
        ("design.mermaid", "flowchart TD\nA --> B\n"),
    ],
)
def test_plugin_service_resolves_mermaid_sources_as_file_with_plugin_target(
    tmp_path: Path,
    filename: str,
    content: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source = repo_root / filename
    source.write_text(content, encoding="utf-8")

    service = PluginService(repo_root, plugins_root=_copy_plugin(tmp_path))

    target = service.resolve_file_target(str(source))

    assert target == {
        "kind": "file",
        "pluginTargets": [
            {
                "pluginId": "mermaid-visio",
                "viewId": "mermaid-visio",
                "title": "Mermaid 转 Visio",
                "input": {"path": str(source)},
            }
        ],
    }


def test_extracts_raw_mmd_and_markdown_mermaid_blocks() -> None:
    with plugin_backend_path():
        from mermaid_visio.source_extractor import extract_diagrams

        raw = extract_diagrams("demo.mmd", "flowchart TD\nA[开始] --> B[结束]\n")
        markdown = extract_diagrams(
            "design.md",
            """# 总图

```mermaid
flowchart TD
A --> B
```

## 子图

~~~mmd
graph LR
C --> D
~~~
""",
        )

    assert len(raw) == 1
    assert raw[0].title == "demo"
    assert raw[0].suggested_filename == "demo.vsdx"
    assert [item.title for item in markdown] == ["总图", "子图"]
    assert [item.suggested_filename for item in markdown] == ["总图.vsdx", "子图.vsdx"]


def test_parser_supports_flowchart_subset() -> None:
    with plugin_backend_path():
        from mermaid_visio.flowchart_parser import parse_flowchart
        from mermaid_visio.models import PluginConfig
        from mermaid_visio.normalizer import normalize_ir

        ir = normalize_ir(
            parse_flowchart(
                """flowchart TD
subgraph S1[用户侧]
  A[开始] -->|是| B{判断}
end
B -- 否 --> C[(库)]
style A fill:#fff,stroke:#333,color:#111
"""
            ),
            PluginConfig(),
        )

    assert ir.direction == "TD"
    assert ir.nodes["A"].label == "开始"
    assert ir.nodes["B"].kind == "decision"
    assert ir.nodes["C"].kind == "database"
    assert ir.edges[0].label == "是"
    assert ir.edges[1].label == "否"
    assert ir.groups["S1"].node_ids == ["A", "B"]
    assert ir.nodes["A"].style["fill"] == "#fff"


def test_vsdx_writer_creates_visio_zip_with_page_shapes(tmp_path: Path) -> None:
    with plugin_backend_path():
        from mermaid_visio.converter import convert_source_to_vsdx
        from mermaid_visio.models import DiagramSource, PluginConfig

        output = tmp_path / "demo.vsdx"
        warnings = convert_source_to_vsdx(
            DiagramSource(
                "diagram-1",
                "demo",
                "flowchart TD\n"
                "A[开始] --> B{判断}\n"
                "B --> C[(归档)]\n"
                "style A fill:#eef6ff,stroke:#2563eb,color:#111827\n",
                1,
                "demo.vsdx",
            ),
            PluginConfig(layout_engine="simple"),
            output,
        )

    assert output.read_bytes().startswith(b"PK")
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        page_xml = archive.read("visio/pages/page1.xml").decode("utf-8")
        document_xml = archive.read("visio/document.xml").decode("utf-8")
    assert "[Content_Types].xml" in names
    assert "visio/document.xml" in names
    assert "开始" in page_xml
    assert "判断" in page_xml
    assert "归档" in page_xml
    assert '<cp IX="0"/><pp IX="0"/>开始' in page_xml
    assert '<Cell N="Font" V="Microsoft YaHei"/>' in page_xml
    assert '<Cell N="AsianFont" V="Microsoft YaHei"/>' in page_xml
    assert '<Cell N="ComplexScriptFont" V="Microsoft YaHei"/>' in page_xml
    assert '<Cell N="FillForegnd" V="#eef6ff" F="THEMEGUARD(RGB(238,246,255))"/>' in page_xml
    assert '<Cell N="LineColor" V="#2563eb" F="THEMEGUARD(RGB(37,99,235))"/>' in page_xml
    assert '<Cell N="Color" V="#111827" F="THEMEGUARD(RGB(17,24,39))"/>' in page_xml
    assert '<Cell N="EndArrow" V="4"/>' in page_xml
    assert 'Row T="Ellipse"' in page_xml
    assert 'NameU="Microsoft YaHei"' in document_xml
    assert warnings == ["已使用简单布局"]


def test_simple_layout_converts_cyclic_flowchart_without_graphviz(tmp_path: Path) -> None:
    output = tmp_path / "cycle.vsdx"
    script = f"""
import sys
from pathlib import Path

sys.path.insert(0, {str(BACKEND_SOURCE)!r})

from mermaid_visio.converter import convert_source_to_vsdx
from mermaid_visio.models import DiagramSource, PluginConfig

convert_source_to_vsdx(
    DiagramSource("diagram-1", "cycle", "flowchart TD\\nA --> B\\nB --> C\\nC --> A\\n", 1, "cycle.vsdx"),
    PluginConfig(layout_engine="simple"),
    Path(sys.argv[1]),
)
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(output)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("simple layout timed out for cyclic flowchart")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert output.read_bytes().startswith(b"PK")


def test_export_selected_marks_budget_exhaustion_without_calling_worker() -> None:
    with plugin_backend_path():
        from mermaid_visio.export_actions import export_selected
        from mermaid_visio.models import DiagramSource, DiagramStatus, PluginConfig

        calls = []
        status = DiagramStatus(
            source=DiagramSource("diagram-1", "demo", "flowchart TD\nA --> B", 1, "demo.vsdx")
        )
        result = export_selected(
            [status],
            PluginConfig(conversion_timeout_seconds=2),
            convert_one=lambda source, config, timeout: calls.append(source) or None,
            clock=iter([0.0, 0.5]).__next__,
        )[0]

    assert result.ok is False
    assert result.error == "批量转换预算耗尽"
    assert calls == []
    assert status.status == "error"


@pytest.mark.asyncio
async def test_plugin_opens_markdown_and_exports_multiple_diagrams_as_zip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source = repo_root / "design.md"
    source.write_text(
        """# 总图
```mermaid
flowchart TD
A[开始] --> B[结束]
```
# 子图
```mermaid
flowchart LR
C --> D
```
""",
        encoding="utf-8",
    )
    service = PluginService(repo_root, plugins_root=_copy_plugin(tmp_path))

    opened = await service.open_view(
        bot_alias="main",
        plugin_id="mermaid-visio",
        view_id="mermaid-visio",
        input_payload={"path": str(source)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    result = await service.invoke_action(
        bot_alias="main",
        plugin_id="mermaid-visio",
        view_id="mermaid-visio",
        session_id=opened["sessionId"],
        action_id="export-all",
        payload={},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert opened["renderer"] == "table"
    assert [row["cells"]["title"] for row in opened["initialWindow"]["rows"]] == ["总图", "子图"]
    effect = result["hostEffects"][0]
    artifact = service.get_artifact(bot_alias="main", artifact_id=effect["artifactId"])
    with zipfile.ZipFile(artifact.path) as archive:
        names = set(archive.namelist())
        report = json.loads(archive.read("conversion-report.json").decode("utf-8"))

    assert effect["type"] == "download_artifact"
    assert artifact.filename == "mermaid-visio-export.zip"
    assert {"总图.vsdx", "子图.vsdx", "conversion-report.json"} <= names
    assert all(item["ok"] for item in report)
    await service.shutdown()


@pytest.mark.asyncio
async def test_plugin_export_timeout_returns_message_without_artifact(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source = repo_root / "demo.mmd"
    source.write_text("flowchart TD\nA --> B\n", encoding="utf-8")
    plugins_root = _copy_plugin(tmp_path)
    manifest_path = plugins_root / "mermaid-visio" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["config"]["conversionTimeoutSeconds"] = 2
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="mermaid-visio",
        view_id="mermaid-visio",
        input_payload={"path": str(source)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    result = await service.invoke_action(
        bot_alias="main",
        plugin_id="mermaid-visio",
        view_id="mermaid-visio",
        session_id=opened["sessionId"],
        action_id="export-all",
        payload={},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert result["hostEffects"] == []
    assert "预算" in result["message"]
    await service.shutdown()
