from __future__ import annotations

import json
import shutil
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.runtime import PluginRuntime
from bot.plugins.service import PluginService


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCX_PLUGIN = REPO_ROOT / "examples" / "plugins" / "docx-preview"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _docx_bytes() -> bytes:
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>正文</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第二章</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>第二节正文</w:t></w:r></w:p>'
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}</w:body></w:document>',
        )
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_docx_session_runs_from_copied_plugin_directory(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "docx-preview"
    shutil.copytree(DOCX_PLUGIN, plugin_dir)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.docx").write_bytes(_docx_bytes())

    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=10,
    )
    try:
        manifest = load_plugin_manifest(plugin_dir / "plugin.json")
        opened = await runtime.open_view("main", manifest, "document", {"path": "sample.docx"})
        assert opened["renderer"] == "document"
        assert opened["mode"] == "session"
        assert opened["summary"]["sections"]
        session_id = str(opened["sessionId"])
        first_id = str(opened["initialWindow"]["sectionId"])
        window = await runtime.get_view_window(
            "main",
            manifest,
            session_id,
            {"sectionId": "section-2" if first_id == "section-1" else first_id},
        )
        assert window["sectionId"]
        assert window["blocks"]
        disposed = await runtime.dispose_view("main", manifest, session_id)
        assert disposed["disposed"] is True
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_docx_manifest_and_runtime_upgrade_together(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    plugin_dir = plugins_root / "docx-preview"
    shutil.copytree(DOCX_PLUGIN, plugin_dir)
    entry = plugin_dir / "backend" / "main.py"
    entry.write_text(
        entry.read_text(encoding="utf-8").replace(
            "server.run(render_view, open_view=open_view, shutdown=shutdown)",
            "server.run(render_view)",
        ),
        encoding="utf-8",
    )
    manifest_path = plugin_dir / "plugin.json"
    installed_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    installed_raw["views"][0]["viewMode"] = "snapshot"
    manifest_path.write_text(json.dumps(installed_raw), encoding="utf-8")
    (tmp_path / "sample.docx").write_bytes(_docx_bytes())
    service = PluginService(tmp_path, plugins_root=plugins_root, source_plugins_root=DOCX_PLUGIN.parent)
    request = dict(
        bot_alias="main", plugin_id="docx-preview", view_id="document",
        input_payload={"path": "sample.docx"}, audit_context={},
    )
    try:
        await service.reload_plugins()
        snapshot = await service.open_view(**request)
        assert snapshot["mode"] == "snapshot"
        assert snapshot["payload"]["blocks"]

        await service.install_plugin("docx-preview", force=True)
        opened = await service.open_view(**request)
        assert opened["mode"] == "session"
        window = await service.get_view_window(
            bot_alias="main", plugin_id="docx-preview", session_id=opened["sessionId"],
            request_payload={"sectionId": "section-2"}, audit_context={},
        )
        assert window["sectionId"] == "section-2"
        assert window["blocks"]
    finally:
        await service.shutdown()
