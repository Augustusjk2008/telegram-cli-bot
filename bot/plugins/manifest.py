from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    PluginFileHandlerSpec,
    PluginManifest,
    PluginRuntimeSpec,
    PluginViewSpec,
)


def _expect_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象")
    return value


def _normalize_extension(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("插件扩展名不能为空")
    return text if text.startswith(".") else f".{text}"


def _normalize_choice(value: Any, label: str, allowed: set[str], default: str) -> str:
    text = str(value or "").strip() or default
    if text not in allowed:
        raise ValueError(f"{label} 仅支持: {', '.join(sorted(allowed))}")
    return text


def load_plugin_manifest(path: Path) -> PluginManifest:
    raw = _expect_mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    if int(raw.get("schemaVersion") or 0) != 1:
        raise ValueError(f"不支持的插件 schemaVersion: {raw.get('schemaVersion')}")

    runtime_raw = _expect_mapping(raw.get("runtime"), "runtime")
    views_raw = raw.get("views") or []
    handlers_raw = raw.get("fileHandlers") or []
    if not isinstance(views_raw, list):
        raise ValueError("views 必须是数组")
    if not isinstance(handlers_raw, list):
        raise ValueError("fileHandlers 必须是数组")

    views: list[PluginViewSpec] = []
    seen_view_ids: set[str] = set()
    for item in views_raw:
        current = _expect_mapping(item, "view")
        view_id = str(current.get("id") or "").strip()
        if not view_id:
            raise ValueError("view.id 不能为空")
        if view_id in seen_view_ids:
            raise ValueError(f"重复的 view.id: {view_id}")
        seen_view_ids.add(view_id)
        views.append(
            PluginViewSpec(
                id=view_id,
                title=str(current.get("title") or "").strip(),
                renderer=str(current.get("renderer") or "").strip(),
                view_mode=_normalize_choice(current.get("viewMode"), "view.viewMode", {"snapshot", "session"}, "snapshot"),
                data_profile=_normalize_choice(current.get("dataProfile"), "view.dataProfile", {"light", "heavy"}, "light"),
            )
        )

    file_handlers: list[PluginFileHandlerSpec] = []
    for item in handlers_raw:
        current = _expect_mapping(item, "fileHandler")
        view_id = str(current.get("viewId") or "").strip()
        if view_id not in seen_view_ids:
            raise ValueError(f"fileHandler.viewId 未定义: {view_id}")
        extensions_raw = current.get("extensions") or []
        if not isinstance(extensions_raw, list):
            raise ValueError("fileHandler.extensions 必须是数组")
        file_handlers.append(
            PluginFileHandlerSpec(
                id=str(current.get("id") or "").strip(),
                label=str(current.get("label") or "").strip(),
                extensions=tuple(_normalize_extension(value) for value in extensions_raw),
                view_id=view_id,
            )
        )

    return PluginManifest(
        root=path.parent.resolve(),
        plugin_id=str(raw.get("id") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        version=str(raw.get("version") or "").strip(),
        description=str(raw.get("description") or "").strip(),
        runtime=PluginRuntimeSpec(
            runtime_type=str(runtime_raw.get("type") or "").strip(),
            entry=str(runtime_raw.get("entry") or "").strip(),
            protocol=str(runtime_raw.get("protocol") or "").strip(),
        ),
        views=tuple(views),
        file_handlers=tuple(file_handlers),
    )
