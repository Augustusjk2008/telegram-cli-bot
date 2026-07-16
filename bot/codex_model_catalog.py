"""Account-aware Codex CLI model catalog discovery."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from bot.cli import resolve_cli_executable
from bot.cli_params import MODEL_OPTION_NONE, get_params_schema, normalize_cli_model_options
from bot.platform.executables import build_executable_invocation

logger = logging.getLogger(__name__)

CODEX_MODEL_CATALOG_TTL_SECONDS = 5 * 60
CODEX_MODEL_CATALOG_TIMEOUT_SECONDS = 8.0
CODEX_MODEL_CATALOG_MAX_ENTRIES = 16
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}


def clear_codex_model_catalog_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _fallback_items(configured_options: Iterable[str]) -> list[dict[str, Any]]:
    efforts = list(get_params_schema("codex")["reasoning_effort"].get("enum") or [])
    return [
        {
            "id": model_id,
            "label": "自动（Codex 默认）" if model_id == MODEL_OPTION_NONE else model_id,
            "reasoning_efforts": list(efforts),
            "default_reasoning_effort": "",
        }
        for model_id in normalize_cli_model_options(list(configured_options))
    ]


def _parse_catalog(stdout: str) -> list[dict[str, Any]]:
    payload = json.loads(stdout)
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in models:
        if not isinstance(raw, dict) or str(raw.get("visibility") or "list") != "list":
            continue
        model_id = str(raw.get("slug") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        efforts: list[str] = []
        for effort_item in raw.get("supported_reasoning_levels") or []:
            effort = str(effort_item.get("effort") if isinstance(effort_item, dict) else effort_item).strip()
            if effort and effort not in efforts:
                efforts.append(effort)
        default_effort = str(raw.get("default_reasoning_level") or "").strip()
        items.append(
            {
                "id": model_id,
                "label": str(raw.get("display_name") or model_id).strip() or model_id,
                "reasoning_efforts": efforts,
                "default_reasoning_effort": default_effort if default_effort in efforts else "",
            }
        )
    return items


def get_codex_model_catalog(
    cli_path: str,
    working_dir: str | Path | None,
    *,
    configured_options: Iterable[str] = (),
) -> dict[str, Any]:
    """Return the visible catalog for the currently authenticated Codex CLI.

    The live catalog is authoritative when available. Static configuration is
    retained as an offline/older-CLI fallback so an unavailable discovery
    command never removes the existing selector.
    """
    cwd = str(working_dir or Path.cwd())
    resolved = resolve_cli_executable(str(cli_path or "codex"), cwd)
    if not resolved:
        return {
            "source": "config",
            "items": _fallback_items(configured_options),
            "error": "未找到 Codex CLI",
        }

    cache_key = str(Path(resolved).resolve())
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = dict(_CACHE.get(cache_key) or {})
    if cached and now - float(cached.get("cached_at") or 0.0) <= CODEX_MODEL_CATALOG_TTL_SECONDS:
        return {key: value for key, value in cached.items() if key != "cached_at"}

    try:
        completed = subprocess.run(
            [*build_executable_invocation(resolved), "debug", "models"],
            cwd=cwd if Path(cwd).is_dir() else None,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CODEX_MODEL_CATALOG_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or f"退出码 {completed.returncode}").strip())
        items = _parse_catalog(completed.stdout or "")
        if not items:
            raise RuntimeError("Codex CLI 返回了空模型目录")
        items.append(
            {
                "id": MODEL_OPTION_NONE,
                "label": "自动（Codex 默认）",
                "reasoning_efforts": list(get_params_schema("codex")["reasoning_effort"].get("enum") or []),
                "default_reasoning_effort": "",
            }
        )
        result = {"source": "codex_cli", "items": items, "error": ""}
    except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as exc:
        logger.info("读取 Codex 模型目录失败，回退到静态配置: %s", exc)
        result = {
            "source": "config",
            "items": _fallback_items(configured_options),
            "error": str(exc),
        }

    with _CACHE_LOCK:
        _CACHE.pop(cache_key, None)
        _CACHE[cache_key] = {**result, "cached_at": now}
        while len(_CACHE) > CODEX_MODEL_CATALOG_MAX_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)), None)
    return result


def find_catalog_model(catalog: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    normalized = str(model_id or "").strip()
    for item in catalog.get("items") or []:
        if isinstance(item, dict) and str(item.get("id") or "").strip() == normalized:
            return item
    return None


__all__ = [
    "clear_codex_model_catalog_cache",
    "find_catalog_model",
    "get_codex_model_catalog",
]
