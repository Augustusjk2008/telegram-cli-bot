"""Launch the installed Harness CLI with per-invocation model selection."""

import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from bot.platform.executables import build_executable_invocation


_DSH_ENTRY_RE = re.compile(
    r"(?i)(?P<path>(?:%~dp0|%[A-Z_][A-Z0-9_]*%|[A-Za-z]:|\\\\|/)?"
    r"[^\"\r\n]*node_modules[\\/]+@deepseek-ai[\\/]+dsh[\\/]+lib[\\/]+bin\.js)"
)
_DSH_NODE_RE = re.compile(
    r"(?i)(?P<path>(?:%~dp0|%[A-Z_][A-Z0-9_]*%|[A-Za-z]:|\\\\|/)?"
    r"[^\"\r\n]*runtimes[\\/]+node-[^\\/\"\r\n]+[\\/]+node\.exe)"
)


def _resolve_dsh_entry_from_shim(executable: Path, shim: str) -> Path | None:
    candidates: list[Path] = []
    for match in _DSH_ENTRY_RE.finditer(shim):
        raw_path = match.group("path")
        expanded = raw_path.replace("%~dp0", str(executable.parent) + os.sep)
        expanded = os.path.expandvars(expanded)
        for key, value in os.environ.items():
            expanded = expanded.replace(f"%{key}%", value)
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = executable.parent / candidate
        candidates.append(candidate)

    candidates.extend(
        [
            executable.parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js",
            executable.parent.parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js",
        ]
    )
    appdata = str(os.environ.get("APPDATA") or "").strip()
    if appdata:
        candidates.append(
            Path(appdata) / "npm" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
        )

    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved
    return None


def _resolve_dsh_node_from_shim(executable: Path, shim: str) -> Path | None:
    for match in _DSH_NODE_RE.finditer(shim):
        raw_path = match.group("path")
        expanded = raw_path.replace("%~dp0", str(executable.parent) + os.sep)
        expanded = os.path.expandvars(expanded)
        for key, value in os.environ.items():
            expanded = expanded.replace(f"%{key}%", value)
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = executable.parent / candidate
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def build_deepseek_invocation(resolved_cli: str, params: dict[str, Any]) -> list[str]:
    selection = {}
    for source, target in (("model", "model"), ("reasoning_effort", "reasoningEffort")):
        value = str(params.get(source) or "").strip()
        if value and value != "none":
            selection[target] = value
    if selection.get("reasoningEffort") not in {None, "off", "low", "high", "max"}:
        raise ValueError("DeepSeek Harness 思考深度仅支持 off、low、high、max")

    executable = Path(resolved_cli)
    entry = executable.resolve()
    shim_node: Path | None = None
    if executable.suffix.lower() in {".cmd", ".ps1", ".bat"}:
        try:
            shim = executable.read_text(encoding="utf-8").replace("\\", "/")
        except (OSError, UnicodeError):
            shim = ""
        resolved_entry = _resolve_dsh_entry_from_shim(executable, shim)
        if resolved_entry is not None:
            entry = resolved_entry
        shim_node = _resolve_dsh_node_from_shim(executable, shim)
    try:
        manifest = json.loads((entry.parent.parent / "package.json").read_text(encoding="utf-8"))
        is_npm_cli = (
            entry.name == "bin.js"
            and isinstance(manifest, dict)
            and manifest.get("name") == "@deepseek-ai/dsh"
        )
    except (OSError, ValueError):
        is_npm_cli = False

    if not is_npm_cli:
        if selection:
            raise ValueError("DeepSeek Harness 模型选择需要 npm 安装的 dsh，请将 CLI 路径指向 dsh 命令")
        return build_executable_invocation(resolved_cli)

    adjacent_node = executable.parent / ("node.exe" if os.name == "nt" else "node")
    node = str(shim_node or adjacent_node) if (shim_node or adjacent_node).is_file() else shutil.which("node")
    if not node:
        raise ValueError("DeepSeek Harness 启动失败：未找到 Node.js")
    return [
        node, str(Path(__file__).with_name("deepseek_launch.mjs")), str(entry),
        json.dumps(selection, ensure_ascii=False),
    ]
