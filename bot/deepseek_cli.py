"""Resolve and launch the Desktop DeepSeek Harness CLI.

The Desktop distribution owns the Electron runtime and the bundled dsh
package. Keeping the wrapper parsing here means that a PATH entry such as
``dsh`` still works while npm shims and the graphical executable fail early
with an actionable message.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

_DESKTOP_HOST_MARKER_RE = re.compile(
    r"(?i)app\.asar[\\/]+dsh[\\/]+node_modules[\\/]+@deepseek-ai[\\/]+"
    r"dsh-desktop-host[\\/]+lib[\\/]+cli\.js"
)
_NPM_DSH_MARKER_RE = re.compile(
    r"(?i)node_modules[\\/]+@deepseek-ai[\\/]+dsh[\\/]+lib[\\/]+bin\.js"
)
_CMD_TOKEN_RE = re.compile(r'"(?P<quoted>[^"]+)"|(?P<bare>[^\s]+)')

DESKTOP_DSH_ERROR = "DeepSeek Harness 必须使用桌面版 dsh.cmd，不能使用 npm CLI"
DESKTOP_DSH_GUI_ERROR = (
    "DeepSeek Harness 必须使用桌面版 dsh.cmd（resources\\runtime\\cli\\bin\\dsh.cmd），"
    "不要填写 DeepSeek Harness.exe"
)


@dataclass(frozen=True)
class DesktopDshRuntime:
    """Paths carried by a Desktop ``dsh.cmd`` wrapper."""

    wrapper: Path
    electron: Path
    host_entry: Path
    dsh_entry: Path


def _expand_cmd_path(raw_path: str, executable: Path) -> Path:
    """Expand the small CMD path language used by the Desktop wrapper."""

    expanded = str(raw_path).strip().strip('"').strip("'")
    expanded = re.sub(
        r"(?i)%~dp0",
        lambda _match: str(executable.parent) + os.sep,
        expanded,
    )
    # os.path.expandvars handles this on Windows; the explicit pass also
    # covers tests that exercise a Windows wrapper from a POSIX host.
    expanded = os.path.expandvars(expanded)
    for key, value in os.environ.items():
        expanded = re.sub(
            rf"%{re.escape(key)}%",
            lambda _match, replacement=str(value): replacement,
            expanded,
            flags=re.IGNORECASE,
        )
    if os.name != "nt":
        expanded = expanded.replace("\\", os.sep)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = executable.parent / candidate
    return candidate.resolve(strict=False)


def _cmd_path_tokens(shim: str) -> Iterable[str]:
    """Yield quoted or simple command tokens, ignoring ``set`` directives."""

    for line in str(shim or "").splitlines():
        stripped = line.strip()
        lowered = stripped.casefold()
        if not stripped or lowered.startswith(("set ", "set\t", "rem ", "::")):
            continue
        for match in _CMD_TOKEN_RE.finditer(line):
            token = match.group("quoted") or match.group("bare")
            if token:
                yield token


def _resolve_desktop_dsh_runtime(executable: Path, shim: str) -> DesktopDshRuntime | None:
    """Parse a Desktop ``dsh.cmd`` and return its bundled runtime paths.

    The parser intentionally uses paths written in the wrapper instead of a
    fixed installation directory. ``app.asar`` paths are virtual and are
    therefore not required to exist as ordinary files on disk.
    """

    host_path: Path | None = None
    electron_path: Path | None = None
    for token in _cmd_path_tokens(shim):
        normalized = token.replace("\\", "/")
        lowered = normalized.casefold()
        if _DESKTOP_HOST_MARKER_RE.search(normalized):
            host_path = _expand_cmd_path(token, executable)
            continue
        if lowered.endswith(".exe") and electron_path is None:
            electron_path = _expand_cmd_path(token, executable)

    if host_path is None or electron_path is None:
        return None

    try:
        # host: .../app.asar/dsh/node_modules/@deepseek-ai/
        #             dsh-desktop-host/lib/cli.js
        dsh_root = host_path.parents[4]
    except IndexError:
        return None
    if dsh_root.name.casefold() != "dsh":
        return None

    return DesktopDshRuntime(
        wrapper=executable.resolve(strict=False),
        electron=electron_path,
        host_entry=host_path,
        dsh_entry=dsh_root / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js",
    )


def _read_cmd_wrapper(executable: Path) -> str:
    try:
        return executable.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _is_gui_executable(executable: Path) -> bool:
    return executable.name.casefold() == "deepseek harness.exe"


def _is_npm_shim(executable: Path, shim: str) -> bool:
    if _NPM_DSH_MARKER_RE.search(shim):
        return True
    normalized = str(executable).replace("\\", "/").casefold()
    return "node_modules/@deepseek-ai/dsh/" in normalized


def _desktop_invocation(runtime: DesktopDshRuntime, selection: dict[str, str]) -> list[str]:
    launcher = Path(__file__).with_name("deepseek_launch.mjs")
    # Electron's Node mode accepts Node flags before the external launcher.
    return [
        str(runtime.electron),
        "--expose-internals",
        str(launcher),
        "desktop",
        str(runtime.electron),
        str(runtime.dsh_entry),
        str(runtime.host_entry),
        json.dumps(selection, ensure_ascii=False),
    ]


def build_deepseek_invocation(resolved_cli: str, params: dict[str, Any]) -> list[str]:
    """Build the Desktop Electron command for one DeepSeek invocation."""

    selection: dict[str, str] = {}
    for source, target in (("model", "model"), ("reasoning_effort", "reasoningEffort")):
        value = str(params.get(source) or "").strip()
        if value and value != "none":
            selection[target] = value
    if selection.get("reasoningEffort") not in {None, "off", "low", "high", "max"}:
        raise ValueError("DeepSeek Harness 思考深度仅支持 off、low、high、max")

    executable = Path(str(resolved_cli)).expanduser()
    if _is_gui_executable(executable):
        raise ValueError(DESKTOP_DSH_GUI_ERROR)

    shim = _read_cmd_wrapper(executable) if executable.suffix.casefold() in {".cmd", ".bat", ".ps1"} else ""
    if _is_npm_shim(executable, shim):
        raise ValueError(DESKTOP_DSH_ERROR)

    runtime = _resolve_desktop_dsh_runtime(executable, shim)
    if runtime is None:
        raise ValueError(DESKTOP_DSH_ERROR)
    if not runtime.electron.is_file():
        raise ValueError(f"{DESKTOP_DSH_ERROR}：未找到桌面版 Electron")
    return _desktop_invocation(runtime, selection)


def is_desktop_dsh_invocation(command: list[str]) -> bool:
    """Return whether a command was built for the Desktop Electron launcher."""

    return any(Path(str(item)).name.casefold() == "deepseek_launch.mjs" for item in command)
