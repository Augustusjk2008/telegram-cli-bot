import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from bot.plugins.service import PluginService


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/docx-preview"


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
async def test_word_session_retains_outline_and_original_path(tmp_path, monkeypatch, extension):
    docx = tmp_path / "sample.docx"
    write_docx(docx)
    path = docx.with_suffix(extension)
    if extension == ".DOC":
        path = tmp_path / "legacy.DOC"
        monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
        from legacy_doc import OLE_SIGNATURE, find_libreoffice

        writer = find_libreoffice()
        if not writer:
            pytest.skip("Requires LibreOffice Writer to generate and preview a Word 97–2003 file")
        subprocess.run([writer, f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}",
                        "--headless", "--convert-to", "doc:MS Word 97", "--outdir", str(tmp_path), str(docx)],
                       check=True, capture_output=True, timeout=40)
        docx.with_suffix(".doc").rename(path)
        assert path.read_bytes().startswith(OLE_SIGNATURE)

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


def test_doc_dependency_and_input_errors_are_actionable(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    import legacy_doc

    monkeypatch.setattr(legacy_doc, "find_libreoffice", lambda: None)
    with pytest.raises(RuntimeError, match="LibreOffice Writer.*另存为 .docx"):
        legacy_doc.convert_doc(legacy_doc.OLE_SIGNATURE)
    with pytest.raises(RuntimeError, match="Word 97–2003"):
        legacy_doc.convert_doc(b"plain text")


def test_converted_doc_size_limit_cleans_up_private_files(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    import legacy_doc

    outputs = []

    def write_output(command):
        output = Path(command[-1]).with_suffix(".docx")
        output.write_bytes(b"above the test limit")
        outputs.append(output)

    monkeypatch.setattr(legacy_doc, "find_libreoffice", lambda: "soffice")
    monkeypatch.setattr(legacy_doc, "_run_writer", write_output)
    with pytest.raises(RuntimeError, match="大小限制"):
        legacy_doc.convert_doc(legacy_doc.OLE_SIGNATURE, max_bytes=4)
    assert not outputs[0].parent.exists()
