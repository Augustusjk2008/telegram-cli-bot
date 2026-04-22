from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginRuntimeSpec:
    runtime_type: str
    entry: str
    protocol: str


@dataclass(frozen=True)
class PluginViewSpec:
    id: str
    title: str
    renderer: str


@dataclass(frozen=True)
class PluginFileHandlerSpec:
    id: str
    label: str
    extensions: tuple[str, ...]
    view_id: str


@dataclass(frozen=True)
class PluginManifest:
    root: Path
    plugin_id: str
    name: str
    version: str
    description: str
    runtime: PluginRuntimeSpec
    views: tuple[PluginViewSpec, ...]
    file_handlers: tuple[PluginFileHandlerSpec, ...]


@dataclass(frozen=True)
class PluginFileResolution:
    plugin_id: str
    view_id: str
    handler_id: str
