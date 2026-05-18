from __future__ import annotations

import base64
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from bot.plugins.service import PluginService

PNG_1X1_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB"
    "gKgn2WQAAAAASUVORK5CYII="
)


def _write_pptx(path: Path, *, background_image: bool = False) -> None:
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldSz cx="9144000" cy="5143500"/>
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
  </p:sldIdLst>
</p:presentation>
"""
    presentation_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
"""
    bg_node = (
        '<p:bg><p:bgPr><a:blipFill><a:blip r:embed="rIdBg"/></a:blipFill></p:bgPr></p:bg>'
        if background_image
        else '<p:bg><p:bgPr><a:solidFill><a:srgbClr val="1F2937"/></a:solidFill></p:bgPr></p:bg>'
    )
    slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    {bg_node}
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="标题 1"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="685800" y="457200"/>
            <a:ext cx="6858000" cy="762000"/>
          </a:xfrm>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr b="1" sz="2400">
                <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
              </a:rPr>
              <a:t>项目路线图</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:pic>
        <p:nvPicPr>
          <p:cNvPr id="3" name="架构图" descr="系统架构图"/>
          <p:cNvPicPr/>
          <p:nvPr/>
        </p:nvPicPr>
        <p:blipFill>
          <a:blip r:embed="rIdImage"/>
          <a:stretch><a:fillRect/></a:stretch>
        </p:blipFill>
        <p:spPr>
          <a:xfrm>
            <a:off x="685800" y="1371600"/>
            <a:ext cx="1828800" cy="914400"/>
          </a:xfrm>
        </p:spPr>
      </p:pic>
      <p:graphicFrame>
        <p:nvGraphicFramePr>
          <p:cNvPr id="4" name="表格 1"/>
          <p:cNvGraphicFramePr/>
          <p:nvPr/>
        </p:nvGraphicFramePr>
        <p:xfrm>
          <a:off x="3200400" y="1371600"/>
          <a:ext cx="3657600" cy="1371600"/>
        </p:xfrm>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
            <a:tbl>
              <a:tblGrid>
                <a:gridCol w="1828800"/>
                <a:gridCol w="1828800"/>
              </a:tblGrid>
              <a:tr h="457200">
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>阶段</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>状态</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
              </a:tr>
              <a:tr h="457200">
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>MVP</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>开发中</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
              </a:tr>
            </a:tbl>
          </a:graphicData>
        </a:graphic>
      </p:graphicFrame>
    </p:spTree>
  </p:cSld>
</p:sld>
"""
    slide_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
  <Relationship Id="rIdBg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image2.png"/>
</Relationships>
"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    root_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>
"""

    path.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = base64.b64decode(PNG_1X1_BASE64)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("ppt/presentation.xml", presentation_xml)
        archive.writestr("ppt/_rels/presentation.xml.rels", presentation_rels_xml)
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels_xml)
        archive.writestr("ppt/media/image1.png", image_bytes)
        archive.writestr("ppt/media/image2.png", image_bytes)


@pytest.mark.asyncio
async def test_pptx_preview_plugin_renders_slides_images_background_and_tables(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/pptx-preview"), plugins_root / "pptx-preview")
    _write_pptx(repo_root / "docs" / "roadmap.pptx")

    service = PluginService(repo_root, plugins_root=plugins_root)

    target = service.resolve_file_target("docs/roadmap.pptx")
    assert target["kind"] == "plugin_view"
    assert target["pluginId"] == "pptx-preview"
    assert target["viewId"] == "document"

    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="pptx-preview",
        view_id="document",
        input_payload={"path": "docs/roadmap.pptx"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["renderer"] == "document"
    assert rendered["mode"] == "snapshot"
    slide = rendered["payload"]["blocks"][0]
    assert slide["type"] == "slide"
    assert slide["slideNumber"] == 1
    assert slide["background"]["color"] == "#1F2937"
    assert any(item["type"] == "text" for item in slide["items"])
    assert any(item["type"] == "image" for item in slide["items"])
    assert any(item["type"] == "table" for item in slide["items"])

    image_item = next(item for item in slide["items"] if item["type"] == "image")
    artifact = service.get_artifact(bot_alias="main", artifact_id=image_item["image"]["artifactId"])
    assert artifact.content_type == "image/png"
    assert artifact.path.read_bytes().startswith(b"\x89PNG")
    await service.shutdown()


@pytest.mark.asyncio
async def test_pptx_preview_plugin_renders_background_image(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/pptx-preview"), plugins_root / "pptx-preview")
    _write_pptx(repo_root / "docs" / "bg-image.pptx", background_image=True)

    service = PluginService(repo_root, plugins_root=plugins_root)
    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="pptx-preview",
        view_id="document",
        input_payload={"path": "docs/bg-image.pptx"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    slide = rendered["payload"]["blocks"][0]
    assert slide["background"]["image"]["contentType"] == "image/png"
    artifact = service.get_artifact(
        bot_alias="main",
        artifact_id=slide["background"]["image"]["artifactId"],
    )
    assert artifact.path.read_bytes().startswith(b"\x89PNG")
    await service.shutdown()


@pytest.mark.asyncio
async def test_pptx_preview_plugin_rejects_invalid_zip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/pptx-preview"), plugins_root / "pptx-preview")
    target = repo_root / "docs" / "broken.pptx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not a zip")

    service = PluginService(repo_root, plugins_root=plugins_root)
    with pytest.raises(RuntimeError, match="PPTX 文件损坏或格式不支持"):
        await service.render_view(
            bot_alias="main",
            plugin_id="pptx-preview",
            view_id="document",
            input_payload={"path": "docs/broken.pptx"},
            audit_context={"account_id": "u1", "bot_alias": "main"},
        )
    await service.shutdown()
