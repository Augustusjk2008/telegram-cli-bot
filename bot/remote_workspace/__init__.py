"""Authenticated, pooled SSH workspaces."""

from .transport import (
    RemoteWorkspaceError,
    RemoteWorkspaceService,
    get_remote_workspace_service,
    normalize_remote_workspace,
)

__all__ = [
    "RemoteWorkspaceError",
    "RemoteWorkspaceService",
    "get_remote_workspace_service",
    "normalize_remote_workspace",
]
