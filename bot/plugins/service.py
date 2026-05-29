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
from .catalog import (
    build_installable_plugin_payload,
    iter_source_plugin_dirs,
    merge_bundled_manifest,
    read_manifest_json,
    resolve_install_source_dir,
    sync_bundled_plugin_manifests,
)
from .execution import (
    build_payload_metrics,
    count_tree_nodes,
    normalize_action_result,
    payload_bytes,
    resolve_input_payload,
    validate_render_result,
)
from .host_api import PluginHostApi
from .manifest import load_plugin_manifest
from .manifest_payloads import (
    build_manifest_payload,
    build_manifest_signature,
    serialize_action,
    serialize_config_schema,
    serialize_permissions,
    stable_config_fingerprint,
)
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


_payload_bytes = payload_bytes
_count_tree_nodes = count_tree_nodes
_EDITABLE_PLUGIN_SOURCE_EXTENSIONS = frozenset({".md", ".mmd", ".mermaid"})


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
        self._snapshot_inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._session_inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._inflight_lock = asyncio.Lock()
        self._render_semaphore = asyncio.Semaphore(max(1, int(render_concurrency)))
        self._last_idle_eviction_at = 0.0
        self._idle_eviction_interval_seconds = 5.0

    def _get_view_spec(self, plugin_id: str, view_id: str):
        manifest = self.registry.get_manifest(plugin_id)
        if not manifest.enabled:
            raise KeyError(f"插件已禁用: {plugin_id}")
        for view in manifest.views:
            if view.id == view_id:
                return manifest, view
        raise KeyError(f"未知插件视图: {plugin_id}/{view_id}")

    def _serialize_permissions(self, manifest) -> dict[str, Any]:
        return serialize_permissions(manifest)

    def _serialize_config_schema(self, manifest) -> dict[str, Any] | None:
        return serialize_config_schema(manifest)

    def _serialize_action(self, action) -> dict[str, Any]:
        return serialize_action(action)

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
        return build_manifest_signature(manifest)

    def _stable_config_fingerprint(self, manifest) -> str:
        return stable_config_fingerprint(manifest)

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
            self._snapshot_inflight.pop(key, None)

    def _resolve_input_payload(self, bot_alias: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        return resolve_input_payload(bot_alias, input_payload, self._workspace_root_for)

    def _manifest_payload(self, manifest) -> dict[str, Any]:
        return build_manifest_payload(manifest)

    def _file_target_title(self, path: str) -> str:
        return Path(str(path or "")).name or str(path or "")

    def _plugin_target_from_resolution(
        self,
        path: str,
        resolution,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        _, view = self._get_view_spec(resolution.plugin_id, resolution.view_id)
        return {
            "pluginId": resolution.plugin_id,
            "viewId": resolution.view_id,
            "title": title if title is not None else (view.title or self._file_target_title(path)),
            "input": {"path": path},
        }

    async def _invalidate_plugin(self, plugin_id: str, *, dispose_sessions: bool = False) -> None:
        stale_records = self.sessions.clear_plugin(plugin_id)
        if dispose_sessions:
            for record in stale_records:
                try:
                    current_manifest = self.registry.get_manifest(plugin_id)
                    await self.runtime.dispose_view(record.bot_alias, current_manifest, record.session_id)
                except Exception:
                    pass
        self.artifacts.clear_plugin(plugin_id)
        self._snapshot_cache_clear_plugin(plugin_id)
        self._session_inflight.clear()
        await self.runtime.stop_plugin_instances(plugin_id)

    def _read_manifest_json(self, path: Path) -> dict[str, Any] | None:
        return read_manifest_json(path)

    def _merge_bundled_manifest(
        self,
        source_raw: dict[str, Any],
        installed_raw: dict[str, Any],
    ) -> dict[str, Any]:
        return merge_bundled_manifest(source_raw, installed_raw)

    def _sync_bundled_plugin_manifests(self) -> None:
        sync_bundled_plugin_manifests(self.source_plugins_root, self.plugins_root)

    def _iter_source_plugin_dirs(self) -> list[Path]:
        return iter_source_plugin_dirs(self.source_plugins_root)

    def _build_installable_plugin_payload(self, source_dir: Path) -> dict[str, Any]:
        return build_installable_plugin_payload(source_dir, self.plugins_root)

    def list_installable_plugins(self) -> list[dict[str, Any]]:
        return [self._build_installable_plugin_payload(path) for path in self._iter_source_plugin_dirs()]

    def _resolve_install_source_dir(
        self,
        install_id: str | None = None,
        *,
        source_path: str | Path | None = None,
    ) -> Path:
        return resolve_install_source_dir(
            self.source_plugins_root,
            self.plugins_root,
            install_id,
            source_path=source_path,
        )

    def _build_payload_metrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_payload_metrics(payload)

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
        return validate_render_result(plugin_id, view, result, expect_session=expect_session)

    def _normalize_action_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return normalize_action_result(result)

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
            await self._invalidate_plugin(plugin_id)
        return [self._manifest_payload(manifest) for manifest in manifests.values()]

    async def install_plugin(
        self,
        install_id: str | None = None,
        *,
        source_path: str | Path | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        source_dir = self._resolve_install_source_dir(install_id, source_path=source_path)
        manifest = load_plugin_manifest(source_dir / "plugin.json")
        target_dir = self.plugins_root / source_dir.name
        discovered = self.registry.discover()
        existing_manifest = discovered.get(manifest.plugin_id)
        existing_root = existing_manifest.root if existing_manifest else None
        if (target_dir.exists() or existing_manifest is not None) and not force:
            raise FileExistsError(f"插件已安装: {source_dir.name}")

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        backups: list[tuple[Path, Path]] = []
        if force:
            await self._invalidate_plugin(manifest.plugin_id, dispose_sessions=True)
            seen_paths: set[Path] = set()
            backup_root = self.plugins_root.parent / ".plugin-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            for path in (existing_root, target_dir):
                current = Path(path) if path else None
                if current is None or not current.exists() or current in seen_paths:
                    continue
                seen_paths.add(current)
                backup_dir = backup_root / f"{current.name}.backup"
                index = 0
                while backup_dir.exists():
                    index += 1
                    backup_dir = backup_root / f"{current.name}.backup-{index}"
                current.rename(backup_dir)
                backups.append((current, backup_dir))
        try:
            shutil.copytree(
                source_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            self.registry.discover()
            for _original, backup_dir in backups:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
            return self._manifest_payload(self.registry.get_manifest(manifest.plugin_id))
        except Exception:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            for original, backup_dir in reversed(backups):
                if backup_dir.exists() and not original.exists():
                    backup_dir.rename(original)
            try:
                self.registry.discover()
            except Exception:
                pass
            raise

    async def uninstall_plugin(self, plugin_id: str) -> dict[str, Any]:
        self.registry.discover()
        manifest = self.registry.get_manifest(plugin_id)
        resolved_id = manifest.plugin_id
        await self._invalidate_plugin(resolved_id, dispose_sessions=True)
        shutil.rmtree(manifest.root)
        self.registry.discover()
        return {"id": resolved_id, "deleted": True}

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

        await self._invalidate_plugin(plugin_id, dispose_sessions=True)
        return self._manifest_payload(self.registry.get_manifest(plugin_id))

    def resolve_file_target(self, path: str) -> dict[str, Any]:
        resolution = self.registry.resolve_file_handler(path)
        if resolution is None:
            return {"kind": "file"}
        if Path(str(path or "")).suffix.lower() in _EDITABLE_PLUGIN_SOURCE_EXTENSIONS:
            return {
                "kind": "file",
                "pluginTargets": [self._plugin_target_from_resolution(path, resolution)],
            }
        return {
            "kind": "plugin_view",
            **self._plugin_target_from_resolution(path, resolution, title=self._file_target_title(path)),
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
            await self.evict_idle_runtimes(throttle=True)
            return cached
        async with self._inflight_lock:
            cached = self._snapshot_cache_get(cache_key)
            if cached is not None:
                return cached
            inflight = self._snapshot_inflight.get(cache_key)
            if inflight is None:
                inflight = asyncio.get_running_loop().create_future()
                inflight.add_done_callback(lambda future: future.exception() if future.done() and not future.cancelled() else None)
                self._snapshot_inflight[cache_key] = inflight
                owner = True
            else:
                owner = False
        if not owner:
            return copy.deepcopy(await inflight)
        async with self._render_semaphore:
            try:
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
                if not inflight.done():
                    inflight.set_result(copy.deepcopy(payload))
                await self.evict_idle_runtimes(throttle=True)
                return payload
            except Exception as exc:
                if not inflight.done():
                    inflight.set_exception(exc)
                raise
            finally:
                async with self._inflight_lock:
                    if self._snapshot_inflight.get(cache_key) is inflight:
                        self._snapshot_inflight.pop(cache_key, None)

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
            await self.evict_idle_runtimes(throttle=True)
            return dict(cached.opened_payload)
        async with self._inflight_lock:
            cached = self.sessions.get_cached(cache_key)
            if cached is not None:
                return dict(cached.opened_payload)
            inflight = self._session_inflight.get(cache_key)
            if inflight is None:
                inflight = asyncio.get_running_loop().create_future()
                inflight.add_done_callback(lambda future: future.exception() if future.done() and not future.cancelled() else None)
                self._session_inflight[cache_key] = inflight
                owner = True
            else:
                owner = False
        if not owner:
            return dict(copy.deepcopy(await inflight))

        try:
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
            if not inflight.done():
                inflight.set_result(copy.deepcopy(payload))
            await self.evict_idle_runtimes(throttle=True)
            return payload
        except Exception as exc:
            if not inflight.done():
                inflight.set_exception(exc)
            raise
        finally:
            async with self._inflight_lock:
                if self._session_inflight.get(cache_key) is inflight:
                    self._session_inflight.pop(cache_key, None)

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
        await self.evict_idle_runtimes(throttle=True)
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
        if session_id and normalized.get("closeSession"):
            self.sessions.remove(session_id)
            try:
                await self.runtime.dispose_view(bot_alias, manifest, session_id)
            except Exception:
                pass
        elif session_id and normalized.get("refresh") == "view":
            self.sessions.remove(session_id)
            try:
                await self.runtime.dispose_view(bot_alias, manifest, session_id)
            except Exception:
                pass
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
        await self.evict_idle_runtimes(throttle=True)
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
        await self.evict_idle_runtimes(throttle=True)
        return payload

    def get_artifact(self, *, bot_alias: str, artifact_id: str) -> ArtifactRecord:
        return self.artifacts.get(bot_alias=bot_alias, artifact_id=artifact_id)

    async def evict_idle_runtimes(self, *, throttle: bool = False) -> int:
        if throttle:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now - self._last_idle_eviction_at < self._idle_eviction_interval_seconds:
                return 0
            self._last_idle_eviction_at = now
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
        self._snapshot_inflight.clear()
        self._session_inflight.clear()
        await self.runtime.shutdown()
