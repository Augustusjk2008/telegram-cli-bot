from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Leave time for host reads and artifact publication within the 60-second RPC.
CONVERSION_TIMEOUT_SECONDS = 40
MAX_PDF_BYTES = 32 * 1024 * 1024


def find_libreoffice(configured_path: str = "") -> str:
    if configured_path.strip():
        candidate = Path(configured_path.strip()).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise RuntimeError("LibreOffice 路径无效，请在插件设置中填写 soffice 可执行文件的完整路径")
    for name in ("soffice.com", "soffice.exe") if os.name == "nt" else ("libreoffice", "soffice"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    candidates = [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")]
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "LibreOffice/program/soffice.com")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("PPTX 静态预览需要 LibreOffice（含 Impress）。请安装后重试，或在插件设置中填写 LibreOffice 路径")


def _slide_count(content: bytes) -> int:
    try:
        with ZipFile(BytesIO(content)) as archive:
            entry = archive.getinfo("ppt/presentation.xml")
            if entry.file_size > 4 * 1024 * 1024:
                raise RuntimeError("PPTX 演示文稿索引超过预览限额")
            root = ET.fromstring(archive.read(entry))
            count = len(root.findall("{*}sldIdLst/{*}sldId"))
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise RuntimeError("PPTX 文件损坏或格式不支持；加密文件请先解锁") from exc
    if not count:
        raise RuntimeError("PPTX 没有可预览的幻灯片")
    return count


def _run_converter(command: list[str]) -> None:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    try:
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, **options) as process:
            try:
                returncode = process.wait(timeout=CONVERSION_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                # Kill only this conversion's process tree, never an open Office session.
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                                       timeout=5, check=False)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                finally:
                    process.kill()
                    process.wait()
                raise RuntimeError("PPTX 转换超时，请减少幻灯片或压缩图片后重试") from exc
    except OSError as exc:
        raise RuntimeError("无法启动 LibreOffice，请检查插件设置中的可执行文件路径") from exc
    if returncode:
        raise RuntimeError("LibreOffice 转换 PPTX 失败，请确认文件可正常打开且已安装 Impress")


def parse_pptx_document(
    path: str,
    content: bytes,
    *,
    write_artifact: Callable[[str, bytes, str], dict[str, Any]],
    limits: dict[str, int] | None = None,
    libreoffice_path: str = "",
) -> dict[str, object]:
    total = _slide_count(content)
    max_slides = max(1, min(300, int((limits or {}).get("max_slides", 80))))
    count = min(total, max_slides)
    executable = find_libreoffice(libreoffice_path)
    with TemporaryDirectory(prefix="orbit-pptx-") as directory:
        work = Path(directory)
        source = work / "slides.pptx"
        source.write_bytes(content)
        # A private profile prevents forwarding the command to an existing Office
        # session and keeps concurrent conversions independent.
        profile = work / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user/registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        export = {
            "PageRange": {"type": "string", "value": f"1-{count}"},
            "ExportHiddenSlides": {"type": "boolean", "value": True},
            "ExportNotesPages": {"type": "boolean", "value": False},
            "UseTransitionEffects": {"type": "boolean", "value": False},
        }
        _run_converter([
            executable, f"-env:UserInstallation={profile.as_uri()}",
            "--headless", "--nologo", "--nodefault", "--norestore",
            "--convert-to", "pdf:impress_pdf_Export:" + json.dumps(export, separators=(",", ":")),
            "--outdir", str(work), str(source),
        ])
        output = work / "slides.pdf"
        if not output.is_file():
            raise RuntimeError("LibreOffice 未生成预览，请确认 PPTX 未加密且文件可正常打开")
        if output.stat().st_size > MAX_PDF_BYTES:
            raise RuntimeError("PPTX 预览超过 32 MiB，请减少预览页数或压缩图片")
        pdf = output.read_bytes()
        try:
            reader = PdfReader(BytesIO(pdf))
            if reader.is_encrypted or len(reader.pages) != count:
                raise RuntimeError("PPTX 转换后的页数不完整或预览已加密，请检查文件和 LibreOffice 版本")
        except PdfReadError as exc:
            raise RuntimeError("LibreOffice 生成的预览无效，请检查文件和 LibreOffice 版本") from exc
    artifact = write_artifact(Path(path).stem + ".pdf", pdf, "application/pdf")
    stats = f"{count} 页 · 静态预览" if count == total else f"仅预览前 {count} 页，共 {total} 页"
    return {
        "path": path,
        "title": Path(path).name,
        "statsText": stats,
        "pdf": {"artifactId": artifact["artifactId"]},
        "blocks": [],
    }
