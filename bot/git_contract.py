"""Shared Git capability contract."""

from __future__ import annotations

from typing import Any


GIT_CAPABILITY_NAMES: tuple[str, ...] = (
    "tree_status",
    "commit_graph",
    "branches",
    "branch_mutation",
    "discard",
    "stash",
    "identity",
    "fetch",
    "pull",
    "push",
    "commit_message_generation",
    "smart_commit",
)

GIT_CAPABILITIES_REQUIRING_CONFIRMATION = frozenset(
    {
        "discard",
        "branch_mutation",
        "stash",
        "pull",
        "push",
        "smart_commit",
    }
)


def build_git_capabilities(*, available: bool, reason: str = "") -> dict[str, Any]:
    """Build the stable capability matrix returned by local and remote Git APIs."""
    normalized_available = bool(available)
    normalized_reason = "" if normalized_available else str(reason or "")
    return {
        "capabilities": {
            name: {
                "available": normalized_available,
                "reason": normalized_reason,
                "requires_confirmation": name in GIT_CAPABILITIES_REQUIRING_CONFIRMATION,
            }
            for name in GIT_CAPABILITY_NAMES
        },
    }
