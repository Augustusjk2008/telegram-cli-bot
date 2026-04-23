from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginPermissions:
    workspace_read: bool = False
    workspace_list: bool = False
    temp_artifacts: bool = False


@dataclass(frozen=True)
class PluginRuntimeSpec:
    runtime_type: str
    entry: str
    protocol: str
    permissions: PluginPermissions = field(default_factory=PluginPermissions)


@dataclass(frozen=True)
class PluginViewSpec:
    id: str
    title: str
    renderer: str
    view_mode: str = "snapshot"
    data_profile: str = "light"


@dataclass(frozen=True)
class PluginFileHandlerSpec:
    id: str
    label: str
    extensions: tuple[str, ...]
    view_id: str


@dataclass(frozen=True)
class PluginConfigFieldOption:
    value: str
    label: str


@dataclass(frozen=True)
class PluginConfigFieldSpec:
    key: str
    label: str
    field_type: str
    default: Any = None
    description: str = ""
    placeholder: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: tuple[PluginConfigFieldOption, ...] = ()


@dataclass(frozen=True)
class PluginConfigSectionSpec:
    id: str
    title: str = ""
    description: str = ""
    fields: tuple[PluginConfigFieldSpec, ...] = ()


@dataclass(frozen=True)
class PluginConfigSchemaSpec:
    title: str = ""
    sections: tuple[PluginConfigSectionSpec, ...] = ()


@dataclass(frozen=True)
class PluginActionSpec:
    id: str
    label: str
    target: str
    location: str
    icon: str = ""
    tooltip: str = ""
    variant: str = "default"
    disabled: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    host_action: dict[str, Any] | None = None
    confirm: dict[str, str] | None = None


@dataclass(frozen=True)
class PluginManifest:
    root: Path
    plugin_id: str
    schema_version: int
    name: str
    version: str
    description: str
    enabled: bool
    config: dict[str, Any]
    runtime: PluginRuntimeSpec
    views: tuple[PluginViewSpec, ...]
    file_handlers: tuple[PluginFileHandlerSpec, ...]
    config_schema: PluginConfigSchemaSpec | None = None
    catalog_actions: tuple[PluginActionSpec, ...] = ()


@dataclass(frozen=True)
class PluginFileResolution:
    plugin_id: str
    view_id: str
    handler_id: str
