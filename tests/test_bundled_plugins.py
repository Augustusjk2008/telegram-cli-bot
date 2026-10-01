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
            assert manifest.config_schema is not None
            fields = {
                field.key: field
                for section in manifest.config_schema.sections
                for field in section.fields
            }
            assert (fields["maxEntries"].default, fields["maxEntries"].minimum,
                    fields["maxEntries"].maximum) == (2000, 100, 10000)


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
        result = await runtime.render_view("main", manifest, view_id, {"path": filename})
        assert result["renderer"] == renderer
    finally:
        await runtime.shutdown()
