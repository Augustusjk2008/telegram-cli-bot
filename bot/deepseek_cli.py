"""Launch the installed Harness CLI with per-invocation model selection."""

import json
import os
from pathlib import Path
import shutil
from typing import Any

from bot.platform.executables import build_executable_invocation


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
    if executable.suffix.lower() in {".cmd", ".ps1", ".bat"}:
        try:
            shim = executable.read_text(encoding="utf-8").replace("\\", "/")
        except (OSError, UnicodeError):
            shim = ""
        if "node_modules/@deepseek-ai/dsh/lib/bin.js" in shim:
            entry = executable.parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    try:
        manifest = json.loads((entry.parent.parent / "package.json").read_text(encoding="utf-8"))
        is_npm_cli = entry.name == "bin.js" and manifest.get("name") == "@deepseek-ai/dsh"
    except (OSError, ValueError):
        is_npm_cli = False

    if not is_npm_cli:
        if selection:
            raise ValueError("DeepSeek Harness 模型选择需要 npm 安装的 dsh，请将 CLI 路径指向 dsh 命令")
        return build_executable_invocation(resolved_cli)

    adjacent_node = executable.parent / ("node.exe" if os.name == "nt" else "node")
    node = str(adjacent_node) if adjacent_node.is_file() else shutil.which("node")
    if not node:
        raise ValueError("DeepSeek Harness 启动失败：未找到 Node.js")
    return [
        node, str(Path(__file__).with_name("deepseek_launch.mjs")), str(entry),
        json.dumps(selection, ensure_ascii=False),
    ]
