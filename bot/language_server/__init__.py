"""语言服务器发现与托管安装。"""

from .clangd import ClangdProvider, discover_clangd_project_config, discover_compile_commands
from .catalog import LanguageServerCatalog
from .installer import LanguageServerInstallError, LanguageServerInstaller
from .manager import (
    LanguageServerRuntimeKey,
    LanguageServerRuntimeManager,
    LanguageServerUnavailableError,
)
from .manifest import (
    LanguageServerManifest,
    LanguageServerManifestError,
    current_platform_key,
    load_language_server_manifest,
)

__all__ = [
    "LanguageServerCatalog",
    "ClangdProvider",
    "LanguageServerInstallError",
    "LanguageServerInstaller",
    "LanguageServerRuntimeKey",
    "LanguageServerRuntimeManager",
    "LanguageServerUnavailableError",
    "LanguageServerManifest",
    "LanguageServerManifestError",
    "current_platform_key",
    "load_language_server_manifest",
    "discover_clangd_project_config",
    "discover_compile_commands",
]
