from __future__ import annotations

from pathlib import Path

from .manifest import load_plugin_manifest
from .models import PluginFileResolution, PluginManifest


class PluginRegistry:
    def __init__(self, plugins_root: Path | str):
        self.plugins_root = Path(plugins_root)
        self._manifests: dict[str, PluginManifest] = {}
        self._loaded = False

    def discover(self) -> dict[str, PluginManifest]:
        manifests: dict[str, PluginManifest] = {}
        if self.plugins_root.exists():
            for manifest_path in sorted(self.plugins_root.glob("*/plugin.json")):
                manifest = load_plugin_manifest(manifest_path)
                if not manifest.plugin_id:
                    raise ValueError(f"插件 id 不能为空: {manifest_path}")
                if manifest.plugin_id in manifests:
                    raise ValueError(f"duplicated plugin id: {manifest.plugin_id}")
                manifests[manifest.plugin_id] = manifest
        self._manifests = manifests
        self._loaded = True
        return dict(self._manifests)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.discover()

    def list_manifests(self) -> list[PluginManifest]:
        self._ensure_loaded()
        return list(self._manifests.values())

    def get_manifest(self, plugin_id: str) -> PluginManifest:
        self._ensure_loaded()
        return self._manifests[plugin_id]

    def resolve_file_handler(self, path: str) -> PluginFileResolution | None:
        candidate = str(path or "").strip().lower()
        if not candidate:
            return None
        for manifest in self.list_manifests():
            if not manifest.enabled:
                continue
            for handler in manifest.file_handlers:
                if any(candidate.endswith(extension) for extension in handler.extensions):
                    return PluginFileResolution(
                        plugin_id=manifest.plugin_id,
                        view_id=handler.view_id,
                        handler_id=handler.id,
                    )
        return None
