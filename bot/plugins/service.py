from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .audit import append_plugin_audit_event
from .paths import default_plugins_root
from .registry import PluginRegistry
from .runtime import PluginRuntime
from .view_sessions import (
    PluginViewSessionRecord,
    PluginViewSessionStore,
    build_source_fingerprint,
    build_source_identity,
)


def _payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class PluginService:
    def __init__(self, repo_root: Path | str, plugins_root: Path | str | None = None):
        self.repo_root = Path(repo_root)
        self.plugins_root = Path(plugins_root) if plugins_root is not None else default_plugins_root()
        self.registry = PluginRegistry(self.plugins_root)
        self.runtime = PluginRuntime()
        self.sessions = PluginViewSessionStore()

    def _get_view_spec(self, plugin_id: str, view_id: str):
        manifest = self.registry.get_manifest(plugin_id)
        for view in manifest.views:
            if view.id == view_id:
                return manifest, view
        raise KeyError(f"未知插件视图: {plugin_id}/{view_id}")

    def _record_audit(
        self,
        *,
        event: str,
        plugin_id: str,
        view_id: str,
        payload: dict[str, Any],
        audit_context: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        track_count = len(payload.get("tracks") or [])
        segment_count = sum(len(track.get("segments") or []) for track in payload.get("tracks") or [])
        append_plugin_audit_event(
            self.repo_root,
            {
                "event": event,
                "plugin_id": plugin_id,
                "view_id": view_id,
                "session_id": session_id or "",
                "payload_bytes": _payload_bytes(payload),
                "track_count": track_count,
                "segment_count": segment_count,
                "account_id": str(audit_context.get("account_id") or ""),
                "bot_alias": str(audit_context.get("bot_alias") or ""),
            },
        )

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
                        "viewMode": view.view_mode,
                        "dataProfile": view.data_profile,
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
        manifest, view = self._get_view_spec(plugin_id, view_id)
        if view.view_mode == "session":
            return await self.open_view(
                plugin_id=plugin_id,
                view_id=view_id,
                input_payload=input_payload,
                audit_context=audit_context,
            )
        result = await self.runtime.render_view(manifest, view_id, input_payload)
        payload = {
            "pluginId": plugin_id,
            "viewId": view_id,
            "title": str(result.get("title") or ""),
            "renderer": str(result.get("renderer") or ""),
            "mode": "snapshot",
            "payload": dict(result.get("payload") or {}),
        }
        self._record_audit(
            event="render_view",
            plugin_id=plugin_id,
            view_id=view_id,
            payload=payload,
            audit_context=audit_context,
        )
        return payload

    async def open_view(
        self,
        *,
        plugin_id: str,
        view_id: str,
        input_payload: dict[str, Any],
        audit_context: dict[str, Any],
    ) -> dict[str, Any]:
        manifest, view = self._get_view_spec(plugin_id, view_id)
        if view.view_mode == "snapshot":
            return await self.render_view(
                plugin_id=plugin_id,
                view_id=view_id,
                input_payload=input_payload,
                audit_context=audit_context,
            )
        resolved_input = dict(input_payload or {})
        source_identity = build_source_identity(resolved_input)
        source_fingerprint = build_source_fingerprint(resolved_input)
        cache_key = self.sessions.build_cache_key(plugin_id, view_id, source_fingerprint)
        cached = self.sessions.get_cached(cache_key)
        if cached is not None:
            return dict(cached.opened_payload)

        result = await self.runtime.open_view(manifest, view_id, resolved_input)
        payload = {
            "pluginId": plugin_id,
            "viewId": view_id,
            "title": str(result.get("title") or ""),
            "renderer": str(result.get("renderer") or ""),
            "mode": "session",
            "sessionId": str(result.get("sessionId") or ""),
            "summary": dict(result.get("summary") or {}),
            "initialWindow": dict(result.get("initialWindow") or {}),
        }
        if not payload["sessionId"]:
            raise RuntimeError("插件未返回 sessionId")

        stale = self.sessions.replace(
            PluginViewSessionRecord(
                plugin_id=plugin_id,
                view_id=view_id,
                session_id=payload["sessionId"],
                renderer=payload["renderer"],
                source_identity=source_identity,
                source_fingerprint=source_fingerprint,
                resolved_input=resolved_input,
                opened_payload=payload,
            )
        )
        if stale is not None and stale.plugin_id == plugin_id:
            try:
                await self.runtime.dispose_view(manifest, stale.session_id)
            except Exception:
                pass

        self._record_audit(
            event="open_view",
            plugin_id=plugin_id,
            view_id=view_id,
            payload=payload,
            audit_context=audit_context,
            session_id=payload["sessionId"],
        )
        return payload

    async def get_view_window(
        self,
        *,
        plugin_id: str,
        session_id: str,
        request_payload: dict[str, Any],
        audit_context: dict[str, Any],
    ) -> dict[str, Any]:
        record = self.sessions.get(session_id)
        if record.plugin_id != plugin_id:
            raise KeyError(f"未知插件会话: {plugin_id}/{session_id}")
        manifest = self.registry.get_manifest(plugin_id)
        payload = await self.runtime.get_view_window(manifest, session_id, request_payload)
        self._record_audit(
            event="query_window",
            plugin_id=plugin_id,
            view_id=record.view_id,
            payload=payload,
            audit_context=audit_context,
            session_id=session_id,
        )
        return payload

    async def dispose_view(
        self,
        *,
        plugin_id: str,
        session_id: str,
        audit_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self.sessions.remove(session_id)
        if record is None or record.plugin_id != plugin_id:
            raise KeyError(f"未知插件会话: {plugin_id}/{session_id}")
        manifest = self.registry.get_manifest(plugin_id)
        payload = await self.runtime.dispose_view(manifest, session_id)
        append_plugin_audit_event(
            self.repo_root,
            {
                "event": "dispose_view",
                "plugin_id": plugin_id,
                "view_id": record.view_id,
                "session_id": session_id,
                "payload_bytes": _payload_bytes(payload),
                "track_count": 0,
                "segment_count": 0,
                "account_id": str((audit_context or {}).get("account_id") or ""),
                "bot_alias": str((audit_context or {}).get("bot_alias") or ""),
            },
        )
        return payload

    async def shutdown(self) -> None:
        records = self.sessions.records()
        for record in records:
            manifest = self.registry.get_manifest(record.plugin_id)
            try:
                await self.runtime.dispose_view(manifest, record.session_id)
            except Exception:
                pass
        self.sessions = PluginViewSessionStore()
        await self.runtime.shutdown()
