"""Launch the installed Harness CLI with per-invocation model selection."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from bot.platform.executables import build_executable_invocation
from bot.platform.processes import build_hidden_process_kwargs


_DSH_ENTRY_RE = re.compile(
    r"(?i)(?P<path>(?:%~dp0|%[A-Z_][A-Z0-9_]*%|[A-Za-z]:|\\\\|/)?"
    r"[^\"\r\n]*node_modules[\\/]+@deepseek-ai[\\/]+dsh[\\/]+lib[\\/]+bin\.js)"
)
_DSH_NODE_RE = re.compile(
    r"(?i)(?P<path>(?:%~dp0|%[A-Z_][A-Z0-9_]*%|[A-Za-z]:|\\\\|/)?"
    r"[^\"\r\n]*runtimes[\\/]+node-[^\\/\"\r\n]+[\\/]+node\.exe)"
)

_DEEPSEEK_CATALOG_TTL_SECONDS = 15.0
_DEEPSEEK_CATALOG_TIMEOUT_SECONDS = 8.0
_DEEPSEEK_CATALOG_MAX_BYTES = 512 * 1024
_DEEPSEEK_CATALOG_MAX_PROVIDERS = 128
_DEEPSEEK_CATALOG_MAX_MODELS = 256
_DEEPSEEK_FALLBACK_MODELS = ("deepseek-flash", "deepseek-v4-pro")
_deepseek_catalog_cache: dict[tuple[str, str, tuple[tuple[str, int, int], ...]], tuple[float, dict[str, Any]]] = {}
_deepseek_catalog_cache_lock = threading.Lock()


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


def _normalize_deepseek_selection(params: dict[str, Any]) -> dict[str, str]:
    selection: dict[str, str] = {}
    for source, target in (
        ("provider", "provider"),
        ("model", "model"),
        ("reasoning_effort", "reasoningEffort"),
    ):
        value = str(params.get(source) or "").strip()
        if value and value.casefold() != "none":
            selection[target] = value
    if selection.get("reasoningEffort") not in {None, "off", "low", "high", "max"}:
        raise ValueError("DeepSeek Harness 思考深度仅支持 off、low、high、max")
    return selection


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
    selection = _normalize_deepseek_selection(params)

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


def _deepseek_catalog_fingerprint(resolved_cli: str, working_dir: str | None) -> tuple[tuple[str, int, int], ...]:
    """Track launcher/profile inputs so catalog cache entries expire on edits."""
    candidates = [Path(resolved_cli)]
    dsh_home = str(os.environ.get("DSH_HOME") or "").strip()
    if dsh_home:
        home = Path(dsh_home).expanduser()
    else:
        home = Path.home() / ".dsh"
    for profile in ("headless", "desktop"):
        profile_dir = home / "profiles" / profile
        candidates.extend(profile_dir / name for name in ("package.json", "cordis.yml", "cordis.patch.yml"))
    candidates.append(home / "cordis.patch.yml")
    if working_dir:
        candidates.append(Path(working_dir))
    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
            stat = resolved.stat()
        except (OSError, ValueError):
            continue
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((key, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(result)


def _build_deepseek_catalog_command(resolved_cli: str) -> list[str] | None:
    """Build the read-only launcher command for an npm or Desktop dsh entry."""
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
        node = _resolve_desktop_node(executable)
        if not node:
            return None
        return [
            str(node), str(Path(__file__).with_name("deepseek_launch.mjs")),
            "--desktop", resolved_cli, "{}", "--describe-models",
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
        return None
    adjacent_node = executable.parent / ("node.exe" if os.name == "nt" else "node")
    node = str(shim_node or adjacent_node) if (shim_node or adjacent_node).is_file() else shutil.which("node")
    if not node:
        return None
    return [
        node, str(Path(__file__).with_name("deepseek_launch.mjs")), str(entry),
        "{}", "--describe-models",
    ]


def _fallback_deepseek_catalog(params: dict[str, Any] | None = None, diagnostic: str = "") -> dict[str, Any]:
    current = params or {}
    provider = str(current.get("provider") or "").strip()
    if provider.casefold() == "none":
        provider = ""
    model = str(current.get("model") or "").strip()
    if model.casefold() == "none":
        model = ""
    models = list(_DEEPSEEK_FALLBACK_MODELS)
    if model and model not in models:
        models.insert(0, model)
    provider_id = provider or ""
    provider_options = []
    model_options_by_provider: dict[str, list[dict[str, Any]]] = {}
    if provider_id:
        model_options_by_provider[provider_id] = [{"id": item, "label": item} for item in models]
        provider_options.append({"id": provider_id, "label": provider_id, "modelOptions": model_options_by_provider[provider_id]})
    return {
        "providers": provider_options,
        "selectedProvider": provider_id,
        "selectedModel": model,
        "modelOptions": models,
        "modelOptionsByProvider": model_options_by_provider,
        "reasoningEfforts": ["none", "off", "low", "high", "max"],
        "status": "fallback",
        "diagnostic": diagnostic[:512],
    }


def _catalog_from_payload(payload: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("DeepSeek catalog 响应不是 JSON 对象")
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list):
        raise ValueError("DeepSeek catalog 缺少 providers")

    def model_option(value: Any) -> dict[str, Any] | None:
        if isinstance(value, str):
            model_id = value.strip()
            return {"id": model_id, "label": model_id} if model_id else None
        if not isinstance(value, dict):
            return None
        model_id = str(value.get("id") or value.get("model") or "").strip()
        if not model_id:
            return None
        efforts = value.get("reasoningEfforts", value.get("reasoning_efforts"))
        if isinstance(efforts, (list, tuple)):
            efforts = [str(item).strip() for item in efforts if str(item).strip()]
        else:
            efforts = []
        default_effort = str(value.get("defaultReasoningEffort", value.get("default_reasoning_effort")) or "").strip()
        return {
            "id": model_id,
            "label": str(value.get("label") or value.get("name") or model_id).strip() or model_id,
            **({"reasoningEfforts": efforts} if efforts else {}),
            **({"defaultReasoningEffort": default_effort} if default_effort else {}),
        }

    providers: list[dict[str, Any]] = []
    for raw in raw_providers[:_DEEPSEEK_CATALOG_MAX_PROVIDERS]:
        if isinstance(raw, str):
            provider_id = raw.strip()
            raw = {"id": provider_id, "label": provider_id}
        if not isinstance(raw, dict):
            continue
        provider_id = str(raw.get("id") or raw.get("provider") or "").strip()
        if not provider_id:
            continue
        raw_models = raw.get("modelOptions", raw.get("model_options", raw.get("models")))
        models = []
        if isinstance(raw_models, (list, tuple)):
            for item in raw_models[:_DEEPSEEK_CATALOG_MAX_MODELS]:
                mapped = model_option(item)
                if mapped and mapped["id"] not in {model["id"] for model in models}:
                    models.append(mapped)
        raw_efforts = raw.get("reasoningEfforts", raw.get("reasoning_efforts"))
        efforts = [str(item).strip() for item in raw_efforts if str(item).strip()] if isinstance(raw_efforts, (list, tuple)) else []
        default_model = str(raw.get("defaultModel", raw.get("default_model")) or "").strip()
        default_effort = str(raw.get("defaultReasoningEffort", raw.get("default_reasoning_effort")) or "").strip()
        providers.append({
            "id": provider_id,
            "label": str(raw.get("label") or raw.get("name") or provider_id).strip() or provider_id,
            **({"defaultModel": default_model} if default_model else {}),
            **({"defaultReasoningEffort": default_effort} if default_effort else {}),
            **({"modelOptions": models} if models else {}),
            **({"reasoningEfforts": efforts} if efforts else {}),
        })
    model_map: dict[str, list[dict[str, Any]]] = {}
    raw_model_map = payload.get("modelOptionsByProvider", payload.get("model_options_by_provider"))
    if isinstance(raw_model_map, dict):
        for provider_id, values in raw_model_map.items():
            if not isinstance(values, (list, tuple)):
                continue
            mapped = [item for item in (model_option(value) for value in values[:_DEEPSEEK_CATALOG_MAX_MODELS]) if item]
            if mapped:
                model_map[str(provider_id).strip()] = mapped
    raw_models = payload.get("modelOptions", payload.get("model_options"))
    model_options = [item["id"] for item in (model_option(value) for value in raw_models[:_DEEPSEEK_CATALOG_MAX_MODELS]) if item] if isinstance(raw_models, (list, tuple)) else []
    raw_reasoning = payload.get("reasoningEfforts", payload.get("reasoning_efforts"))
    reasoning = [str(item).strip() for item in raw_reasoning if str(item).strip()] if isinstance(raw_reasoning, (list, tuple)) else []
    diagnostic = str(payload.get("diagnostic") or payload.get("catalogDiagnostic") or "").strip()
    diagnostic = re.sub(
        r"((?:api[_-]?key|token|secret|password|authorization|credential)[^\s:=]*)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        diagnostic,
        flags=re.IGNORECASE,
    )[:512]
    return {
        "providers": providers,
        "selectedProvider": str(payload.get("selectedProvider", payload.get("selected_provider")) or "").strip(),
        "selectedModel": str(payload.get("selectedModel", payload.get("selected_model")) or "").strip(),
        "modelOptions": model_options,
        "modelOptionsByProvider": model_map,
        "reasoningEfforts": reasoning,
        "status": str(payload.get("status") or "ready").strip() or "ready",
        "diagnostic": diagnostic,
    }


def discover_deepseek_catalog(
    resolved_cli: str,
    working_dir: str | None = None,
    params: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Discover a bounded, credential-free DeepSeek provider/model catalog."""
    fallback = _fallback_deepseek_catalog(params)
    command = _build_deepseek_catalog_command(resolved_cli)
    fingerprint = _deepseek_catalog_fingerprint(resolved_cli, working_dir)
    cache_key = (
        str(Path(resolved_cli).expanduser().resolve()).casefold(),
        str(Path(working_dir).expanduser().resolve()).casefold() if working_dir else "",
        fingerprint,
    )
    now = time.monotonic()
    if not force:
        with _deepseek_catalog_cache_lock:
            cached = _deepseek_catalog_cache.get(cache_key)
            if cached is not None and now - cached[0] < _DEEPSEEK_CATALOG_TTL_SECONDS:
                return dict(cached[1])
    if command is None:
        result = {**fallback, "status": "unavailable", "diagnostic": "当前 DeepSeek CLI 入口不支持只读 catalog"}
    else:
        try:
            completed = subprocess.run(
                command,
                cwd=working_dir or None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_DEEPSEEK_CATALOG_TIMEOUT_SECONDS,
                check=False,
                **build_hidden_process_kwargs(),
            )
            raw_stdout = completed.stdout or ""
            if len(raw_stdout.encode("utf-8", errors="replace")) > _DEEPSEEK_CATALOG_MAX_BYTES:
                raise ValueError("DeepSeek catalog 输出过大")
            lines = [line.strip() for line in raw_stdout.splitlines() if line.strip()]
            payload = json.loads(lines[-1]) if lines else None
            result = _catalog_from_payload(payload, params)
            if completed.returncode != 0 and result.get("status") == "ready":
                result["status"] = "fallback"
        except subprocess.TimeoutExpired:
            result = {**fallback, "status": "error", "diagnostic": "DeepSeek catalog 读取超时"}
        except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
            result = {**fallback, "status": "error", "diagnostic": str(exc)[:512]}
    with _deepseek_catalog_cache_lock:
        _deepseek_catalog_cache[cache_key] = (time.monotonic(), dict(result))
    return result
