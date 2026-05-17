from __future__ import annotations

from bot.debug.models import DebugProfile

from .base import DebugProvider


class DebugProviderRegistry:
    def __init__(self, providers: list[DebugProvider]):
        self._providers = list(providers)

    def providers(self) -> list[DebugProvider]:
        return list(self._providers)

    def require_provider(self, profile: DebugProfile) -> DebugProvider:
        provider_id = str(profile.provider_id or "").strip()
        for provider in self._providers:
            if provider_id and str(getattr(provider, "provider_id", "")).strip() == provider_id:
                return provider
        for provider in self._providers:
            if provider.can_handle(profile):
                return provider
        raise LookupError(f"未找到调试 provider: {provider_id or profile.kind or profile.language}")


def build_default_provider_registry(*, gdb_session_factory=None, dap_client_factory=None, adapter_launcher=None):
    from .cpp_gdb import CppGdbProvider
    from .godot import GodotProvider
    from .python_debugpy import PythonDebugpyProvider

    return DebugProviderRegistry(
        [
            CppGdbProvider(gdb_session_factory=gdb_session_factory),
            PythonDebugpyProvider(dap_client_factory=dap_client_factory, adapter_launcher=adapter_launcher),
            GodotProvider(),
        ]
    )
