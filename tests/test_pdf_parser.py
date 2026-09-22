from __future__ import annotations

import importlib.util
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.runtime import PluginRuntime


PARSER = Path(__file__).resolve().parents[1] / "examples/plugins/pdf-preview/backend/pdf_parser.py"
spec = importlib.util.spec_from_file_location("tested_pdf_parser", PARSER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def pdf_bytes(*, pages=2, title=None, password=None):
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=300, height=400)
        if index:
            page.rotate(90)
    if title:
        writer.add_metadata({"/Title": title})
    if password is not None:
        writer.encrypt(password)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("title", [None, "原始版式"])
def test_preserves_original_pdf_without_requiring_a_text_layer(title):
    content = pdf_bytes(title=title)
    write = Mock(return_value={"artifactId": "pdf-artifact"})
    payload = module.parse_pdf_document("folder/sample.pdf", content, write_artifact=write)
    write.assert_called_once_with("sample.pdf", content, "application/pdf")
    assert payload == {
        "path": "folder/sample.pdf", "title": title or "sample.pdf",
        "statsText": "2 页", "pdf": {"artifactId": "pdf-artifact"}, "blocks": [],
    }


@pytest.mark.parametrize(("content", "message"), [
    (b"not a pdf", "文件损坏"),
    (pdf_bytes(pages=0), "没有可预览"),
    (pdf_bytes(password="secret"), "需要密码"),
])
def test_rejects_unreadable_documents_before_writing_artifacts(content, message):
    write = Mock()
    with pytest.raises(RuntimeError, match=message):
        module.parse_pdf_document("sample.pdf", content, write_artifact=write)
    write.assert_not_called()


def test_accepts_encryption_with_an_empty_user_password():
    payload = module.parse_pdf_document("sample.pdf", pdf_bytes(password=""),
                                        write_artifact=lambda *_: {"artifactId": "pdf-artifact"})
    assert payload["pdf"] == {"artifactId": "pdf-artifact"}


@pytest.mark.asyncio
async def test_bundled_pdf_plugin_publishes_a_scoped_artifact(tmp_path):
    source = pdf_bytes()
    (tmp_path / "sample.pdf").write_bytes(source)
    artifacts = ArtifactStore(tmp_path)
    runtime = PluginRuntime(workspace_root_for=lambda _: tmp_path, host_api=PluginHostApi(artifacts))
    manifest = load_plugin_manifest(PARSER.parent.parent / "plugin.json")
    try:
        result = await runtime.render_view("main", manifest, "document", {"path": "sample.pdf"})
        artifact_id = result["payload"]["pdf"]["artifactId"]
        artifact = artifacts.get(bot_alias="main", artifact_id=artifact_id)
        assert artifact.content_type == "application/pdf"
        assert artifact.path.read_bytes() == source
        with pytest.raises(KeyError):
            artifacts.get(bot_alias="other", artifact_id=artifact_id)
    finally:
        await runtime.shutdown()
