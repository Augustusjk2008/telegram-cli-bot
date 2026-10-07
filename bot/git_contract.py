"""Shared Git capability contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


GIT_CAPABILITY_NAMES: tuple[str, ...] = (
    "tree_status",
    "commit_graph",
    "branches",
    "branch_mutation",
    "discard",
    "stash",
    "stash_create",
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
        "stash_create",
        "pull",
        "push",
        "smart_commit",
    }
)


def build_git_capabilities(*, available: bool | Mapping[str, bool], reason: str = "") -> dict[str, Any]:
    """Build the stable capability matrix returned by local and remote Git APIs."""
    availability = {
        name: bool(available.get(name, False) if isinstance(available, Mapping) else available)
        for name in GIT_CAPABILITY_NAMES
    }
    return {
        "capabilities": {
            name: {
                "available": availability[name],
                "reason": "" if availability[name] else str(reason or ""),
                "requires_confirmation": name in GIT_CAPABILITIES_REQUIRING_CONFIRMATION,
            }
            for name in GIT_CAPABILITY_NAMES
        },
    }
