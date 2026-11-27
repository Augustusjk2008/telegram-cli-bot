from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


OLE_SIGNATURE = bytes.fromhex("D0 CF 11 E0 A1 B1 1A E1")
MAX_DOCX_BYTES = 32 * 1024 * 1024
# Leave time for parsing and Host API calls within the plugin's 60-second RPC.
CONVERSION_TIMEOUT = 40
CONVERTER_WHEEL = Path(__file__).resolve().parent / "vendor/msdoc2docx-0.36.6-py3-none-any.whl"
ENCRYPTED_DOCUMENT = 3
CONVERTER_UNAVAILABLE = 4


def find_libreoffice() -> str | None:
    names = ("soffice.com", "soffice.exe") if os.name == "nt" else ("libreoffice", "soffice")
    for name in names:
        executable = shutil.which(name)
        if executable:
            return executable
    candidates = [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")]
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.extend(Path(root) / "LibreOffice/program" / name for name in names)
    return next((str(path) for path in candidates if path.is_file()), None)


def _run_converter(command: list[str], deadline: float) -> int:
    timeout = deadline - time.monotonic()
    timeout_message = "DOC 转换超时，请将文件另存为 .docx 后预览"
    if timeout <= 0:
        raise RuntimeError(timeout_message)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, **options) as process:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # soffice may launch a child. Stop only this private conversion.
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                process.kill()
            raise RuntimeError(timeout_message) from exc


def _try_writer(executable: str, source: Path, deadline: float) -> bool:
    profile = source.parent / "profile"
    (profile / "user").mkdir(parents=True)
    (profile / "user/registrymodifications.xcu").write_text(
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
        '<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>'
        '<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>'
        '</item></oor:items>', encoding="utf-8",
    )
    try:
        status = _run_converter([
            executable, f"-env:UserInstallation={profile.as_uri()}",
            "--headless", "--nologo", "--nodefault", "--norestore",
            "--infilter=MS Word 97", "--convert-to", "docx:Office Open XML Text",
            "--outdir", str(source.parent), str(source),
        ], deadline)
    except OSError:
        return False
    return status == 0 and source.with_suffix(".docx").is_file()


def _bundled_worker(source: Path) -> int:
    # Only this isolated child imports the bundled, pure-Python wheel.
    if not CONVERTER_WHEEL.is_file():
        return CONVERTER_UNAVAILABLE
    sys.path.insert(0, str(CONVERTER_WHEEL))
    try:
        from doc2docx import convert
        from doc2docx.cfb import CompoundFileLimits
        from doc2docx.errors import Doc2DocxError, EncryptedDocumentError
    except ImportError:
        return CONVERTER_UNAVAILABLE
    try:
        convert(source, limits=CompoundFileLimits(max_input_bytes=MAX_DOCX_BYTES, max_stream_bytes=MAX_DOCX_BYTES))
    except EncryptedDocumentError:
        return ENCRYPTED_DOCUMENT
    except Doc2DocxError:
        return 1
    return 0


def convert_doc(content: bytes, *, max_bytes: int = MAX_DOCX_BYTES) -> bytes:
    if not content.startswith(OLE_SIGNATURE):
        raise RuntimeError("无法识别 Word 97–2003 二进制 DOC 文件，请将文件另存为 .docx 后预览")
    with TemporaryDirectory(prefix="tcb-word-") as directory:
        source = Path(directory) / "preview.doc"
        source.write_bytes(content)
        output = source.with_suffix(".docx")
        deadline = time.monotonic() + CONVERSION_TIMEOUT
        writer = find_libreoffice()
        if not writer or not _try_writer(writer, source, deadline):
            output.unlink(missing_ok=True)
            try:
                status = _run_converter([sys.executable, "-I", "-S", str(Path(__file__).resolve()), str(source)], deadline)
            except OSError as exc:
                raise RuntimeError("无法启动内置 DOC 转换器，请重新安装 DOCX Preview 或将文件另存为 .docx") from exc
            if status == CONVERTER_UNAVAILABLE:
                raise RuntimeError("内置 DOC 转换器不可用，请重新安装 DOCX Preview 或将文件另存为 .docx")
            if status == ENCRYPTED_DOCUMENT:
                raise RuntimeError("此 DOC 文件已加密，请解密后再预览")
            if status or not output.is_file():
                raise RuntimeError("无法预览此 DOC 文件，格式不兼容或文件已损坏。请将文件另存为 .docx 后重试")
        if output.stat().st_size > min(max_bytes, MAX_DOCX_BYTES):
            raise RuntimeError("转换后的 Word 文档超过预览大小限制")
        return output.read_bytes()


if __name__ == "__main__":
    sys.exit(_bundled_worker(Path(sys.argv[1])))
