"""Resolve a local Web session before handing a chat operation to the service."""

from __future__ import annotations

import functools
import inspect
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

from bot import config
from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile, UserSession
from bot.sessions import create_web_chat_session, get_web_chat_session, list_web_chat_sessions
from bot.web.api_common import WebApiError, get_profile_or_raise, resolve_session_bot_id


class ChatTarget(NamedTuple):
    profile: BotProfile
    agent: AgentProfile
    session: UserSession


_catalog_users: dict[tuple[int, str], int] = {}
_catalog_waiters: dict[tuple[int, str], list[Callable[[], None]]] = {}
_catalog_lock = threading.Lock()


def after_chat_catalog_change(manager: MultiBotManager, alias: str, callback: Callable[[], None]) -> None:
    key = (id(manager), alias.strip().lower())
    with _catalog_lock:
        if _catalog_users.get(key) == -1:
            _catalog_waiters.setdefault(key, []).append(callback)
            return
    callback()


@contextmanager
def reserve_chat_catalog(manager: MultiBotManager, alias: str, *, changing_owner: bool = False):
    """Session operations may overlap. A workspace move or rename requires exclusive ownership."""
    key = (id(manager), alias.strip().lower())
    with _catalog_lock:
        users = _catalog_users.get(key, 0)
        if users < 0 or (changing_owner and users):
            raise WebApiError(409, "chat_catalog_busy", "Bot 的会话或工作区正在变更，请稍后重试")
        _catalog_users[key] = -1 if changing_owner else users + 1
    try:
        yield
    finally:
        with _catalog_lock:
            if _catalog_users[key] <= 1:
                del _catalog_users[key]
            else:
                _catalog_users[key] -= 1
            waiters = _catalog_waiters.pop(key, ()) if changing_owner else ()
        for callback in waiters:
            callback()


def _local_profile(manager: MultiBotManager, alias: str) -> BotProfile:
    profile = get_profile_or_raise(manager, alias)
    if profile.remote_workspace or profile.archived:
        raise WebApiError(409, "local_chat_sessions_unavailable", "独立聊天会话仅支持本地工作区")
    return profile


def check_named_chat_owner(manager: MultiBotManager, alias: str, session: UserSession, workspace: str) -> None:
    profile = _local_profile(manager, alias)
    root = Path(profile.working_dir).resolve()
    if session.bot_alias != profile.alias or Path(workspace).resolve() != root or Path(session.working_dir).resolve() != root:
        raise WebApiError(409, "session_workdir_changed", "会话工作区已变化，请重新打开会话")


@contextmanager
def _use_chat_target(manager: MultiBotManager, alias: str, target: ChatTarget | None):
    if target is None or not target.session.web_session_id:
        yield
        return
    with reserve_chat_catalog(manager, alias):
        check_named_chat_owner(manager, alias, target.session, target.profile.working_dir)
        yield


def with_chat_target(function):
    """Keep a resolved named chat bound to its workspace until its operation completes."""
    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def async_call(manager, alias, *args, **kwargs):
            with _use_chat_target(manager, alias, kwargs.get("target")):
                return await function(manager, alias, *args, **kwargs)
        return async_call

    @functools.wraps(function)
    def call(manager, alias, *args, **kwargs):
        with _use_chat_target(manager, alias, kwargs.get("target")):
            return function(manager, alias, *args, **kwargs)
    return call


def list_chat_sessions(manager: MultiBotManager, alias: str, user_id: int) -> dict:
    with reserve_chat_catalog(manager, alias):
        profile = get_profile_or_raise(manager, alias)
        enabled = not (profile.remote_workspace or profile.archived)
        items = [{"id": "main", "title": "主会话"}]
        if enabled:
            items.extend(list_web_chat_sessions(resolve_session_bot_id(manager, alias), alias, user_id))
    return {"enabled": bool(enabled), "items": items}


def create_chat_session(manager: MultiBotManager, alias: str, user_id: int, title: str) -> dict:
    if config.UPDATE_DRAINING or config.UPDATE_REQUESTED:
        raise WebApiError(503, "update_restarting", "更新正在交接，请等待宿主重新启动")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
        raise WebApiError(400, "invalid_session_title", "会话名称须为 1 至 80 个字符")
    with reserve_chat_catalog(manager, alias):
        profile = _local_profile(manager, alias)
        session = create_web_chat_session(
            resolve_session_bot_id(manager, alias), alias, user_id, profile.working_dir, title.strip(),
        )
    return {"id": session.web_session_id, "title": session.web_session_title}


def resolve_named_chat_target(
    manager: MultiBotManager, alias: str, user_id: int, session_id: str,
) -> ChatTarget:
    with reserve_chat_catalog(manager, alias):
        profile = _local_profile(manager, alias)
        try:
            session = get_web_chat_session(
                resolve_session_bot_id(manager, alias), alias, user_id, profile.working_dir, session_id,
            )
        except KeyError:
            raise WebApiError(404, "session_not_found", "聊天会话不存在") from None
        if Path(session.working_dir).resolve() != Path(profile.working_dir).resolve():
            raise WebApiError(409, "session_workdir_changed", "会话工作目录已变化，请在 Bot 管理中确认工作区")
        # Named sessions run ordinary text turns, including on a Bot with a cluster in its default chat.
        profile = replace(profile, cluster=replace(profile.cluster, enabled=False), agents=[])
        return ChatTarget(profile, profile.get_agent("main"), session)
