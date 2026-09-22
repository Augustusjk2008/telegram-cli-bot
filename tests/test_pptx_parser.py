from __future__ import annotations

import importlib.util
import base64
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.registry import PluginRegistry
from bot.plugins.runtime import PluginRuntime


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/pptx-preview"
spec = importlib.util.spec_from_file_location("tested_pptx_parser", PLUGIN / "backend/pptx_parser.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def pptx_bytes(slides=3):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        ids = "".join(f'<p:sldId id="{256 + index}" r:id="s{index + 1}"/>' for index in range(slides))
        archive.writestr("ppt/presentation.xml", (
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx="9144000" cy="5143500"/></p:presentation>'
        ))
        rels = "".join(f'<Relationship Id="s{index + 1}" Target="slides/slide{index + 1}.xml"/>'
                       for index in range(slides))
        archive.writestr("ppt/_rels/presentation.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}</Relationships>'
        ))
        for index in range(slides):
            archive.writestr(f"ppt/slides/slide{index + 1}.xml", f'''<p:sld
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                show="{0 if index == 1 else 1}">
              <p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></p:bgPr></p:bg>
              <p:spTree><p:sp><p:spPr><a:xfrm><a:off x="304800" y="304800"/>
              <a:ext cx="6096000" cy="914400"/></a:xfrm></p:spPr>
              <p:txBody><a:p><a:r><a:rPr sz="2400"><a:solidFill><a:srgbClr val="123456"/></a:solidFill></a:rPr>
              <a:t>No Office required 中文 {index + 1}</a:t></a:r></a:p></p:txBody></p:sp>
              <p:pic><p:blipFill><a:blip r:embed="img"/></p:blipFill><p:spPr><a:xfrm>
              <a:off x="304800" y="1524000"/><a:ext cx="914400" cy="914400"/></a:xfrm></p:spPr></p:pic>
              </p:spTree></p:cSld></p:sld>''')
            archive.writestr(f"ppt/slides/_rels/slide{index + 1}.xml.rels", (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="img" Target="../media/pixel.png"/></Relationships>'
            ))
        archive.writestr("ppt/media/pixel.png", base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF2kAAAAASUVORK5CYII="))
    return buffer.getvalue()


def pdf_bytes(pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=960, height=540)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_static_preview_preserves_pdf_and_reports_slide_limit(monkeypatch):
    source = pptx_bytes()
    pdf = pdf_bytes()
    workdirs = []
    monkeypatch.setattr(module, "find_libreoffice", lambda _: "soffice")

    def convert(command):
        work = Path(command[-1]).parent
        workdirs.append(work)
        assert (work / "slides.pptx").read_bytes() == source
        options = json.loads(command[command.index("--convert-to") + 1].split(":", 2)[2])
        assert options["PageRange"]["value"] == "1-2"
        assert options["ExportHiddenSlides"]["value"] is True
        assert options["ExportNotesPages"]["value"] is False
        assert options["UseTransitionEffects"]["value"] is False
        assert f"-env:UserInstallation={(work / 'profile').as_uri()}" in command
        profile = ET.parse(work / "profile/user/registrymodifications.xcu")
        setting = profile.find(".//prop")
        assert setting.attrib["{http://openoffice.org/2001/registry}name"] == "DisableMacrosExecution"
        assert setting.findtext("value") == "true"
        (work / "slides.pdf").write_bytes(pdf)

    monkeypatch.setattr(module, "_run_converter", convert)
    write = Mock(return_value={"artifactId": "slides"})
    payload = module.parse_pptx_document("报告 & review.PPTX", source, write_artifact=write,
                                         limits={"max_slides": 2})
    write.assert_called_once_with("报告 & review.pdf", pdf, "application/pdf")
    assert payload["title"] == "报告 & review.PPTX"
    assert payload["pdf"] == {"artifactId": "slides"}
    assert payload["statsText"] == "仅预览前 2 页，共 3 页"
    assert payload["blocks"] == []
    assert not workdirs[0].exists()


@pytest.mark.parametrize(("content", "message"), [
    (b"not a zip", "文件损坏"), (pptx_bytes(0), "没有可预览"),
])
def test_invalid_decks_fail_before_starting_office(monkeypatch, content, message):
    converter = Mock()
    monkeypatch.setattr(module, "_run_converter", converter)
    write = Mock()
    with pytest.raises(RuntimeError, match=message):
        module.parse_pptx_document("bad.pptx", content, write_artifact=write)
    converter.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize(("output", "message"), [
    (None, "未生成预览"), (b"not a pdf", "预览无效"),
    (pdf_bytes(1), "页数不完整"), (pdf_bytes(0), "页数不完整"),
    (RuntimeError("转换超时"), "转换超时"),
])
def test_conversion_failures_clean_up_without_publishing(monkeypatch, output, message):
    workdirs = []
    monkeypatch.setattr(module, "find_libreoffice", lambda _: "soffice")

    def convert(command):
        work = Path(command[-1]).parent
        workdirs.append(work)
        if isinstance(output, Exception):
            raise output
        if output is not None:
            (work / "slides.pdf").write_bytes(output)

    monkeypatch.setattr(module, "_run_converter", convert)
    write = Mock()
    with pytest.raises(RuntimeError, match=message):
        module.parse_pptx_document("slides.pptx", pptx_bytes(2), write_artifact=write)
    assert not workdirs[0].exists()
    write.assert_not_called()


def test_oversized_preview_is_rejected_before_publication(monkeypatch):
    monkeypatch.setattr(module, "find_libreoffice", lambda _: "soffice")
    monkeypatch.setattr(module, "MAX_PDF_BYTES", 8)
    monkeypatch.setattr(module, "_run_converter", lambda command:
                        Path(command[-1]).with_suffix(".pdf").write_bytes(b"x" * 9))
    write = Mock()
    with pytest.raises(RuntimeError, match="超过 32 MiB"):
        module.parse_pptx_document("slides.pptx", pptx_bytes(), write_artifact=write)
    write.assert_not_called()


def test_converter_discovery_allows_missing_optional_dependency(monkeypatch, tmp_path):
    executable = tmp_path / "LibreOffice/program/soffice.com"
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert module.find_libreoffice(str(executable)) == str(executable.resolve())
    with pytest.raises(RuntimeError, match="路径无效"):
        module.find_libreoffice(str(tmp_path / "missing.exe"))
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert module.find_libreoffice() == str(executable)
    monkeypatch.setattr(module.Path, "is_file", lambda _: False)
    assert module.find_libreoffice() == ""


def test_missing_libreoffice_opens_slides_with_builtin_preview(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    monkeypatch.setattr(module, "find_libreoffice", lambda _: "")
    converter = Mock(side_effect=AssertionError("Office must not be started"))
    monkeypatch.setattr(module, "_run_converter", converter)
    write = Mock(return_value={"artifactId": "image"})
    payload = module.parse_pptx_document("slides.pptx", pptx_bytes(), write_artifact=write,
                                         limits={"max_slides": 2})
    assert "pdf" not in payload
    assert "基础静态预览" in payload["statsText"]
    slides = [block for block in payload["blocks"] if block["type"] == "slide"]
    assert [slide["slideNumber"] for slide in slides] == [1, 2]
    assert slides[1]["title"] == "No Office required 中文 2"
    assert (slides[0]["widthPx"], slides[0]["heightPx"]) == (960, 540)
    assert slides[0]["background"]["color"] == "#EEEEEE"
    assert slides[0]["items"][0]["paragraphs"][0]["runs"][0]["color"] == "#123456"
    assert slides[0]["items"][1]["image"]["artifactId"] == "image"
    assert "剩余 1 页" in payload["blocks"][-1]["runs"][0]["text"]
    assert all(call.args[2] == "image/png" for call in write.call_args_list)
    converter.assert_not_called()


def test_converter_timeout_terminates_only_owned_process_tree(monkeypatch):
    process = Mock(pid=12345)
    process.wait.side_effect = [subprocess.TimeoutExpired("soffice", 40), 0]
    popen = MagicMock()
    popen.return_value.__enter__.return_value = process
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    terminate_tree = Mock()
    if module.os.name == "nt":
        monkeypatch.setattr(module.subprocess, "run", terminate_tree)
    else:
        monkeypatch.setattr(module.os, "killpg", terminate_tree)
    with pytest.raises(RuntimeError, match="转换超时"):
        module._run_converter(["soffice", "--headless"])
    if module.os.name == "nt":
        assert terminate_tree.call_args.args[0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    else:
        terminate_tree.assert_called_once_with(12345, module.signal.SIGKILL)
    process.kill.assert_called_once()


def test_converter_process_success_and_failure():
    module._run_converter([sys.executable, "-c", "pass"])
    with pytest.raises(RuntimeError, match="转换 PPTX 失败"):
        module._run_converter([sys.executable, "-c", "raise SystemExit(1)"])


@pytest.mark.asyncio
@pytest.mark.parametrize("office_available", [False, True])
async def test_pptx_file_handler_and_stdio_artifact_contract(tmp_path, office_available):
    # Replace only the external Office boundary; exercise the real plugin process,
    # manifest config, workspace read and artifact host APIs.
    plugin_dir = tmp_path / "plugins/pptx-preview"
    shutil.copytree(PLUGIN, plugin_dir)
    parser = plugin_dir / "backend/pptx_parser.py"
    with parser.open("a", encoding="utf-8") as handle:
        handle.write(f'\nfind_libreoffice = lambda _: {"test-office" if office_available else ""!r}\n')
        if office_available:
            handle.write(f'_run_converter = lambda command: Path(command[-1]).with_suffix(".pdf").write_bytes({pdf_bytes()!r})\n')
        else:
            handle.write('def _run_converter(command):\n    raise AssertionError("Office must not be started")\n')
    manifest_path = plugin_dir / "plugin.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["config"]["maxSlides"] = 2
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    (tmp_path / "sample.PPTX").write_bytes(pptx_bytes())
    artifacts = ArtifactStore(tmp_path)
    runtime = PluginRuntime(workspace_root_for=lambda _: tmp_path, host_api=PluginHostApi(artifacts))
    manifest = load_plugin_manifest(manifest_path)
    try:
        registry = PluginRegistry(tmp_path / "plugins")
        resolution = registry.resolve_file_handler("sample.PPTX")
        assert resolution.plugin_id == "pptx-preview"
        result = await runtime.render_view("main", manifest, "document", {"path": "sample.PPTX"})
        assert result["renderer"] == "document"
        if office_available:
            assert result["payload"]["statsText"] == "仅预览前 2 页，共 3 页"
            artifact_id = result["payload"]["pdf"]["artifactId"]
        else:
            assert "pdf" not in result["payload"]
            assert result["payload"]["blocks"][1]["title"] == "No Office required 中文 2"
            artifact_id = result["payload"]["blocks"][0]["items"][1]["image"]["artifactId"]
        artifact = artifacts.get(bot_alias="main", artifact_id=artifact_id)
        assert artifact.content_type == ("application/pdf" if office_available else "image/png")
        if office_available:
            assert artifact.path.read_bytes() == pdf_bytes()
        else:
            assert artifact.path.read_bytes().startswith(b"\x89PNG")
        with pytest.raises(KeyError):
            artifacts.get(bot_alias="other", artifact_id=artifact_id)
    finally:
        await runtime.shutdown()
