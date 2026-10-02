from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.host_api import PluginHostApi
from bot.plugins.runtime import PluginRuntime

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PLUGINS_ROOT = REPO_ROOT / "examples" / "plugins"


def test_bundled_plugin_manifests_load_with_basic_contracts() -> None:
    manifest_paths = sorted(BUNDLED_PLUGINS_ROOT.glob("*/plugin.json"))
    assert manifest_paths, "expected bundled plugin manifests"

    seen_ids: set[str] = set()
    for manifest_path in manifest_paths:
        manifest = load_plugin_manifest(manifest_path)

        assert manifest.root == manifest_path.parent.resolve()
        assert manifest.plugin_id
        assert manifest.plugin_id not in seen_ids
        seen_ids.add(manifest.plugin_id)
        assert manifest.schema_version == 2
        assert manifest.name
        assert manifest.version

        assert manifest.runtime.runtime_type
        assert manifest.runtime.entry
        assert manifest.runtime.protocol
        assert (manifest.root / manifest.runtime.entry).is_file()
        if manifest.plugin_id in {"hex-preview", "zip-preview", "xlsx-preview", "pdf-preview", "pptx-preview"}:
            assert (manifest.root / "backend" / "plugin_sdk.py").is_file()

        view_ids = {view.id for view in manifest.views}
        assert view_ids
        for view in manifest.views:
            assert view.title
            assert view.renderer
            assert view.view_mode in {"snapshot", "session"}
            assert view.data_profile in {"light", "heavy"}

        for handler in manifest.file_handlers:
            assert handler.id
            assert handler.label
            assert handler.view_id in view_ids
            assert handler.extensions
            assert all(extension.startswith(".") for extension in handler.extensions)

        if manifest.plugin_id == "csv-preview":
            assert manifest.config["defaultPageSize"] == 50
            assert manifest.config["headerMode"] == "auto"
            assert manifest.config_schema is not None
            fields = {
                field.key: field
                for section in manifest.config_schema.sections
                for field in section.fields
            }
            assert fields["defaultPageSize"].minimum == 1
            assert fields["defaultPageSize"].maximum == 500
            assert [option.value for option in fields["headerMode"].options] == [
                "auto",
                "header",
                "no-header",
            ]

        if manifest.plugin_id == "hex-preview":
            assert manifest.config_schema is not None
            fields = {
                field.key: field
                for section in manifest.config_schema.sections
                for field in section.fields
            }
            assert (fields["maxPreviewBytes"].default, fields["maxPreviewBytes"].minimum,
                    fields["maxPreviewBytes"].maximum) == (16384, 256, 262144)
            assert (fields["bytesPerRow"].default, fields["bytesPerRow"].minimum,
                    fields["bytesPerRow"].maximum) == (16, 8, 32)
            assert (fields["entropyBuckets"].default, fields["entropyBuckets"].minimum,
                    fields["entropyBuckets"].maximum) == (48, 8, 256)

        if manifest.plugin_id == "zip-preview":
            assert manifest.views[0].view_mode == "session"
            assert manifest.config_schema is not None
            fields = {
                field.key: field
                for section in manifest.config_schema.sections
                for field in section.fields
            }
            assert (fields["maxEntries"].default, fields["maxEntries"].minimum,
                    fields["maxEntries"].maximum) == (2000, 100, 10000)


def test_hdl_workbench_catalog_and_session_contract() -> None:
    manifest = load_plugin_manifest(BUNDLED_PLUGINS_ROOT / "hdl-workbench/plugin.json")
    assert manifest.runtime.permissions.workspace_read
    assert manifest.runtime.permissions.workspace_list
    assert not manifest.runtime.permissions.temp_artifacts
    assert {view.id: (view.renderer, view.view_mode) for view in manifest.views} == {
        "module-tree": ("tree", "session"),
        "module-details": ("table", "session"),
    }
    fields = {
        field.key: field
        for section in manifest.config_schema.sections
        for field in section.fields
    }
    assert set(fields) == {
        "topModule", "ignoreDirectories", "includeDirectories",
        "maxFiles", "maxFileBytes", "maxTotalBytes",
    }
    assert {key: field.default for key, field in fields.items()} == manifest.config
    action, = manifest.catalog_actions
    assert action.target == "host" and action.location == "catalog"
    assert action.payload["folderPicker"] is True
    assert action.payload["folderInputKey"] == "path"
    assert action.host_action["pluginId"] == manifest.plugin_id
    assert action.host_action["viewId"] == "module-tree"


def _xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>value</t></is></c>'
            "</row></sheetData></worksheet>",
        )
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plugin_id", "filename", "content", "view_id", "renderer"),
    [
        ("hex-preview", "sample.bin", b"\x00hello", "hex", "hex"),
        ("zip-preview", "sample.zip", b"", "archive-tree", "tree"),
        ("xlsx-preview", "sample.xlsx", _xlsx_bytes(), "document", "document"),
    ],
)
async def test_simple_bundled_plugins_run_from_copied_directories(
    tmp_path: Path,
    plugin_id: str,
    filename: str,
    content: bytes,
    view_id: str,
    renderer: str,
) -> None:
    if plugin_id == "zip-preview":
        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, "w") as archive:
            archive.writestr("folder/file.txt", "content")
        content = archive_buffer.getvalue()

    plugin_dir = tmp_path / "plugins" / plugin_id
    shutil.copytree(BUNDLED_PLUGINS_ROOT / plugin_id, plugin_dir)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / filename).write_bytes(content)

    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=10,
    )
    try:
        manifest = load_plugin_manifest(plugin_dir / "plugin.json")
        if plugin_id == "zip-preview":
            result = await runtime.open_view("main", manifest, view_id, {"path": filename})
            assert result["mode"] == "session"
            assert result["initialWindow"]["nodes"][0]["children"] == []
            session_id = result["sessionId"]
            children = await runtime.get_view_window(
                "main", manifest, session_id, {"op": "children", "nodeId": "dir:folder"},
            )
            assert [node["label"] for node in children["nodes"]] == ["file.txt"]
            snapshot = await runtime.render_view("main", manifest, view_id, {"path": filename})
            assert snapshot["payload"]["roots"][0]["children"] == children["nodes"]
            with pytest.raises(RuntimeError, match="目录节点不存在"):
                await runtime.get_view_window(
                    "main", manifest, session_id, {"op": "children", "nodeId": "dir:unknown"},
                )
            assert (await runtime.dispose_view("main", manifest, session_id))["disposed"] is True
            assert (await runtime.dispose_view("main", manifest, session_id))["disposed"] is False
            with pytest.raises(RuntimeError, match="会话不存在或已释放"):
                await runtime.get_view_window("main", manifest, session_id, {"op": "children"})
        else:
            result = await runtime.render_view("main", manifest, view_id, {"path": filename})
        assert result["renderer"] == renderer
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_copied_rtl_plugin_omits_source_actions_and_preserves_tree_and_copy(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "rtl-hierarchy"
    shutil.copytree(BUNDLED_PLUGINS_ROOT / "rtl-hierarchy", plugin_dir)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "design.hier"
    source.write_text("top\n  u_core\n    alu\n  u_mem\n", encoding="utf-8")
    manifest = load_plugin_manifest(plugin_dir / "plugin.json")
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=10,
    )
    try:
        snapshot = await runtime.render_view("main", manifest, "module-tree", {"path": str(source)})
        opened = await runtime.open_view("main", manifest, "module-tree", {"path": str(source)})
        session_id = opened["sessionId"]
        children = await runtime.get_view_window(
            "main", manifest, session_id, {"op": "children", "nodeId": "top"},
        )
        assert [node["id"] for node in children["nodes"]] == ["top.u_core", "top.u_mem"]
        search = await runtime.get_view_window("main", manifest, session_id, {"op": "search", "query": "alu"})
        assert [node["id"] for node in search["nodes"]] == ["top.u_core.alu"]
        for nodes in (
            snapshot["payload"]["roots"], opened["summary"]["roots"],
            opened["initialWindow"]["nodes"], children["nodes"], search["nodes"],
        ):
            for node in nodes:
                assert [action["id"] for action in node["actions"]] == ["copy-name"]
                assert node["actions"][0]["hostAction"] == {"type": "copy_text", "text": node["label"]}

        for legacy_session_id in (session_id, None, "missing-session"):
            result = await runtime.invoke_action(
                "main", manifest, view_id="module-tree", session_id=legacy_session_id,
                action_id="open-source", payload={"nodeId": "top.u_core", "path": "src/index.ts", "line": 12},
            )
            assert result["message"] == "缺少源码定位信息"
            assert result.get("hostEffects", []) == []

        copied = await runtime.invoke_action(
            "main", manifest, view_id="module-tree", session_id=session_id,
            action_id="copy-name", payload={"nodeId": "top.u_core"},
        )
        assert copied["hostEffects"] == [{"type": "copy_text", "text": "top.u_core"}]
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_copied_timing_plugin_omits_source_actions_and_preserves_exports(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "timing-report"
    shutil.copytree(BUNDLED_PLUGINS_ROOT / "timing-report", plugin_dir)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "timing.rpt"
    source.write_text("endpoint,slack\nrx_data,-0.132\ntx_data,-0.081\n", encoding="utf-8")
    manifest = load_plugin_manifest(plugin_dir / "plugin.json")
    artifacts = ArtifactStore(tmp_path)
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(artifacts),
        call_timeout_seconds=10,
    )
    try:
        snapshot = await runtime.render_view("main", manifest, "timing-table", {"path": str(source)})
        opened = await runtime.open_view("main", manifest, "timing-table", {"path": str(source)})
        session_id = opened["sessionId"]
        window = await runtime.get_view_window(
            "main", manifest, session_id, {"offset": 0, "limit": 1, "query": "tx_data"},
        )
        assert [row["cells"]["endpoint"] for row in window["rows"]] == ["tx_data"]
        for rows in (snapshot["payload"]["rows"], opened["initialWindow"]["rows"], window["rows"]):
            assert all([action["id"] for action in row["actions"]] == ["export-row"] for row in rows)
        for toolbar in (snapshot["payload"]["actions"], opened["summary"]["actions"]):
            assert [action["id"] for action in toolbar] == ["export-all"]

        for legacy_session_id in (session_id, None, "missing-session"):
            result = await runtime.invoke_action(
                "main", manifest, view_id="timing-table", session_id=legacy_session_id,
                action_id="open-source", payload={"rowId": "path-1", "path": "src/index.ts", "line": 12},
            )
            assert result["message"] == "缺少源码定位信息"
            assert result.get("hostEffects", []) == []

        for action_id, payload, expected_csv in (
            ("export-row", {"rowId": "path-2"}, "endpoint,slack\ntx_data,-0.081\n"),
            ("export-all", {}, "endpoint,slack\nrx_data,-0.132\ntx_data,-0.081\n"),
        ):
            exported = await runtime.invoke_action(
                "main", manifest, view_id="timing-table", session_id=session_id,
                action_id=action_id, payload=payload,
            )
            assert len(exported["hostEffects"]) == 1
            effect = exported["hostEffects"][0]
            assert effect["type"] == "download_artifact"
            assert effect["filename"] == "timing.csv"
            artifact = artifacts.get(bot_alias="main", artifact_id=effect["artifactId"])
            assert artifact.path.read_text(encoding="utf-8") == expected_csv
    finally:
        await runtime.shutdown()
