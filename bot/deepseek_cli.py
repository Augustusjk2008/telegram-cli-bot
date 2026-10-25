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


def _is_desktop_shim(shim: str) -> bool:
    """Recognize the official Desktop wrapper without matching npm shims."""
    normalized = shim.replace("\\", "/").lower()
    return (
        "dsh-desktop-host" in normalized
        and "deepseek harness.exe" in normalized
        and "app.asar" in normalized
    )


def _resolve_desktop_node(executable: Path) -> Path | None:
    """Resolve the Node runtime shipped with an official Desktop install."""
    try:
        install_root = executable.parents[4]
    except IndexError:
        return None
    candidates = (
        install_root / "resources" / "runtime" / "primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
        install_root / "resources" / "runtime" / "node.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _desktop_patch_requires_cluster_mcp(params: dict[str, Any]) -> bool:
    extra_args = params.get("extra_args") or []
    if not isinstance(extra_args, (list, tuple)):
        return False
    index = 0
    while index < len(extra_args):
        arg = str(extra_args[index])
        if arg == "--patch":
            index += 1
            patch_path = str(extra_args[index]) if index < len(extra_args) else ""
        elif arg.startswith("--patch="):
            patch_path = arg.partition("=")[2]
        else:
            index += 1
            continue
        if patch_path:
            try:
                patch_text = Path(patch_path).read_text(encoding="utf-8")[:262_144]
            except (OSError, UnicodeError):
                patch_text = ""
            if "@deepseek-ai/dsh-mcp-client" in patch_text or "orbit-tcb-cluster-mcp" in patch_text:
                return True
        index += 1
    return False


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
        if value and value.casefold() != "none":
            selection[target] = value
    if selection.get("reasoningEffort") not in {None, "off", "low", "high", "max"}:
        raise ValueError("DeepSeek Harness 思考深度仅支持 off、low、high、max")

    executable = Path(resolved_cli)
    entry = executable.resolve()
    shim_node: Path | None = None
    desktop_wrapper = False
    if executable.suffix.lower() in {".cmd", ".ps1", ".bat"}:
        try:
            shim = executable.read_text(encoding="utf-8").replace("\\", "/")
        except (OSError, UnicodeError):
            shim = ""
        desktop_wrapper = _is_desktop_shim(shim)
        if not desktop_wrapper:
            resolved_entry = _resolve_dsh_entry_from_shim(executable, shim)
            if resolved_entry is not None:
                entry = resolved_entry
            shim_node = _resolve_dsh_node_from_shim(executable, shim)

    if desktop_wrapper:
        if not selection and not _desktop_patch_requires_cluster_mcp(params):
            return build_executable_invocation(resolved_cli)
        node = _resolve_desktop_node(executable)
        if not node:
            raise ValueError("DeepSeek Harness Desktop 启动失败：未找到 Desktop 内置 Node.js")
        return [
            str(node), str(Path(__file__).with_name("deepseek_launch.mjs")),
            "--desktop", resolved_cli, json.dumps(selection, ensure_ascii=False),
        ]
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
