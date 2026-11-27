from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from bot.plugins.service import PluginService
from bot.web.api_common import AuthContext, WebApiError
from bot.web.plugin_api_service import open_plugin_view


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/docx-preview"
# Saved from write_docx() using Writer's "MS Word 97" filter.
WORD97 = Path(__file__).parent / "fixtures/word97-outline.doc"


def write_docx(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", """
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Override PartName="/word/document.xml"
                ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
              <Override PartName="/word/styles.xml"
                ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
            </Types>""")
        archive.writestr("_rels/.rels", """
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Target="word/document.xml"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>
            </Relationships>""")
        archive.writestr("word/_rels/document.xml.rels", """
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="styles" Target="styles.xml"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"/>
            </Relationships>""")
        archive.writestr("word/styles.xml", """
            <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
                <w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
              <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
                <w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
            </w:styles>""")
        archive.writestr("word/document.xml", """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
              <w:p><w:pPr><w:pStyle w:val="Heading1"/><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Overview</w:t></w:r></w:p>
              <w:p><w:pPr><w:pStyle w:val="Heading2"/><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>细节</w:t></w:r></w:p>
              <w:p><w:r><w:t>Section body</w:t></w:r></w:p>
            </w:body></w:document>""")


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [".docx", ".DOC"])
async def test_word_session_retains_outline_and_original_path(tmp_path, extension):
    path = tmp_path / f"sample{extension}"
    if extension == ".DOC":
        path.write_bytes(WORD97.read_bytes())
    else:
        write_docx(path)

    service = PluginService(tmp_path, tmp_path / "plugins", PLUGIN.parent)
    await service.install_plugin(PLUGIN.name)
    try:
        handler = service.registry.resolve_file_handler(path.name)
        assert handler.plugin_id == PLUGIN.name
        opened = await service.open_view(bot_alias="main", plugin_id=handler.plugin_id, view_id=handler.view_id,
                                         input_payload={"path": path.name}, audit_context={})
        assert Path(opened["summary"]["path"]).name == path.name
        sections = opened["summary"]["sections"]
        assert [(s["title"], s["headingLevel"]) for s in sections] == [("Overview", 1), ("细节", 2)]
        assert opened["initialWindow"]["sectionId"] == sections[0]["id"]
        path.unlink()  # The session serves later windows from its private copy.
        window = await service.get_view_window(bot_alias="main", plugin_id=handler.plugin_id,
                                               session_id=opened["sessionId"], request_payload={"sectionId": sections[1]["id"]},
                                               audit_context={})
        assert window["blocks"][-1]["runs"][0]["text"] == "Section body"
    finally:
        await service.shutdown()


@pytest.mark.parametrize("missing", [True, False], ids=["no-writer", "unusable-writer"])
def test_bundled_reader_opens_real_doc_without_writer(tmp_path, monkeypatch, missing):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    import legacy_doc
    from docx_parser import parse_docx_document

    writer = None if missing else str(tmp_path / "unavailable-soffice")
    monkeypatch.setattr(legacy_doc, "find_libreoffice", lambda: writer)
    document = parse_docx_document("sample.doc", legacy_doc.convert_doc(WORD97.read_bytes()))
    headings = [(b["level"], b["runs"][0]["text"]) for b in document["blocks"] if b["type"] == "heading"]
    assert headings == [(1, "Overview"), (2, "细节")]
    assert document["blocks"][-1]["runs"][0]["text"] == "Section body"


@pytest.mark.asyncio
async def test_incompatible_doc_only_fails_its_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(variable, raising=False)
    (tmp_path / "readable.doc").write_bytes(WORD97.read_bytes())
    (tmp_path / "broken.doc").write_bytes(WORD97.read_bytes()[:8])
    write_docx(tmp_path / "next.docx")
    service = PluginService(tmp_path, tmp_path / "plugins", PLUGIN.parent)
    await service.install_plugin(PLUGIN.name)
    manager = SimpleNamespace(plugin_service=service, main_profile=SimpleNamespace(alias="main", working_dir=str(tmp_path)))
    auth = AuthContext(user_id=1, token_used=True, capabilities={"run_plugins"})

    async def open_file(name):
        return await open_plugin_view(manager, "main", auth, PLUGIN.name, "document", {"path": name})

    try:
        opened = await open_file("readable.doc")
        with pytest.raises(WebApiError, match="格式不兼容或文件已损坏") as failure:
            await open_file("broken.doc")
        assert failure.value.code == "plugin_open_failed"
        # A native session only exists in its original plugin process.
        section = opened["summary"]["sections"][1]["id"]
        window = await service.get_view_window(bot_alias="main", plugin_id=PLUGIN.name, session_id=opened["sessionId"],
                                               request_payload={"sectionId": section}, audit_context={})
        assert window["blocks"][-1]["runs"][0]["text"] == "Section body"
        assert (await open_file("next.docx"))["title"] == "Overview"
    finally:
        await service.shutdown()


def test_non_word_input_has_actionable_error(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    import legacy_doc

    with pytest.raises(RuntimeError, match="Word 97–2003"):
        legacy_doc.convert_doc(b"plain text")


def test_converted_doc_size_limit_cleans_up_private_files(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    import legacy_doc

    outputs = []

    def write_output(command, deadline):
        output = Path(command[-1]).with_suffix(".docx")
        output.write_bytes(b"above the test limit")
        outputs.append(output)
        return 0

    monkeypatch.setattr(legacy_doc, "find_libreoffice", lambda: "soffice")
    monkeypatch.setattr(legacy_doc, "_run_converter", write_output)
    with pytest.raises(RuntimeError, match="大小限制"):
        legacy_doc.convert_doc(legacy_doc.OLE_SIGNATURE, max_bytes=4)
    assert not outputs[0].parent.exists()
