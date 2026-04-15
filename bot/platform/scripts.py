"""Platform-aware script discovery and execution helpers."""

from __future__ import annotations

import locale
import logging
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from bot.app_settings import build_git_proxy_env

from .output import strip_ansi_escape
from .runtime import get_runtime_platform

logger = logging.getLogger(__name__)
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT_EXEC_TIMEOUT = 60


def allowed_script_extensions() -> set[str]:
    if get_runtime_platform() == "windows":
        return {".bat", ".cmd", ".ps1", ".py", ".exe"}
    return {".sh", ".py"}


def build_script_command(script_path: Path) -> tuple[list[str] | str, bool]:
    ext = script_path.suffix.lower()
    if ext == ".exe":
        return [str(script_path)], False
    if ext == ".ps1":
        return [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ], False
    if ext == ".py":
        return ["python", str(script_path)], False
    if ext == ".sh":
        return ["bash", str(script_path)], False
    return str(script_path), True


def _decode_process_output(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data

    encodings = [
        locale.getpreferredencoding(False),
        "utf-8",
        "gb18030",
        "cp936",
    ]
    tried: set[str] = set()
    for encoding in encodings:
        normalized = (encoding or "").lower()
        if not normalized or normalized in tried:
            continue
        tried.add(normalized)
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    return data.decode("utf-8", errors="replace")


def get_script_display_name(script_path: Path) -> str:
    try:
        lines = script_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
    except OSError:
        return script_path.stem

    ext = script_path.suffix.lower()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        display_name = None
        if ext in {".bat", ".cmd"}:
            if line.startswith("::"):
                display_name = line[2:].strip()
            elif line.upper().startswith("REM "):
                display_name = line[4:].strip()
        elif ext in {".ps1", ".py", ".sh"} and line.startswith("#"):
            display_name = line[1:].strip()

        if display_name:
            return display_name

    return script_path.stem


def get_script_description(script_path: Path) -> str:
    try:
        lines = script_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:15]
    except OSError:
        return "无简介"

    descriptions: list[str] = []
    ext = script_path.suffix.lower()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        description = None
        if ext in {".bat", ".cmd"}:
            if line.startswith("::"):
                description = line[2:].strip()
            elif line.upper().startswith("REM "):
                description = line[4:].strip()
        elif ext in {".ps1", ".py", ".sh"}:
            if line.startswith("#"):
                description = line[1:].strip()
        else:
            for prefix in ("#", "//", "::", ";", "@REM", "REM"):
                if line.upper().startswith(prefix):
                    description = line[len(prefix):].strip()
                    break

        if description:
            descriptions.append(description)
        if len(descriptions) >= 3:
            break

    if descriptions:
        return " | ".join(descriptions[:3])
    return "无简介"


def list_available_scripts() -> list[tuple[str, str, str, Path]]:
    if not SCRIPTS_DIR.exists():
        return []

    scripts = []
    for item in SCRIPTS_DIR.iterdir():
        if item.is_file() and item.suffix.lower() in allowed_script_extensions():
            scripts.append((item.stem, get_script_display_name(item), get_script_description(item), item))

    scripts.sort(key=lambda row: row[0])
    return scripts


def _format_script_result(
    returncode: int,
    stdout_data: bytes | str | None = None,
    stderr_data: bytes | str | None = None,
    *,
    timed_out: bool = False,
) -> tuple[bool, str]:
    stdout = strip_ansi_escape(_decode_process_output(stdout_data)).strip()
    stderr = strip_ansi_escape(_decode_process_output(stderr_data)).strip()

    if timed_out:
        timeout_message = f"执行超时（超过{SCRIPT_EXEC_TIMEOUT}秒）"
        merged = stdout or stderr
        if merged:
            return False, f"{merged}\n\n{timeout_message}".strip()
        return False, timeout_message

    if returncode == 0:
        output = stdout or stderr
        return True, output if output else "执行成功（无输出）"

    error_message = stderr or stdout or f"退出码: {returncode}"
    return False, f"执行失败: {error_message}"


def _iter_log_lines(text: str) -> Iterator[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        cleaned = line.strip()
        if cleaned:
            yield cleaned


def _terminate_script_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def execute_script(script_path: Path) -> tuple[bool, str]:
    try:
        command, use_shell = build_script_command(script_path)
        result = subprocess.run(
            command,
            capture_output=True,
            text=False,
            timeout=SCRIPT_EXEC_TIMEOUT,
            shell=use_shell,
            env=build_git_proxy_env(),
        )
        return _format_script_result(result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired as exc:
        return _format_script_result(-1, exc.output, exc.stderr, timed_out=True)
    except Exception as exc:
        logger.debug("execute_script failed path=%s error=%s", script_path, exc)
        return False, f"执行异常: {str(exc)}"


def stream_execute_script(script_path: Path) -> Iterator[dict[str, object]]:
    process: subprocess.Popen | None = None
    collected_output: list[str] = []

    try:
        command, use_shell = build_script_command(script_path)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            shell=use_shell,
            env=build_git_proxy_env(),
        )
        started_at = time.monotonic()

        if process.stdout is not None:
            while True:
                if (time.monotonic() - started_at) >= SCRIPT_EXEC_TIMEOUT and process.poll() is None:
                    _terminate_script_process(process)
                    success, output = _format_script_result(
                        process.returncode if process.returncode is not None else -1,
                        "".join(collected_output),
                        timed_out=True,
                    )
                    yield {
                        "type": "done",
                        "script_name": script_path.stem,
                        "success": success,
                        "output": output,
                    }
                    return

                line = process.stdout.readline()
                if line:
                    decoded = strip_ansi_escape(_decode_process_output(line))
                    collected_output.append(decoded)
                    for log_line in _iter_log_lines(decoded):
                        yield {"type": "log", "text": log_line}
                    continue

                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        decoded = strip_ansi_escape(_decode_process_output(remaining))
                        collected_output.append(decoded)
                        for log_line in _iter_log_lines(decoded):
                            yield {"type": "log", "text": log_line}
                    break

                time.sleep(0.05)

        returncode = process.wait(timeout=2) if process is not None else -1
        success, output = _format_script_result(returncode, "".join(collected_output))
        yield {
            "type": "done",
            "script_name": script_path.stem,
            "success": success,
            "output": output,
        }
    except Exception as exc:
        yield {
            "type": "done",
            "script_name": script_path.stem,
            "success": False,
            "output": f"执行异常: {str(exc)}",
        }
    finally:
        if process is not None and process.stdout is not None:
            try:
                process.stdout.close()
            except Exception:
                pass
