from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bot.plugins.service import PluginService


def _build_pdf_with_lines(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 18 Tf", "72 760 Td"]
    for index, raw_line in enumerate(lines):
        escaped = raw_line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index:
            content_lines.append("0 -24 Td")
        content_lines.append(f"({escaped}) Tj")
    content_lines.append("ET")
    content_stream = "\n".join(content_lines).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content_stream), content_stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    parts = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets: list[int] = []
    current_offset = len(parts[0])
    for index, body in enumerate(objects, start=1):
        offsets.append(current_offset)
        chunk = f"{index} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
        parts.append(chunk)
        current_offset += len(chunk)

    xref_offset = current_offset
    xref_parts = [f"xref\n0 {len(objects) + 1}\n".encode("latin-1"), b"0000000000 65535 f \n"]
    for offset in offsets:
        xref_parts.append(f"{offset:010d} 00000 n \n".encode("latin-1"))
    trailer = f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin-1")
    return b"".join(parts + xref_parts + [trailer])


def _write_pdf(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_build_pdf_with_lines(lines))


def _join_block_text(block: dict[str, object]) -> str:
    return "".join(str(run.get("text") or "") for run in block.get("runs", []))


@pytest.mark.asyncio
async def test_pdf_preview_plugin_renders_text_layer_as_document(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/pdf-preview"), plugins_root / "pdf-preview")
    _write_pdf(
        repo_root / "docs" / "roadmap.pdf",
        [
            "Project Roadmap",
            "",
            "Current status: in progress.",
            "",
            "Deliver text PDF preview first.",
        ],
    )

    service = PluginService(repo_root, plugins_root=plugins_root)

    target = service.resolve_file_target("docs/roadmap.pdf")
    assert target["kind"] == "plugin_view"
    assert target["pluginId"] == "pdf-preview"
    assert target["viewId"] == "document"

    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="pdf-preview",
        view_id="document",
        input_payload={"path": "docs/roadmap.pdf"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["renderer"] == "document"
    assert rendered["mode"] == "snapshot"
    assert rendered["payload"]["title"] == "Project Roadmap"
    assert rendered["payload"]["blocks"][0]["type"] == "heading"
    assert any("Current status: in progress." in _join_block_text(block) for block in rendered["payload"]["blocks"])

    await service.shutdown()


@pytest.mark.asyncio
async def test_pdf_preview_plugin_returns_scan_hint_when_pdf_has_no_text_layer(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/pdf-preview"), plugins_root / "pdf-preview")
    _write_pdf(repo_root / "docs" / "scan.pdf", [])

    service = PluginService(repo_root, plugins_root=plugins_root)
    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="pdf-preview",
        view_id="document",
        input_payload={"path": "docs/scan.pdf"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["renderer"] == "document"
    assert rendered["payload"]["title"] == "scan.pdf"
    assert rendered["payload"]["blocks"][0]["type"] == "paragraph"
    assert "可能是扫描版 PDF" in _join_block_text(rendered["payload"]["blocks"][0])

    await service.shutdown()
