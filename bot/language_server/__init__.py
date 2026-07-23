"""语言服务器发现与托管安装。"""

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
    "LanguageServerInstallError",
    "LanguageServerInstaller",
    "LanguageServerRuntimeKey",
    "LanguageServerRuntimeManager",
    "LanguageServerUnavailableError",
    "LanguageServerManifest",
    "LanguageServerManifestError",
    "current_platform_key",
    "load_language_server_manifest",
]
