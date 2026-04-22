from __future__ import annotations

from pathlib import Path
from typing import Any

from .audit import append_plugin_audit_event
from .paths import default_plugins_root
from .registry import PluginRegistry
from .runtime import PluginRuntime


class PluginService:
    def __init__(self, repo_root: Path | str, plugins_root: Path | str | None = None):
        self.repo_root = Path(repo_root)
        self.plugins_root = Path(plugins_root) if plugins_root is not None else default_plugins_root()
        self.registry = PluginRegistry(self.plugins_root)
        self.runtime = PluginRuntime()

    def list_plugins(self, refresh: bool = False) -> list[dict[str, Any]]:
        manifests = list(self.registry.discover().values()) if refresh else self.registry.list_manifests()
        return [
            {
                "id": manifest.plugin_id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "views": [
                    {
                        "id": view.id,
                        "title": view.title,
                        "renderer": view.renderer,
                    }
                    for view in manifest.views
                ],
                "fileHandlers": [
                    {
                        "id": handler.id,
                        "label": handler.label,
                        "extensions": list(handler.extensions),
                        "viewId": handler.view_id,
                    }
                    for handler in manifest.file_handlers
                ],
            }
            for manifest in manifests
        ]

    def resolve_file_target(self, path: str) -> dict[str, Any]:
        resolution = self.registry.resolve_file_handler(path)
        if resolution is None:
            return {"kind": "file"}
        return {
            "kind": "plugin_view",
            "pluginId": resolution.plugin_id,
            "viewId": resolution.view_id,
            "title": Path(str(path or "")).name or str(path or ""),
            "input": {"path": path},
        }

    async def render_view(
        self,
        *,
        plugin_id: str,
        view_id: str,
        input_payload: dict[str, Any],
        audit_context: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = self.registry.get_manifest(plugin_id)
        if not any(view.id == view_id for view in manifest.views):
            raise KeyError(f"未知插件视图: {plugin_id}/{view_id}")
        result = await self.runtime.render_view(manifest, view_id, input_payload)
        append_plugin_audit_event(
            self.repo_root,
            {
                "plugin_id": plugin_id,
                "view_id": view_id,
                "input": input_payload,
                "account_id": str(audit_context.get("account_id") or ""),
                "bot_alias": str(audit_context.get("bot_alias") or ""),
            },
        )
        return {
            "pluginId": plugin_id,
            "viewId": view_id,
            "title": str(result.get("title") or ""),
            "renderer": str(result.get("renderer") or ""),
            "payload": dict(result.get("payload") or {}),
        }

    async def shutdown(self) -> None:
        await self.runtime.shutdown()
