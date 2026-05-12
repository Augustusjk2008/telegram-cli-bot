from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any

from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.state import attach_assistant_persist_hook, restore_assistant_runtime_state
from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile, UserSession
from bot.sessions import align_session_paths, get_or_create_session
from bot.web.auth_store import GUEST_CAPABILITIES, MEMBER_CAPABILITIES


class WebApiError(Exception):
    """Web API business error."""

    def __init__(self, status: int, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}


@dataclass
class AuthContext:
    """Web request auth context."""

    user_id: int
    token_used: bool
    account_id: str = "legacy-default"
    username: str = "legacy"
    role: str = "member"
    capabilities: set[str] = field(default_factory=lambda: set(MEMBER_CAPABILITIES))
    allowed_bot_aliases: set[str] = field(default_factory=set)
    owned_bot_aliases: set[str] = field(default_factory=set)
    is_local_admin: bool = False

    def with_capabilities(self, capabilities: frozenset[str] | set[str]) -> "AuthContext":
        return AuthContext(
            user_id=self.user_id,
            token_used=self.token_used,
            account_id=self.account_id,
            username=self.username,
            role=self.role,
            capabilities=set(capabilities),
            allowed_bot_aliases=set(self.allowed_bot_aliases),
            owned_bot_aliases=set(self.owned_bot_aliases),
            is_local_admin=self.is_local_admin,
        )


def _raise(status: int, code: str, message: str, data: dict[str, Any] | None = None):
    raise WebApiError(status=status, code=code, message=message, data=data)


def _require_capability(auth: AuthContext, capability: str) -> None:
    if capability in auth.capabilities:
        return
    _raise(403, "forbidden", "当前账号无权限执行此操作")


def bot_readonly_auth(auth: AuthContext) -> AuthContext:
    return auth.with_capabilities(GUEST_CAPABILITIES)


def get_profile_or_raise(manager: MultiBotManager, alias: str) -> BotProfile:
    alias = (alias or "").strip().lower()
    if alias == manager.main_profile.alias:
        return manager.main_profile
    profile = manager.managed_profiles.get(alias)
    if profile is None:
        _raise(404, "bot_not_found", f"未找到别名为 `{alias}` 的 Bot")
    return profile


def resolve_session_bot_id(manager: MultiBotManager, alias: str) -> int:
    app = manager.applications.get(alias)
    if app:
        bot_id = app.bot_data.get("bot_id")
        if isinstance(bot_id, int):
            return bot_id
    return -int(zlib.adler32(f"web:{alias}".encode("utf-8")))


def get_session_for_alias(manager: MultiBotManager, alias: str, user_id: int) -> UserSession:
    profile = get_profile_or_raise(manager, alias)
    session = get_or_create_session(
        bot_id=resolve_session_bot_id(manager, alias),
        bot_alias=alias,
        user_id=user_id,
        default_working_dir=profile.working_dir,
        load_persisted_state=profile.bot_mode != "assistant",
    )

    if profile.bot_mode == "assistant" and session.persist_hook is None:
        home = bootstrap_assistant_home(profile.working_dir)
        attach_assistant_persist_hook(session, home, user_id)
        restore_assistant_runtime_state(session, home, user_id)

    return align_session_paths(session, profile.working_dir, profile.bot_mode)


def get_chat_session_for_alias(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    agent_id: str = "main",
) -> tuple[BotProfile, AgentProfile, UserSession]:
    profile = get_profile_or_raise(manager, alias)
    normalized_agent_id = str(agent_id or "main").strip().lower() or "main"
    try:
        agent = profile.get_agent(normalized_agent_id)
    except KeyError:
        _raise(404, "agent_not_found", "未找到 agent")
    if normalized_agent_id == "main":
        return profile, agent, get_session_for_alias(manager, alias, user_id)
    if normalized_agent_id != "main" and profile.bot_mode != "cli":
        _raise(400, "agent_not_supported", "仅 CLI Bot 支持子 agent")
    session = get_or_create_session(
        bot_id=resolve_session_bot_id(manager, alias),
        bot_alias=alias,
        user_id=user_id,
        default_working_dir=profile.working_dir,
        load_persisted_state=profile.bot_mode != "assistant",
        agent_id=agent.id,
    )
    return profile, agent, align_session_paths(session, profile.working_dir, profile.bot_mode)
