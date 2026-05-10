from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def read_manifest_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def merge_bundled_manifest(source_raw: dict[str, Any], installed_raw: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(source_raw)
    if "enabled" in installed_raw:
        merged["enabled"] = bool(installed_raw.get("enabled"))
    source_config = merged.get("config") if isinstance(merged.get("config"), dict) else {}
    installed_config = installed_raw.get("config") if isinstance(installed_raw.get("config"), dict) else {}
    if source_config or installed_config:
        merged["config"] = {**source_config, **installed_config}
    return merged


def iter_source_plugin_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        path
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and (path / "plugin.json").is_file()
    ]


def build_installable_plugin_payload(source_dir: Path, plugins_root: Path) -> dict[str, Any]:
    raw = read_manifest_json(source_dir / "plugin.json") or {}
    plugin_id = str(raw.get("id") or source_dir.name).strip() or source_dir.name
    return {
        "id": source_dir.name,
        "pluginId": plugin_id,
        "name": str(raw.get("name") or source_dir.name).strip() or source_dir.name,
        "version": str(raw.get("version") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "installed": (plugins_root / source_dir.name).exists(),
    }


def resolve_install_source_dir(
    source_plugins_root: Path,
    plugins_root: Path,
    install_id: str | None = None,
    *,
    source_path: str | Path | None = None,
) -> Path:
    if source_path is not None:
        candidate = Path(source_path).expanduser().resolve()
        manifest_path = candidate / "plugin.json"
        if not candidate.is_dir():
            raise FileNotFoundError(f"插件目录不存在: {candidate}")
        if not manifest_path.is_file():
            raise FileNotFoundError(f"目录缺少 plugin.json: {candidate}")
        return candidate

    normalized_install_id = str(install_id or "").strip()
    if not normalized_install_id:
        raise KeyError("未指定可安装插件")
    source_dir = next(
        (
            path
            for path in iter_source_plugin_dirs(source_plugins_root)
            if path.name == normalized_install_id
            or build_installable_plugin_payload(path, plugins_root)["pluginId"] == normalized_install_id
        ),
        None,
    )
    if source_dir is None:
        raise KeyError(f"未找到可安装插件: {normalized_install_id}")
    return source_dir


def sync_bundled_plugin_manifests(source_plugins_root: Path, plugins_root: Path) -> None:
    if not source_plugins_root.exists() or not plugins_root.exists():
        return
    for source_dir in iter_source_plugin_dirs(source_plugins_root):
        target_manifest_path = plugins_root / source_dir.name / "plugin.json"
        if not target_manifest_path.is_file():
            continue
        source_raw = read_manifest_json(source_dir / "plugin.json")
        installed_raw = read_manifest_json(target_manifest_path)
        if source_raw is None or installed_raw is None:
            continue
        merged = merge_bundled_manifest(source_raw, installed_raw)
        if merged == installed_raw:
            continue
        target_manifest_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
