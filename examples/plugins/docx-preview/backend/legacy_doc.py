from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


OLE_SIGNATURE = bytes.fromhex("D0 CF 11 E0 A1 B1 1A E1")
MAX_DOCX_BYTES = 32 * 1024 * 1024
# Leave time for parsing and Host API calls within the plugin's 60-second RPC.
CONVERSION_TIMEOUT = 40


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


def _run_writer(command: list[str]) -> None:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    try:
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, **options) as writer:
            try:
                status = writer.wait(timeout=CONVERSION_TIMEOUT)
            except subprocess.TimeoutExpired as exc:
                # soffice may launch a child. Stop only this private conversion.
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(writer.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
                    else:
                        os.killpg(writer.pid, signal.SIGKILL)
                finally:
                    writer.kill()
                raise RuntimeError("DOC 转换超时，请将文件另存为 .docx 后预览") from exc
    except OSError as exc:
        raise RuntimeError("无法运行 LibreOffice Writer，请将文件另存为 .docx 后预览") from exc
    if status:
        raise RuntimeError("DOC 转换失败，请确认文件可在 LibreOffice Writer 中打开")


def convert_doc(content: bytes, *, max_bytes: int = MAX_DOCX_BYTES) -> bytes:
    if not content.startswith(OLE_SIGNATURE):
        raise RuntimeError("无法识别 Word 97–2003 二进制 DOC 文件，请将文件另存为 .docx 后预览")
    executable = find_libreoffice()
    if not executable:
        raise RuntimeError("预览 .doc 需要在主机上安装 LibreOffice Writer，也可将文件另存为 .docx 后预览")
    with TemporaryDirectory(prefix="tcb-word-") as directory:
        work = Path(directory)
        source = work / "preview.doc"
        source.write_bytes(content)
        profile = work / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user/registrymodifications.xcu").write_text(
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
            '<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>'
            '<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        _run_writer([
            executable, f"-env:UserInstallation={profile.as_uri()}",
            "--headless", "--nologo", "--nodefault", "--norestore",
            "--infilter=MS Word 97", "--convert-to", "docx:Office Open XML Text",
            "--outdir", str(work), str(source),
        ])
        output = source.with_suffix(".docx")
        if not output.is_file():
            raise RuntimeError("未能转换 DOC，请确认文件未加密且可在 LibreOffice Writer 中打开")
        if output.stat().st_size > min(max_bytes, MAX_DOCX_BYTES):
            raise RuntimeError("转换后的 Word 文档超过预览大小限制")
        return output.read_bytes()
