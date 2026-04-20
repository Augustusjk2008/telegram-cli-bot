from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_CHAT_ATTACHMENT_ALIAS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH = Path(".tcb") / "state" / "chat.sqlite"


def _is_windows_platform() -> bool:
    return os.name == "nt"


def get_tcb_home_root() -> Path:
    return Path.home() / ".tcb"


def _normalize_chat_attachment_alias(alias: str) -> str:
    candidate = _CHAT_ATTACHMENT_ALIAS_RE.sub("-", str(alias or "").strip()).strip(".-_")
    return candidate or "main"


def get_chat_attachments_dir(alias: str, user_id: int) -> Path:
    return get_tcb_home_root() / "chat-attachments" / _normalize_chat_attachment_alias(alias) / str(user_id)


def get_legacy_project_chat_db_path(working_dir: str | Path) -> Path:
    return Path(str(working_dir)).expanduser() / _LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH


def normalize_workspace_dir(working_dir: str | Path) -> str:
    normalized = os.path.expanduser(str(working_dir))
    normalized = os.path.abspath(normalized)
    normalized = os.path.normpath(normalized)
    if _is_windows_platform():
        normalized = os.path.normcase(normalized)
    return normalized


def get_chat_workspace_key(working_dir: str | Path) -> str:
    normalized = normalize_workspace_dir(working_dir)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_chat_workspace_dir(working_dir: str | Path) -> Path:
    return get_tcb_home_root() / "chat-history" / "workspaces" / get_chat_workspace_key(working_dir)


def get_chat_history_db_path(working_dir: str | Path) -> Path:
    return get_chat_workspace_dir(working_dir) / "chat.sqlite"


def get_chat_workspace_metadata_path(working_dir: str | Path) -> Path:
    return get_chat_workspace_dir(working_dir) / "workspace.json"
