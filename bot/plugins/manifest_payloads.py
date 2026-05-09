from __future__ import annotations

import json
from typing import Any


def serialize_permissions(manifest) -> dict[str, Any]:
    return {
        "workspaceRead": manifest.runtime.permissions.workspace_read,
        "workspaceList": manifest.runtime.permissions.workspace_list,
        "tempArtifacts": manifest.runtime.permissions.temp_artifacts,
    }


def serialize_config_schema(manifest) -> dict[str, Any] | None:
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


def serialize_action(action) -> dict[str, Any]:
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


def build_manifest_signature(manifest) -> str:
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
                "permissions": serialize_permissions(manifest),
            },
            "views": [(view.id, view.renderer, view.view_mode, view.data_profile) for view in manifest.views],
            "handlers": [(handler.id, handler.extensions, handler.view_id) for handler in manifest.file_handlers],
            "config_schema": serialize_config_schema(manifest),
            "catalog_actions": [serialize_action(action) for action in manifest.catalog_actions],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def stable_config_fingerprint(manifest) -> str:
    return json.dumps(dict(manifest.config), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_manifest_payload(manifest) -> dict[str, Any]:
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
        "catalogActions": [serialize_action(action) for action in manifest.catalog_actions],
        "runtime": {
            "type": manifest.runtime.runtime_type,
            "entry": manifest.runtime.entry,
            "protocol": manifest.runtime.protocol,
            "permissions": serialize_permissions(manifest),
        },
    }
    if manifest.config_schema is not None:
        payload["configSchema"] = serialize_config_schema(manifest)
    return payload

