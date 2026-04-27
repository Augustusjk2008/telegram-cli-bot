from __future__ import annotations

import asyncio
import copy
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .artifacts import ArtifactRecord, ArtifactStore
from .audit import append_plugin_audit_event
from .host_api import PluginHostApi
from .host_api import resolve_workspace_path
from .manifest import load_plugin_manifest
from .paths import default_plugins_root
from .registry import PluginRegistry
from .runtime import PluginRuntime
from .view_sessions import (
    PluginViewSessionRecord,
    PluginViewSessionStore,
    build_snapshot_cache_key,
    build_source_fingerprint,
    build_source_identity,
)


def _payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _count_tree_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    stack = list(nodes)
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(item for item in list(node.get("children") or []) if isinstance(item, dict))
    return total


class PluginService:
    def __init__(
        self,
        repo_root: Path | str,
        plugins_root: Path | str | None = None,
        source_plugins_root: Path | str | None = None,
        *,
        workspace_root_for: Callable[[str], Path] | None = None,
        render_concurrency: int = 2,
    ):
        self.repo_root = Path(repo_root)
        self.plugins_root = Path(plugins_root) if plugins_root is not None else default_plugins_root()
        self.source_plugins_root = (
            Path(source_plugins_root)
            if source_plugins_root is not None
            else self.repo_root / "examples" / "plugins"
        )
        self._sync_bundled_plugin_manifests()
        self._workspace_root_for = workspace_root_for or (lambda _alias: self.repo_root)
        self.registry = PluginRegistry(self.plugins_root)
        self.artifacts = ArtifactStore(self.repo_root)
        self.runtime = PluginRuntime(
            workspace_root_for=self._workspace_root_for,
            host_api=PluginHostApi(self.artifacts),
            audit_hook=self._record_runtime_audit,
        )
        self.sessions = PluginViewSessionStore()
        self._snapshot_cache: dict[str, dict[str, Any]] = {}
        self._snapshot_cache_plugins: dict[str, set[str]] = {}
        self._render_semaphore = asyncio.Semaphore(max(1, int(render_concurrency)))

    def _get_view_spec(self, plugin_id: str, view_id: str):
        manifest = self.registry.get_manifest(plugin_id)
        if not manifest.enabled:
            raise KeyError(f"插件已禁用: {plugin_id}")
        for view in manifest.views:
            if view.id == view_id:
                return manifest, view
        raise KeyError(f"未知插件视图: {plugin_id}/{view_id}")

    def _serialize_permissions(self, manifest) -> dict[str, Any]:
        return {
            "workspaceRead": manifest.runtime.permissions.workspace_read,
            "workspaceList": manifest.runtime.permissions.workspace_list,
            "tempArtifacts": manifest.runtime.permissions.temp_artifacts,
        }

    def _serialize_config_schema(self, manifest) -> dict[str, Any] | None:
        if manifest.config_schema is None:
            return None
        return {
            "title": manifest.config_schema.title,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "description": section.description,
                    "fields": [
                        {
                            "key": field.key,
                            "label": field.label,
                            "type": field.field_type,
                            "default": field.default,
                            "description": field.description,
                            "placeholder": field.placeholder,
                            "minimum": field.minimum,
                            "maximum": field.maximum,
                            "step": field.step,
                            "options": [
                                {"value": option.value, "label": option.label}
                                for option in field.options
                            ],
                        }
                        for field in section.fields
                    ],
                }
                for section in manifest.config_schema.sections
            ],
        }

    def _serialize_action(self, action) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": action.id,
            "label": action.label,
            "target": action.target,
            "location": action.location,
            "variant": action.variant,
            "disabled": action.disabled,
            "payload": dict(action.payload or {}),
        }
        if action.icon:
            payload["icon"] = action.icon
        if action.tooltip:
            payload["tooltip"] = action.tooltip
        if action.confirm is not None:
            payload["confirm"] = dict(action.confirm)
        if action.host_action is not None:
            payload["hostAction"] = dict(action.host_action)
        return payload

    def _get_session_record(
        self,
        *,
        session_id: str,
        plugin_id: str,
        bot_alias: str,
        view_id: str | None = None,
    ) -> PluginViewSessionRecord:
        record = self.sessions.get_optional(session_id)
        if record is None:
            raise KeyError(f"未知插件会话: {plugin_id}/{session_id}")
        if record.bot_alias != bot_alias or record.plugin_id != plugin_id:
            raise KeyError(f"未知插件会话: {plugin_id}/{session_id}")
        if view_id is not None and record.view_id != view_id:
            raise KeyError(f"未知插件会话: {plugin_id}/{session_id}")
        return record

    def _manifest_signature(self, manifest) -> str:
        manifest_path = manifest.root / "plugin.json"
        try:
            stat = manifest_path.stat()
        except OSError:
            return "missing"
        return json.dumps(
            {
                "root": str(manifest.root),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "schema_version": manifest.schema_version,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "enabled": manifest.enabled,
                "config": dict(manifest.config),
                "runtime": {
                    "type": manifest.runtime.runtime_type,
                    "entry": manifest.runtime.entry,
                    "protocol": manifest.runtime.protocol,
                    "permissions": {
                        "workspaceRead": manifest.runtime.permissions.workspace_read,
                        "workspaceList": manifest.runtime.permissions.workspace_list,
                        "tempArtifacts": manifest.runtime.permissions.temp_artifacts,
                    },
                },
                "views": [(view.id, view.renderer, view.view_mode, view.data_profile) for view in manifest.views],
                "handlers": [(handler.id, handler.extensions, handler.view_id) for handler in manifest.file_handlers],
                "config_schema": self._serialize_config_schema(manifest),
                "catalog_actions": [self._serialize_action(action) for action in manifest.catalog_actions],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _stable_config_fingerprint(self, manifest) -> str:
        return json.dumps(dict(manifest.config), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _snapshot_cache_remember(self, plugin_id: str, cache_key: str, payload: dict[str, Any]) -> None:
        self._snapshot_cache[cache_key] = copy.deepcopy(payload)
        self._snapshot_cache_plugins.setdefault(plugin_id, set()).add(cache_key)

    def _snapshot_cache_get(self, cache_key: str) -> dict[str, Any] | None:
        cached = self._snapshot_cache.get(cache_key)
        return copy.deepcopy(cached) if cached is not None else None

    def _snapshot_cache_clear_plugin(self, plugin_id: str) -> None:
        keys = self._snapshot_cache_plugins.pop(plugin_id, set())
        for key in keys:
            self._snapshot_cache.pop(key, None)

    def _resolve_input_payload(self, bot_alias: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        resolved_input = dict(input_payload or {})
        path_value = resolved_input.get("path")
        if path_value is None:
            return resolved_input
        raw_path = Path(str(path_value))
        if raw_path.is_absolute():
            resolved_input["path"] = str(raw_path.expanduser().resolve())
            return resolved_input
        resolved_input["path"] = str(resolve_workspace_path(self._workspace_root_for(bot_alias), str(path_value)))
        return resolved_input

    def _manifest_payload(self, manifest) -> dict[str, Any]:
        payload = {
            "id": manifest.plugin_id,
            "schemaVersion": manifest.schema_version,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "enabled": manifest.enabled,
            "config": dict(manifest.config),
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
            "catalogActions": [self._serialize_action(action) for action in manifest.catalog_actions],
            "runtime": {
                "type": manifest.runtime.runtime_type,
                "entry": manifest.runtime.entry,
                "protocol": manifest.runtime.protocol,
                "permissions": self._serialize_permissions(manifest),
            },
        }
        if manifest.config_schema is not None:
            payload["configSchema"] = self._serialize_config_schema(manifest)
        return payload

    def _read_manifest_json(self, path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return raw if isinstance(raw, dict) else None

    def _merge_bundled_manifest(
        self,
        source_raw: dict[str, Any],
        installed_raw: dict[str, Any],
    ) -> dict[str, Any]:
        merged = copy.deepcopy(source_raw)
        if "enabled" in installed_raw:
            merged["enabled"] = bool(installed_raw.get("enabled"))
        source_config = merged.get("config") if isinstance(merged.get("config"), dict) else {}
        installed_config = installed_raw.get("config") if isinstance(installed_raw.get("config"), dict) else {}
        if source_config or installed_config:
            merged["config"] = {**source_config, **installed_config}
        return merged

    def _sync_bundled_plugin_manifests(self) -> None:
        if not self.source_plugins_root.exists() or not self.plugins_root.exists():
            return
        for source_dir in self._iter_source_plugin_dirs():
            target_manifest_path = self.plugins_root / source_dir.name / "plugin.json"
            if not target_manifest_path.is_file():
                continue
            source_raw = self._read_manifest_json(source_dir / "plugin.json")
            installed_raw = self._read_manifest_json(target_manifest_path)
            if source_raw is None or installed_raw is None:
                continue
            merged = self._merge_bundled_manifest(source_raw, installed_raw)
            if merged == installed_raw:
                continue
            target_manifest_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def _iter_source_plugin_dirs(self) -> list[Path]:
        root = self.source_plugins_root
        if not root.exists():
            return []
        return [
            path
            for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
            if path.is_dir() and (path / "plugin.json").is_file()
        ]

    def _build_installable_plugin_payload(self, source_dir: Path) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        manifest_path = source_dir / "plugin.json"
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = {}
        plugin_id = str(raw.get("id") or source_dir.name).strip() or source_dir.name
        return {
            "id": source_dir.name,
            "pluginId": plugin_id,
            "name": str(raw.get("name") or source_dir.name).strip() or source_dir.name,
            "version": str(raw.get("version") or "").strip(),
            "description": str(raw.get("description") or "").strip(),
            "installed": (self.plugins_root / source_dir.name).exists(),
        }

    def list_installable_plugins(self) -> list[dict[str, Any]]:
        return [self._build_installable_plugin_payload(path) for path in self._iter_source_plugin_dirs()]

    def _resolve_install_source_dir(
        self,
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
                for path in self._iter_source_plugin_dirs()
                if path.name == normalized_install_id
                or self._build_installable_plugin_payload(path)["pluginId"] == normalized_install_id
            ),
            None,
        )
        if source_dir is None:
            raise KeyError(f"未找到可安装插件: {normalized_install_id}")
        return source_dir

    def _build_payload_metrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        tracks = [item for item in list(payload.get("tracks") or []) if isinstance(item, dict)]
        rows = [item for item in list(payload.get("rows") or []) if isinstance(item, dict)]
        roots = [item for item in list(payload.get("roots") or []) if isinstance(item, dict)]
        nodes = [item for item in list(payload.get("nodes") or []) if isinstance(item, dict)]
        return {
            "payload_bytes": _payload_bytes(payload),
            "track_count": len(tracks),
            "segment_count": sum(len(track.get("segments") or []) for track in tracks),
            "row_count": len(rows),
            "node_count": _count_tree_nodes(roots) + _count_tree_nodes(nodes),
        }

    def _record_audit(
        self,
        *,
        event: str,
        plugin_id: str,
        view_id: str,
        payload: dict[str, Any],
        audit_context: dict[str, Any],
        session_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        append_plugin_audit_event(
            self.repo_root,
            {
                "event": event,
                "plugin_id": plugin_id,
                "view_id": view_id,
                "session_id": session_id or "",
                **self._build_payload_metrics(payload),
                "account_id": str(audit_context.get("account_id") or ""),
                "bot_alias": str(audit_context.get("bot_alias") or ""),
                **(extra or {}),
            },
        )

    def _record_runtime_audit(self, payload: dict[str, Any]) -> None:
        append_plugin_audit_event(self.repo_root, payload)

    def _validate_render_result(
        self,
        plugin_id: str,
        view,
        result: dict[str, Any],
        *,
        expect_session: bool,
    ) -> dict[str, Any]:
        renderer = str(result.get("renderer") or "")
        if renderer != view.renderer:
            raise RuntimeError(f"插件 renderer 不匹配: expected={view.renderer} actual={renderer}")
        payload = {
            "pluginId": plugin_id,
            "viewId": view.id,
            "title": str(result.get("title") or view.title or ""),
            "renderer": renderer,
        }
        if expect_session:
            session_id = str(result.get("sessionId") or "")
            if not session_id:
                raise RuntimeError("插件未返回 sessionId")
            return {
                **payload,
                "mode": "session",
                "sessionId": session_id,
                "summary": dict(result.get("summary") or {}),
                "initialWindow": dict(result.get("initialWindow") or {}),
            }
        return {
            **payload,
            "mode": "snapshot",
            "payload": dict(result.get("payload") or {}),
        }

    def _normalize_action_result(self, result: dict[str, Any]) -> dict[str, Any]:
        refresh = str(result.get("refresh") or "none").strip() or "none"
        if refresh not in {"none", "view", "session"}:
            refresh = "none"
        host_effects = result.get("hostEffects") or []
        if not isinstance(host_effects, list):
            raise RuntimeError("插件 action hostEffects 必须是数组")
        return {
            "message": str(result.get("message") or ""),
            "refresh": refresh,
            "hostEffects": [dict(item) for item in host_effects if isinstance(item, dict)],
            "closeSession": bool(result.get("closeSession", False)),
        }

    def list_plugins(self, refresh: bool = False) -> list[dict[str, Any]]:
        if refresh:
            self._sync_bundled_plugin_manifests()
            manifests = list(self.registry.discover().values())
        else:
            manifests = self.registry.list_manifests()
        return [self._manifest_payload(manifest) for manifest in manifests]

    async def reload_plugins(self) -> list[dict[str, Any]]:
        before = {
            manifest.plugin_id: self._manifest_signature(manifest)
            for manifest in self.registry.list_manifests()
        }
        self._sync_bundled_plugin_manifests()
        manifests = self.registry.discover()
        after = {
            plugin_id: self._manifest_signature(manifest)
            for plugin_id, manifest in manifests.items()
        }
        affected = sorted(
            plugin_id
            for plugin_id in set(before) | set(after)
            if before.get(plugin_id) != after.get(plugin_id)
        )
        for plugin_id in affected:
            self.sessions.clear_plugin(plugin_id)
            self.artifacts.clear_plugin(plugin_id)
            self._snapshot_cache_clear_plugin(plugin_id)
            await self.runtime.stop_plugin_instances(plugin_id)
        return [self._manifest_payload(manifest) for manifest in manifests.values()]

    async def install_plugin(
        self,
        install_id: str | None = None,
        *,
        source_path: str | Path | None = None,
    ) -> dict[str, Any]:
        source_dir = self._resolve_install_source_dir(install_id, source_path=source_path)
        manifest = load_plugin_manifest(source_dir / "plugin.json")
        target_dir = self.plugins_root / source_dir.name
        if target_dir.exists():
            raise FileExistsError(f"插件已安装: {source_dir.name}")

        discovered = self.registry.discover()
        if manifest.plugin_id in discovered:
            raise ValueError(f"插件已存在: {manifest.plugin_id}")

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(
                source_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            self.registry.discover()
            return self._manifest_payload(self.registry.get_manifest(manifest.plugin_id))
        except Exception:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            try:
                self.registry.discover()
            except Exception:
                pass
            raise

    async def update_plugin(
        self,
        plugin_id: str,
        *,
        enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.registry.discover()
        manifest = self.registry.get_manifest(plugin_id)
        manifest_path = manifest.root / "plugin.json"
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if enabled is not None:
            raw["enabled"] = bool(enabled)
        if config is not None:
            current_config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
            raw["config"] = {**current_config, **dict(config)}
        manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.registry.discover()

        stale_records = self.sessions.clear_plugin(plugin_id)
        for record in stale_records:
            try:
                current_manifest = self.registry.get_manifest(plugin_id)
                await self.runtime.dispose_view(record.bot_alias, current_manifest, record.session_id)
            except Exception:
                pass
        self.artifacts.clear_plugin(plugin_id)
        self._snapshot_cache_clear_plugin(plugin_id)
        await self.runtime.stop_plugin_instances(plugin_id)
        return self._manifest_payload(self.registry.get_manifest(plugin_id))

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
        bot_alias: str,
        plugin_id: str,
        view_id: str,
        input_payload: dict[str, Any],
        audit_context: dict[str, Any],
    ) -> dict[str, Any]:
        manifest, view = self._get_view_spec(plugin_id, view_id)
        if view.view_mode == "session":
            return await self.open_view(
                bot_alias=bot_alias,
                plugin_id=plugin_id,
                view_id=view_id,
                input_payload=input_payload,
                audit_context=audit_context,
            )
        resolved_input = self._resolve_input_payload(bot_alias, input_payload)
        source_fingerprint = build_source_fingerprint(resolved_input)
        cache_key = build_snapshot_cache_key(
            bot_alias=bot_alias,
            plugin_id=plugin_id,
            view_id=view_id,
            source_fingerprint=source_fingerprint,
            config_fingerprint=self._stable_config_fingerprint(manifest),
            manifest_fingerprint=self._manifest_signature(manifest),
        )
        cached = self._snapshot_cache_get(cache_key)
        if cached is not None:
            self._record_audit(
                event="render_view_cache_hit",
                plugin_id=plugin_id,
                view_id=view_id,
                payload=dict(cached.get("payload") or {}),
                audit_context=audit_context,
            )
            await self.evict_idle_runtimes()
            return cached
        async with self._render_semaphore:
            result = await self.runtime.render_view(bot_alias, manifest, view_id, resolved_input)
        payload = self._validate_render_result(plugin_id, view, result, expect_session=False)
        self._snapshot_cache_remember(plugin_id, cache_key, payload)
        self._record_audit(
            event="render_view",
            plugin_id=plugin_id,
            view_id=view_id,
            payload=payload,
            audit_context=audit_context,
        )
        await self.evict_idle_runtimes()
        return payload

    async def open_view(
        self,
        *,
        bot_alias: str,
        plugin_id: str,
        view_id: str,
        input_payload: dict[str, Any],
        audit_context: dict[str, Any],
    ) -> dict[str, Any]:
        manifest, view = self._get_view_spec(plugin_id, view_id)
        if view.view_mode == "snapshot":
            return await self.render_view(
                bot_alias=bot_alias,
                plugin_id=plugin_id,
                view_id=view_id,
                input_payload=input_payload,
                audit_context=audit_context,
            )
        resolved_input = self._resolve_input_payload(bot_alias, input_payload)
        source_identity = build_source_identity(resolved_input)
        source_fingerprint = build_source_fingerprint(
            resolved_input,
            hash_file_contents=view.data_profile != "heavy",
        )
        cache_key = self.sessions.build_cache_key(bot_alias, plugin_id, view_id, source_fingerprint)
        cached = self.sessions.get_cached(cache_key)
        if cached is not None:
            await self.evict_idle_runtimes()
            return dict(cached.opened_payload)

        result = await self.runtime.open_view(bot_alias, manifest, view_id, resolved_input)
        payload = self._validate_render_result(plugin_id, view, result, expect_session=True)

        stale = self.sessions.replace(
            PluginViewSessionRecord(
                bot_alias=bot_alias,
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
        if stale is not None:
            try:
                await self.runtime.dispose_view(stale.bot_alias, manifest, stale.session_id)
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
        await self.evict_idle_runtimes()
        return payload

    async def get_view_window(
        self,
        *,
        bot_alias: str,
        plugin_id: str,
        session_id: str,
        request_payload: dict[str, Any],
        audit_context: dict[str, Any],
    ) -> dict[str, Any]:
        record = self._get_session_record(
            session_id=session_id,
            plugin_id=plugin_id,
            bot_alias=bot_alias,
        )
        manifest = self.registry.get_manifest(plugin_id)
        if not manifest.enabled:
            raise KeyError(f"插件已禁用: {plugin_id}")
        payload = await self.runtime.get_view_window(bot_alias, manifest, session_id, request_payload)
        self.sessions.remember_window_request(session_id, request_payload)
        self._record_audit(
            event="query_window",
            plugin_id=plugin_id,
            view_id=record.view_id,
            payload=payload,
            audit_context=audit_context,
            session_id=session_id,
        )
        await self.evict_idle_runtimes()
        return payload

    async def invoke_action(
        self,
        *,
        bot_alias: str,
        plugin_id: str,
        view_id: str,
        action_id: str,
        payload: dict[str, Any],
        audit_context: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        manifest, _view = self._get_view_spec(plugin_id, view_id)
        if session_id:
            self._get_session_record(
                session_id=session_id,
                plugin_id=plugin_id,
                bot_alias=bot_alias,
                view_id=view_id,
            )
        result = await self.runtime.invoke_action(
            bot_alias,
            manifest,
            view_id=view_id,
            session_id=session_id,
            action_id=action_id,
            payload=dict(payload or {}),
        )
        normalized = self._normalize_action_result(result)
        self._record_audit(
            event="invoke_action",
            plugin_id=plugin_id,
            view_id=view_id,
            payload=normalized,
            audit_context=audit_context,
            session_id=session_id,
            extra={
                "action_id": action_id,
                "action_target": "plugin",
            },
        )
        await self.evict_idle_runtimes()
        return normalized

    async def dispose_view(
        self,
        *,
        bot_alias: str,
        plugin_id: str,
        session_id: str,
        audit_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self.sessions.remove(session_id)
        if record is None or record.bot_alias != bot_alias or record.plugin_id != plugin_id:
            raise KeyError(f"未知插件会话: {plugin_id}/{session_id}")
        manifest = self.registry.get_manifest(plugin_id)
        payload = await self.runtime.dispose_view(bot_alias, manifest, session_id)
        self._record_audit(
            event="dispose_view",
            plugin_id=plugin_id,
            view_id=record.view_id,
            payload=payload,
            audit_context=audit_context or {},
            session_id=session_id,
        )
        await self.evict_idle_runtimes()
        return payload

    def get_artifact(self, *, bot_alias: str, artifact_id: str) -> ArtifactRecord:
        return self.artifacts.get(bot_alias=bot_alias, artifact_id=artifact_id)

    async def evict_idle_runtimes(self) -> int:
        return await self.runtime.evict_idle_processes()

    async def shutdown(self) -> None:
        records = self.sessions.records()
        for record in records:
            try:
                manifest = self.registry.get_manifest(record.plugin_id)
                await self.runtime.dispose_view(record.bot_alias, manifest, record.session_id)
            except Exception:
                pass
        self.sessions = PluginViewSessionStore()
        self.artifacts.clear_all()
        self._snapshot_cache.clear()
        self._snapshot_cache_plugins.clear()
        await self.runtime.shutdown()
