from __future__ import annotations

from pathlib import Path

from .models import PluginConfig

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = PLUGIN_ROOT / "vendor" / "graphviz"
WINDOWS_RUNTIME_DIR = VENDOR_ROOT / "win-x64"
GRAPHVIZ_RUNTIME_VERSION = "16.1.0"


def vendor_dot_path() -> Path:
    return WINDOWS_RUNTIME_DIR / "bin" / "dot.exe"


def resolve_dot_path(config: PluginConfig) -> str:
    vendor_dot = vendor_dot_path()
    if config.bundled_graphviz_enabled and vendor_dot.is_file():
        return str(vendor_dot)
    if config.dot_path and config.dot_path != "dot":
        return config.dot_path
    return "dot"


def graphviz_status(config: PluginConfig) -> dict[str, object]:
    vendor_dot = vendor_dot_path()
    return {
        "vendorInstalled": vendor_dot.is_file(),
        "vendorDotPath": str(vendor_dot),
        "resolvedDotPath": resolve_dot_path(config),
        "bundledEnabled": config.bundled_graphviz_enabled,
        "installAvailable": True,
        "version": GRAPHVIZ_RUNTIME_VERSION if vendor_dot.is_file() else "",
    }
