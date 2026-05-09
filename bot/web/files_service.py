from __future__ import annotations

import ntpath
import os
import re
from pathlib import Path
from typing import Any

from bot.manager import MultiBotManager
from bot.models import UserSession
from bot.web.api_common import _raise, get_session_for_alias

_WINDOWS_DRIVES_VIRTUAL_ROOT = "::windows-drives::"
_WINDOWS_DRIVES_DISPLAY_ROOT = "盘符列表"
_WINDOWS_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]*$")
_WINDOWS_STYLE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def get_browser_directory(session: UserSession) -> str:
    if isinstance(session.browse_dir, str) and session.browse_dir.strip():
        return session.browse_dir
    return session.working_dir


def is_windows_drives_virtual_root(path: str) -> bool:
    return str(path or "").strip() == _WINDOWS_DRIVES_VIRTUAL_ROOT


def is_windows_drive_root(path: str) -> bool:
    return bool(_WINDOWS_DRIVE_ROOT_RE.fullmatch(str(path or "").strip()))


def looks_like_windows_path(path: str) -> bool:
    value = str(path or "").strip()
    return bool(_WINDOWS_STYLE_PATH_RE.match(value) or is_windows_drive_root(value))


def normalize_windows_drive_root(path: str) -> str:
    value = str(path or "").strip().replace("/", "\\")
    if not is_windows_drive_root(value):
        _raise(400, "invalid_drive_root", f"无效盘符路径: {path}")
    return f"{value[0].upper()}:\\"


def display_browser_directory(path: str) -> str:
    if is_windows_drives_virtual_root(path):
        return _WINDOWS_DRIVES_DISPLAY_ROOT
    return path


def build_directory_listing_response(
    working_dir: str,
    entries: list[dict[str, Any]],
    *,
    is_virtual_root: bool = False,
) -> dict[str, Any]:
    return {
        "working_dir": display_browser_directory(working_dir),
        "entries": entries,
        "is_virtual_root": is_virtual_root,
    }


def list_windows_drive_entries() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for drive_code in range(ord("A"), ord("Z") + 1):
        drive_root = f"{chr(drive_code)}:\\"
        if os.path.isdir(drive_root):
            entries.append({"name": drive_root, "is_dir": True})
    return build_directory_listing_response(
        _WINDOWS_DRIVES_VIRTUAL_ROOT,
        entries,
        is_virtual_root=True,
    )


def require_real_browser_directory(browser_dir: str) -> str:
    if is_windows_drives_virtual_root(browser_dir):
        _raise(409, "virtual_directory_unsupported", "当前视图仅用于切换盘符，不能直接执行文件操作")
    return browser_dir


def resolve_browser_target_path(current_dir: str, new_path: str) -> str:
    path = str(new_path or "").strip()
    if not path:
        _raise(400, "missing_path", "路径不能为空")

    if is_windows_drives_virtual_root(current_dir):
        if path in {"..", "."}:
            return _WINDOWS_DRIVES_VIRTUAL_ROOT
        return normalize_windows_drive_root(path)

    if is_windows_drive_root(current_dir) and path == "..":
        return _WINDOWS_DRIVES_VIRTUAL_ROOT

    if looks_like_windows_path(current_dir) or looks_like_windows_path(path):
        candidate = path
        if not ntpath.isabs(candidate):
            candidate = ntpath.join(current_dir, candidate)
        return ntpath.abspath(ntpath.expanduser(candidate))

    candidate = path
    if not os.path.isabs(candidate):
        candidate = os.path.join(current_dir, candidate)
    return os.path.abspath(os.path.expanduser(candidate))


def list_directory_entries(working_dir: str) -> dict[str, Any]:
    entries = []
    for entry in sorted(os.scandir(working_dir), key=lambda item: (not item.is_dir(), item.name.lower())):
        item = {
            "name": entry.name,
            "is_dir": entry.is_dir(),
        }
        if entry.is_file():
            item["size"] = entry.stat().st_size
        entries.append(item)
    return build_directory_listing_response(working_dir, entries)


def list_directory_entry_items(working_dir: str) -> list[dict[str, Any]]:
    return list_directory_entries(working_dir)["entries"]


def ensure_path_within_base_dir(base_dir: str, target_dir: str) -> None:
    try:
        base_path = Path(base_dir).resolve()
        target_path = Path(target_dir).resolve()
        target_path.relative_to(base_path)
    except ValueError:
        _raise(403, "forbidden_path", "当前账号无权访问该目录")


def get_directory_listing(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    path: str | None = None,
    *,
    base_dir: str | None = None,
    restrict_to_base_dir: bool = False,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = str(base_dir or get_browser_directory(session))
    target_dir = browser_dir
    if path is not None and str(path).strip():
        target_dir = resolve_browser_target_path(browser_dir, str(path))
    if restrict_to_base_dir and base_dir:
        ensure_path_within_base_dir(base_dir, target_dir)
    if is_windows_drives_virtual_root(target_dir):
        return list_windows_drive_entries()
    try:
        return list_directory_entries(target_dir)
    except FileNotFoundError:
        _raise(404, "working_dir_not_found", f"目录不存在: {target_dir}")
    except Exception as exc:
        _raise(500, "list_dir_failed", str(exc))


def reveal_directory_tree(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    path: str,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    root = Path(require_real_browser_directory(get_browser_directory(session))).expanduser().resolve()
    raw_path = Path(str(path or "").strip())
    if not str(raw_path):
        _raise(400, "missing_path", "路径不能为空")
    target = (raw_path if raw_path.is_absolute() else root / raw_path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _raise(403, "forbidden_path", "当前账号无权访问该目录")
    if not target.exists():
        _raise(404, "path_not_found", "文件或文件夹不存在")

    highlight_path = target.relative_to(root).as_posix()
    branch_target = target if target.is_dir() else target.parent
    branch_paths = [""]
    if branch_target != root:
        relative_parts = branch_target.relative_to(root).parts
        branch_paths.extend(
            "/".join(relative_parts[:index])
            for index in range(1, len(relative_parts) + 1)
        )

    branches: dict[str, list[dict[str, Any]]] = {}
    for branch_path in branch_paths:
        branch_dir = root / Path(*branch_path.split("/")) if branch_path else root
        branches[branch_path] = list_directory_entry_items(str(branch_dir))

    return {
        "root_path": str(root),
        "highlight_path": highlight_path,
        "expanded_paths": [item for item in branch_paths if item],
        "branches": branches,
    }


def get_working_directory(manager: MultiBotManager, alias: str, user_id: int) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    return {"working_dir": session.working_dir}


def change_working_directory(manager: MultiBotManager, alias: str, user_id: int, new_path: str) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    current_dir = get_browser_directory(session)
    path = resolve_browser_target_path(current_dir, new_path)
    if not is_windows_drives_virtual_root(path) and not os.path.isdir(path):
        _raise(404, "dir_not_found", f"目录不存在: {path}")

    session.browse_dir = path
    session.persist()
    return {
        "working_dir": display_browser_directory(session.browse_dir),
        "is_virtual_root": is_windows_drives_virtual_root(session.browse_dir),
    }

