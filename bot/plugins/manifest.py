from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    PluginActionSpec,
    PluginConfigFieldOption,
    PluginConfigFieldSpec,
    PluginConfigSchemaSpec,
    PluginConfigSectionSpec,
    PluginFileHandlerSpec,
    PluginManifest,
    PluginPermissions,
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


def _parse_permissions(value: Any) -> PluginPermissions:
    current = _expect_mapping(value, "runtime.permissions")
    allowed = {
        "workspaceRead": "workspace_read",
        "workspaceList": "workspace_list",
        "tempArtifacts": "temp_artifacts",
    }
    unknown = sorted(key for key in current.keys() if key not in allowed)
    if unknown:
        raise ValueError(f"runtime.permissions 包含未知字段: {', '.join(unknown)}")
    return PluginPermissions(
        workspace_read=bool(current.get("workspaceRead", False)),
        workspace_list=bool(current.get("workspaceList", False)),
        temp_artifacts=bool(current.get("tempArtifacts", False)),
    )


def _parse_config_schema(value: Any) -> PluginConfigSchemaSpec:
    current = _expect_mapping(value, "configSchema")
    sections_raw = current.get("sections") or []
    if not isinstance(sections_raw, list):
        raise ValueError("configSchema.sections 必须是数组")

    sections: list[PluginConfigSectionSpec] = []
    seen_section_ids: set[str] = set()
    for section_item in sections_raw:
        section = _expect_mapping(section_item, "configSchema.section")
        section_id = str(section.get("id") or "").strip()
        if not section_id:
            raise ValueError("configSchema.section.id 不能为空")
        if section_id in seen_section_ids:
            raise ValueError(f"重复的 configSchema.section.id: {section_id}")
        seen_section_ids.add(section_id)

        fields_raw = section.get("fields") or []
        if not isinstance(fields_raw, list):
            raise ValueError("configSchema.section.fields 必须是数组")
        seen_field_keys: set[str] = set()
        fields: list[PluginConfigFieldSpec] = []
        for field_item in fields_raw:
            field_spec = _parse_config_field(field_item)
            if field_spec.key in seen_field_keys:
                raise ValueError(f"重复的 configSchema.field.key: {field_spec.key}")
            seen_field_keys.add(field_spec.key)
            fields.append(field_spec)

        sections.append(
            PluginConfigSectionSpec(
                id=section_id,
                title=str(section.get("title") or "").strip(),
                description=str(section.get("description") or "").strip(),
                fields=tuple(fields),
            )
        )

    return PluginConfigSchemaSpec(
        title=str(current.get("title") or "").strip(),
        sections=tuple(sections),
    )


def _parse_config_field(value: Any) -> PluginConfigFieldSpec:
    current = _expect_mapping(value, "configSchema.field")
    field_type = _normalize_choice(
        current.get("type"),
        "configSchema.field.type",
        {"boolean", "string", "integer", "number", "select"},
        "",
    )
    key = str(current.get("key") or "").strip()
    label = str(current.get("label") or "").strip()
    if not key:
        raise ValueError("configSchema.field.key 不能为空")
    if not label:
        raise ValueError(f"configSchema.field.label 不能为空: {key}")
    options: list[PluginConfigFieldOption] = []
    if field_type == "select":
        options_raw = current.get("options") or []
        if not isinstance(options_raw, list) or not options_raw:
            raise ValueError(f"configSchema.field.options 不能为空: {key}")
        for option_item in options_raw:
            option = _expect_mapping(option_item, "configSchema.field.option")
            value_text = str(option.get("value") or "").strip()
            label_text = str(option.get("label") or "").strip()
            if not value_text or not label_text:
                raise ValueError(f"configSchema.field.option 无效: {key}")
            options.append(PluginConfigFieldOption(value=value_text, label=label_text))

    def _maybe_number(raw_value: Any, label_text: str) -> float | None:
        if raw_value is None or raw_value == "":
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        raise ValueError(f"{label_text} 必须是数字")

    return PluginConfigFieldSpec(
        key=key,
        label=label,
        field_type=field_type,
        default=current.get("default"),
        description=str(current.get("description") or "").strip(),
        placeholder=str(current.get("placeholder") or "").strip(),
        minimum=_maybe_number(current.get("minimum"), f"configSchema.field.minimum[{key}]"),
        maximum=_maybe_number(current.get("maximum"), f"configSchema.field.maximum[{key}]"),
        step=_maybe_number(current.get("step"), f"configSchema.field.step[{key}]"),
        options=tuple(options),
    )


def _parse_action(value: Any, *, label: str) -> PluginActionSpec:
    current = _expect_mapping(value, label)
    action_id = str(current.get("id") or "").strip()
    action_label = str(current.get("label") or "").strip()
    if not action_id:
        raise ValueError(f"{label}.id 不能为空")
    if not action_label:
        raise ValueError(f"{label}.label 不能为空: {action_id}")
    return PluginActionSpec(
        id=action_id,
        label=action_label,
        target=_normalize_choice(current.get("target"), f"{label}.target", {"plugin", "host"}, "plugin"),
        location=_normalize_choice(current.get("location"), f"{label}.location", {"catalog", "toolbar", "row", "node"}, "catalog"),
        icon=str(current.get("icon") or "").strip(),
        tooltip=str(current.get("tooltip") or "").strip(),
        variant=_normalize_choice(current.get("variant"), f"{label}.variant", {"default", "primary", "danger"}, "default"),
        disabled=bool(current.get("disabled", False)),
        payload=dict(_expect_mapping(current.get("payload") or {}, f"{label}.payload")),
        host_action=dict(_expect_mapping(current.get("hostAction"), f"{label}.hostAction")) if current.get("hostAction") is not None else None,
        confirm=dict(_expect_mapping(current.get("confirm"), f"{label}.confirm")) if current.get("confirm") is not None else None,
    )


def load_plugin_manifest(path: Path) -> PluginManifest:
    raw = _expect_mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    schema_version = int(raw.get("schemaVersion") or 0)
    if schema_version not in {1, 2}:
        raise ValueError(f"不支持的插件 schemaVersion: {raw.get('schemaVersion')}")

    runtime_raw = _expect_mapping(raw.get("runtime"), "runtime")
    views_raw = raw.get("views") or []
    handlers_raw = raw.get("fileHandlers") or []
    if not isinstance(views_raw, list):
        raise ValueError("views 必须是数组")
    if not isinstance(handlers_raw, list):
        raise ValueError("fileHandlers 必须是数组")

    permissions_raw = runtime_raw.get("permissions")
    if schema_version == 1 and permissions_raw is not None:
        raise ValueError("schemaVersion=1 不支持 runtime.permissions")
    permissions = _parse_permissions(permissions_raw or {}) if schema_version == 2 else PluginPermissions()

    views: list[PluginViewSpec] = []
    seen_view_ids: set[str] = set()
    allowed_renderers = {"waveform"} if schema_version == 1 else {"waveform", "table", "tree", "document"}
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
                renderer=_normalize_choice(current.get("renderer"), "view.renderer", allowed_renderers, ""),
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

    if schema_version == 1 and raw.get("configSchema") is not None:
        raise ValueError("schemaVersion=1 不支持 configSchema")
    if schema_version == 1 and raw.get("catalogActions") is not None:
        raise ValueError("schemaVersion=1 不支持 catalogActions")

    config_schema = _parse_config_schema(raw.get("configSchema")) if schema_version == 2 and raw.get("configSchema") is not None else None
    catalog_actions_raw = raw.get("catalogActions") or []
    if not isinstance(catalog_actions_raw, list):
        raise ValueError("catalogActions 必须是数组")
    catalog_actions = tuple(
        _parse_action(item, label="catalogActions.item")
        for item in catalog_actions_raw
    ) if schema_version == 2 else ()

    return PluginManifest(
        root=path.parent.resolve(),
        plugin_id=str(raw.get("id") or "").strip(),
        schema_version=schema_version,
        name=str(raw.get("name") or "").strip(),
        version=str(raw.get("version") or "").strip(),
        description=str(raw.get("description") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
        config=dict(_expect_mapping(raw.get("config") or {}, "config")),
        runtime=PluginRuntimeSpec(
            runtime_type=str(runtime_raw.get("type") or "").strip(),
            entry=str(runtime_raw.get("entry") or "").strip(),
            protocol=str(runtime_raw.get("protocol") or "").strip(),
            permissions=permissions,
        ),
        views=tuple(views),
        file_handlers=tuple(file_handlers),
        config_schema=config_schema,
        catalog_actions=catalog_actions,
    )
