"""Replayable steps for a managed Bot's chat identity change."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bot import session_store, sessions
from bot.web.chat_favorite_store import ChatFavoriteStore
from bot.web.chat_store import ChatStore

if TYPE_CHECKING:
    from bot.manager import MultiBotManager
    from bot.models import BotProfile


class ChatRenamePending(RuntimeError):
    """The Bot's durable rename intent still requires recovery."""


def rename_default_permissions(old_alias: str, new_alias: str) -> None:
    from bot.runtime_paths import get_permissions_root
    from bot.web.permission_store import BotPermissionStore

    store = BotPermissionStore(get_permissions_root(), legacy_path=Path(__file__).resolve().parents[1] / ".web_permissions.json")
    store.rename_bot(old_alias, new_alias)


def has_legacy_collision(manager: MultiBotManager, profile: BotProfile, new_alias: str) -> bool:
    from bot.web.api_common import resolve_session_bot_id

    owner_ids = {resolve_session_bot_id(manager, alias) for alias in (profile.alias, new_alias)}
    other_aliases = set(manager.bot_workspaces())
    other_aliases.update(
        p.pending_rename_to for p in manager.managed_profiles.values() if p is not profile and p.pending_rename_to
    )
    other_aliases.difference_update((profile.alias, new_alias))
    return any(resolve_session_bot_id(manager, alias) in owner_ids for alias in other_aliases)


def migrate_chat_ownership(manager: MultiBotManager, profile: BotProfile, new_alias: str) -> None:
    from bot.scheduler import notify_bot_renamed
    from bot.web.api_common import resolve_session_bot_id

    old_alias = profile.alias
    old_id = resolve_session_bot_id(manager, old_alias)
    new_id = resolve_session_bot_id(manager, new_alias)
    aliases = {"old_alias": old_alias, "new_alias": new_alias}

    # A legacy snapshot records only the numeric Bot id. On collision its owner
    # is ambiguous, while named snapshots and history carry an explicit alias.
    session_store.rename_bot_sessions(old_id, new_id, **aliases, include_legacy=not profile.pending_rename_skip_legacy)
    sessions.rekey_bot_sessions(old_id, new_id, **aliases, include_legacy=not profile.pending_rename_skip_legacy)
    ChatStore(Path(profile.working_dir)).rename_bot_identity(
        old_bot_id=old_id, new_bot_id=new_id, **aliases,
        include_unlabeled_legacy=not profile.pending_rename_skip_legacy,
    )
    ChatFavoriteStore(profile.working_dir).rename_bot(old_id, new_id, old_alias, new_alias)
    manager.rename_bot_permissions(old_alias, new_alias)
    notify_bot_renamed(old_alias, new_alias)
