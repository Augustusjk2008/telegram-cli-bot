"""原生 agent 运行时封装。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

NATIVE_AGENT_PROVIDER = "native_agent"

if TYPE_CHECKING:
    from .service import NativeAgentService


def get_native_agent_service() -> "NativeAgentService":
    from .service import get_native_agent_service as _get_native_agent_service

    return _get_native_agent_service()


def normalize_execution_mode(*args: Any, **kwargs: Any) -> str:
    from .service import normalize_execution_mode as _normalize_execution_mode

    return _normalize_execution_mode(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "NativeAgentService":
        from .service import NativeAgentService

        return NativeAgentService
    raise AttributeError(name)


__all__ = [
    "NATIVE_AGENT_PROVIDER",
    "NativeAgentService",
    "get_native_agent_service",
    "normalize_execution_mode",
]
