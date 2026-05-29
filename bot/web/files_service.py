from __future__ import annotations

import base64
import ntpath
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import BotProfile, UserSession
from bot.runtime_paths import get_chat_attachments_dir
from bot.web import workspace_index_service
from bot.web.api_common import _raise, get_profile_or_raise, get_session_for_alias
from bot.web.text_encoding import UnsupportedTextEncoding, read_text_file, read_text_file_head, write_text_file

_WINDOWS_DRIVES_VIRTUAL_ROOT = "::windows-drives::"
_WINDOWS_DRIVES_DISPLAY_ROOT = "盘符列表"
_WINDOWS_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]*$")
_WINDOWS_STYLE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
UPLOAD_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
_RASTER_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


async def _write_limited_chunks(target_path: str | Path, chunks: AsyncIterator[bytes], *, replace_existing: bool) -> int:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile("wb", dir=str(target.parent), prefix=f".{target.name}.", delete=False) as handle:
            temp_name = handle.name
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if total > UPLOAD_MAX_FILE_SIZE_BYTES:
                    _raise(413, "file_too_large", msg("upload", "file_too_large"))
                handle.write(chunk)
        if total <= 0:
            _raise(400, "empty_file", "文件内容不能为空")
        if replace_existing:
            os.replace(temp_name, target)
        else:
            Path(temp_name).replace(target)
        temp_name = ""
        return total
    finally:
        if temp_name:
            try:
                os.remove(temp_name)
            except OSError:
                pass


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


def resolve_safe_path(base_dir: str, filename: str) -> str:
    candidate = str(filename or "").strip()
    if not candidate or candidate == "." or "\x00" in candidate:
        _raise(400, "unsafe_path", "文件路径不安全")
    if os.path.isabs(candidate):
        _raise(400, "unsafe_path", "不允许访问绝对路径")

    resolved_base = os.path.realpath(base_dir)
    resolved_path = os.path.realpath(os.path.join(resolved_base, os.path.expanduser(candidate)))

    try:
        if os.path.commonpath([resolved_base, resolved_path]) != resolved_base:
            _raise(400, "unsafe_path", "文件路径不安全")
    except ValueError:
        _raise(400, "unsafe_path", "文件路径不安全")

    return resolved_path


def resolve_safe_write_path(base_dir: str, path: str) -> str:
    candidate = str(path or "").strip()
    if not candidate or candidate == "." or "\x00" in candidate:
        _raise(400, "unsafe_write_path", "文件路径不安全")
    if os.path.isabs(candidate):
        _raise(400, "unsafe_write_path", "不允许写入绝对路径")

    resolved_base = os.path.realpath(base_dir)
    resolved_path = os.path.realpath(os.path.join(resolved_base, os.path.expanduser(candidate)))

    try:
        if os.path.commonpath([resolved_base, resolved_path]) != resolved_base:
            _raise(400, "unsafe_write_path", "文件路径不安全")
    except ValueError:
        _raise(400, "unsafe_write_path", "文件路径不安全")

    return resolved_path


def ensure_editable_text_file(path: str, encoding: str | None = None) -> str:
    try:
        return read_text_file(path, encoding).encoding
    except UnsupportedTextEncoding:
        _raise(400, "not_text_file", "文件不是可编辑的文本文件")


def write_text_file_atomically(path: str, content: str, encoding: str | None = None) -> None:
    directory = os.path.dirname(path)
    temporary_path = os.path.join(directory, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    try:
        write_text_file(temporary_path, content, encoding)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def stat_file_version(path: str) -> int:
    return os.stat(path).st_mtime_ns


def ensure_file_version_advanced(path: str, previous_mtime_ns: int) -> int:
    current_mtime_ns = stat_file_version(path)
    if current_mtime_ns > previous_mtime_ns:
        return current_mtime_ns

    for step_ns in (
        100,
        1_000,
        10_000,
        100_000,
        1_000_000,
        10_000_000,
        100_000_000,
        1_000_000_000,
        2_000_000_000,
    ):
        adjusted_mtime_ns = previous_mtime_ns + step_ns
        os.utime(path, ns=(adjusted_mtime_ns, adjusted_mtime_ns))
        current_mtime_ns = stat_file_version(path)
        if current_mtime_ns > previous_mtime_ns:
            return current_mtime_ns

    _raise(500, "write_file_failed", "文件版本更新失败")


def resolve_new_directory_path(base_dir: str, name: str) -> tuple[str, str]:
    candidate = str(name or "").strip()
    if not candidate or candidate in {".", ".."} or "\x00" in candidate:
        _raise(400, "invalid_directory_name", "文件夹名称不合法")

    path_separators = {os.path.sep}
    if os.path.altsep:
        path_separators.add(os.path.altsep)
    if any(separator and separator in candidate for separator in path_separators):
        _raise(400, "invalid_directory_name", "文件夹名称不能包含路径分隔符")

    return candidate, os.path.abspath(os.path.join(base_dir, candidate))


def validate_text_filename(name: str) -> str:
    candidate = str(name or "").strip()
    if not candidate or candidate in {".", ".."} or "\x00" in candidate:
        _raise(400, "invalid_filename", "文件名不合法")

    path_separators = {os.path.sep}
    if os.path.altsep:
        path_separators.add(os.path.altsep)
    if any(separator and separator in candidate for separator in path_separators):
        _raise(400, "invalid_filename", "文件名不能包含路径分隔符")

    return candidate


def resolve_action_parent_dir(session: UserSession, parent_path: str | None = None) -> str:
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    candidate = str(parent_path or "").strip()
    if not candidate:
        return browser_dir

    resolved_base = os.path.realpath(browser_dir)
    if os.path.isabs(candidate):
        resolved_path = os.path.realpath(os.path.expanduser(candidate))
    else:
        resolved_path = os.path.realpath(os.path.join(resolved_base, os.path.expanduser(candidate)))

    try:
        if os.path.commonpath([resolved_base, resolved_path]) != resolved_base:
            _raise(400, "unsafe_write_path", "文件路径不安全")
    except ValueError:
        _raise(400, "unsafe_write_path", "文件路径不安全")

    if not os.path.isdir(resolved_path):
        _raise(404, "dir_not_found", f"目录不存在: {resolved_path}")
    return resolved_path


def ensure_file_browser_supported(manager: MultiBotManager, alias: str) -> BotProfile:
    profile = get_profile_or_raise(manager, alias)
    if profile.bot_mode not in ("cli", "assistant"):
        _raise(409, "unsupported_bot_mode", f"Bot `{alias}` 当前模式为 `{profile.bot_mode}`，不支持文件操作")
    return profile


def sanitize_uploaded_filename(filename: str) -> str:
    candidate = os.path.basename(ntpath.basename(str(filename or "").strip()))
    if not candidate or candidate in {".", ".."} or "\x00" in candidate:
        _raise(400, "unsafe_filename", "文件名不合法")
    return candidate


def build_chat_attachment_dir(alias: str, user_id: int) -> str:
    return str(get_chat_attachments_dir(alias, user_id))


def resolve_unique_upload_path(base_dir: str, filename: str) -> tuple[str, str]:
    safe_name = sanitize_uploaded_filename(filename)
    stem, suffix = os.path.splitext(safe_name)
    resolved_name = safe_name
    resolved_path = os.path.join(base_dir, resolved_name)
    counter = 1
    while os.path.exists(resolved_path):
        resolved_name = f"{stem}-{counter}{suffix}"
        resolved_path = os.path.join(base_dir, resolved_name)
        counter += 1
    return resolved_path, resolved_name


def resolve_chat_attachment_path(alias: str, user_id: int, saved_path: str) -> Path:
    candidate = Path(str(saved_path or "").strip())
    if not str(candidate):
        _raise(400, "missing_saved_path", "附件路径不能为空")
    if not candidate.is_absolute():
        _raise(400, "invalid_saved_path", "附件路径必须是绝对路径")

    attachment_dir = get_chat_attachments_dir(alias, user_id).resolve()
    resolved_candidate = candidate.expanduser().resolve(strict=False)
    try:
        resolved_candidate.relative_to(attachment_dir)
    except ValueError:
        _raise(403, "attachment_delete_forbidden", "只能删除当前 Bot 当前用户上传的附件")
    return resolved_candidate


def invalidate_workspace_indexes(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    *paths: str | os.PathLike[str] | None,
) -> None:
    api_service = sys.modules.get("bot.web.api_service")
    hook = getattr(api_service, "_invalidate_workspace_indexes", None) if api_service is not None else None
    if callable(hook) and hook is not invalidate_workspace_indexes:
        hook(manager, alias, user_id, *paths)
        return

    session = get_session_for_alias(manager, alias, user_id)
    candidates = [session.working_dir, get_browser_directory(session), *paths]
    for candidate in candidates:
        if candidate:
            workspace_index_service.invalidate_workspace_index(candidate)


def create_directory(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    name: str,
    parent_path: str | None = None,
) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    parent_dir = resolve_action_parent_dir(session, parent_path)
    directory_name, target_path = resolve_new_directory_path(parent_dir, name)

    if os.path.exists(target_path):
        _raise(409, "path_exists", "目标已存在")

    try:
        os.mkdir(target_path)
    except FileExistsError:
        _raise(409, "path_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "create_directory_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "name": directory_name,
        "created_path": target_path,
        "working_dir": browser_dir,
    }


def create_text_file(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    content: str = "",
    parent_path: str | None = None,
) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    parent_dir = resolve_action_parent_dir(session, parent_path)
    file_name = validate_text_filename(filename)
    target_path = os.path.abspath(os.path.join(parent_dir, file_name))

    if os.path.exists(target_path):
        _raise(409, "file_already_exists", "文件已存在")

    try:
        with open(target_path, "x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except FileExistsError:
        _raise(409, "file_already_exists", "文件已存在")
    except Exception as exc:
        _raise(500, "create_file_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "path": os.path.relpath(target_path, browser_dir).replace("\\", "/"),
        "file_size_bytes": os.path.getsize(target_path),
        "last_modified_ns": stat_file_version(target_path),
    }


def rename_path(manager: MultiBotManager, alias: str, user_id: int, path: str, new_name: str) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    source_rel = str(path or "").strip().replace("\\", "/")
    if not source_rel:
        _raise(400, "invalid_rename_path", "缺少待重命名路径")

    source_path = resolve_safe_write_path(browser_dir, source_rel)
    target_name = validate_text_filename(new_name)

    if not os.path.isfile(source_path):
        _raise(404, "file_not_found", "文件不存在")

    target_path = os.path.abspath(os.path.join(os.path.dirname(source_path), target_name))
    if os.path.exists(target_path):
        _raise(409, "rename_target_exists", "目标已存在")

    try:
        os.rename(source_path, target_path)
    except FileExistsError:
        _raise(409, "rename_target_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "rename_path_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    target_relative_path = os.path.relpath(target_path, browser_dir).replace("\\", "/")
    return {
        "old_path": source_rel,
        "path": target_relative_path,
    }


def build_copy_filename(source_name: str, directory: str) -> str:
    stem, suffix = os.path.splitext(source_name)
    candidate = f"{stem} 副本{suffix}"
    counter = 2
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem} 副本 {counter}{suffix}"
        counter += 1
    return candidate


def copy_path(manager: MultiBotManager, alias: str, user_id: int, path: str) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    source_rel = str(path or "").strip().replace("\\", "/")
    if not source_rel:
        _raise(400, "invalid_copy_path", "缺少待复制路径")

    source_path = resolve_safe_write_path(browser_dir, source_rel)
    if not os.path.isfile(source_path):
        _raise(404, "file_not_found", "文件不存在")

    target_name = build_copy_filename(os.path.basename(source_path), os.path.dirname(source_path))
    target_path = os.path.abspath(os.path.join(os.path.dirname(source_path), target_name))

    try:
        shutil.copy2(source_path, target_path)
    except FileExistsError:
        _raise(409, "copy_target_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "copy_path_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    target_relative_path = os.path.relpath(target_path, browser_dir).replace("\\", "/")
    return {
        "source_path": source_rel,
        "path": target_relative_path,
        "file_size_bytes": os.path.getsize(target_path),
        "last_modified_ns": stat_file_version(target_path),
    }


def move_path(manager: MultiBotManager, alias: str, user_id: int, path: str, target_parent_path: str) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    source_rel = str(path or "").strip().replace("\\", "/")
    if not source_rel:
        _raise(400, "invalid_move_path", "缺少待移动路径")

    source_path = resolve_safe_write_path(browser_dir, source_rel)
    if not os.path.exists(source_path):
        _raise(404, "path_not_found", "路径不存在")

    target_dir = resolve_action_parent_dir(session, target_parent_path)
    target_path = os.path.abspath(os.path.join(target_dir, os.path.basename(source_path)))
    source_abs = os.path.abspath(source_path)

    if os.path.isdir(source_abs):
        try:
            if os.path.commonpath([source_abs, os.path.abspath(target_dir)]) == source_abs:
                _raise(400, "invalid_move_target", "不能将文件夹移动到自身或其子文件夹中")
        except ValueError:
            _raise(400, "invalid_move_target", "不能将文件夹移动到自身或其子文件夹中")

    if os.path.normcase(source_abs) == os.path.normcase(target_path):
        _raise(400, "same_move_target", "路径已在目标文件夹中")
    if os.path.exists(target_path):
        _raise(409, "move_target_exists", "目标已存在")

    try:
        shutil.move(source_path, target_path)
    except FileExistsError:
        _raise(409, "move_target_exists", "目标已存在")
    except Exception as exc:
        _raise(500, "move_path_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    target_relative_path = os.path.relpath(target_path, browser_dir).replace("\\", "/")
    return {
        "old_path": source_rel,
        "path": target_relative_path,
    }


def delete_path(manager: MultiBotManager, alias: str, user_id: int, path: str) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    target_path = resolve_safe_write_path(browser_dir, path)

    if os.path.normcase(os.path.abspath(target_path)) == os.path.normcase(os.path.abspath(browser_dir)):
        _raise(400, "cannot_delete_current_dir", "不能删除当前目录")
    if not os.path.exists(target_path):
        _raise(404, "path_not_found", "文件或文件夹不存在")

    try:
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
            deleted_type = "directory"
        else:
            os.remove(target_path)
            deleted_type = "file"
    except Exception as exc:
        _raise(500, "delete_path_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "path": path,
        "deleted_type": deleted_type,
        "working_dir": browser_dir,
    }


def save_chat_attachment(manager: MultiBotManager, alias: str, user_id: int, filename: str, data: bytes) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    if not data:
        _raise(400, "empty_file", "文件内容不能为空")
    if len(data) > UPLOAD_MAX_FILE_SIZE_BYTES:
        _raise(400, "file_too_large", msg("upload", "file_too_large"))

    attachment_dir = build_chat_attachment_dir(alias, user_id)
    os.makedirs(attachment_dir, exist_ok=True)
    file_path, stored_filename = resolve_unique_upload_path(attachment_dir, filename)
    with open(file_path, "wb") as handle:
        handle.write(data)
    return {
        "filename": stored_filename,
        "saved_path": file_path,
        "size": len(data),
    }


async def save_chat_attachment_from_chunks(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    chunks: AsyncIterator[bytes],
) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    attachment_dir = build_chat_attachment_dir(alias, user_id)
    os.makedirs(attachment_dir, exist_ok=True)
    file_path, stored_filename = resolve_unique_upload_path(attachment_dir, filename)
    size = await _write_limited_chunks(file_path, chunks, replace_existing=False)
    return {
        "filename": stored_filename,
        "saved_path": file_path,
        "size": size,
    }


def delete_chat_attachment(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    saved_path: str,
) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    target_path = resolve_chat_attachment_path(alias, user_id, saved_path)

    if target_path.exists() and not target_path.is_file():
        _raise(400, "invalid_saved_path", "附件路径必须指向文件")

    existed = target_path.exists()
    if existed:
        try:
            target_path.unlink()
        except FileNotFoundError:
            existed = False
        except Exception as exc:
            _raise(500, "delete_attachment_failed", str(exc))

    return {
        "filename": target_path.name,
        "saved_path": str(target_path),
        "existed": existed,
        "deleted": existed,
    }


def save_uploaded_file(manager: MultiBotManager, alias: str, user_id: int, filename: str, data: bytes) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    if not data:
        _raise(400, "empty_file", "文件内容不能为空")
    if len(data) > UPLOAD_MAX_FILE_SIZE_BYTES:
        _raise(400, "file_too_large", msg("upload", "file_too_large"))

    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    file_path = resolve_safe_write_path(browser_dir, filename)
    with open(file_path, "wb") as handle:
        handle.write(data)
    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "filename": filename,
        "saved_path": file_path,
        "size": len(data),
    }


async def save_uploaded_file_from_chunks(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    chunks: AsyncIterator[bytes],
) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    file_path = resolve_safe_write_path(browser_dir, filename)
    size = await _write_limited_chunks(file_path, chunks, replace_existing=True)
    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "filename": filename,
        "saved_path": file_path,
        "size": size,
    }


def write_file_content(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    path: str,
    content: str,
    *,
    expected_mtime_ns: int | None = None,
    encoding: str | None = None,
) -> dict[str, Any]:
    ensure_file_browser_supported(manager, alias)
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    file_path = resolve_safe_write_path(browser_dir, path)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")

    current_mtime_ns = stat_file_version(file_path)
    if expected_mtime_ns is not None and int(expected_mtime_ns) != current_mtime_ns:
        _raise(409, "file_version_conflict", "文件已被修改，请重新打开后再试")

    detected_encoding = ensure_editable_text_file(file_path, encoding)

    try:
        write_text_file_atomically(file_path, content, detected_encoding)
        next_mtime_ns = ensure_file_version_advanced(file_path, current_mtime_ns)
    except UnsupportedTextEncoding:
        _raise(400, "unsupported_encoding", "文件不是文本文件或编码不支持")
    except Exception as exc:
        _raise(500, "write_file_failed", str(exc))

    invalidate_workspace_indexes(manager, alias, user_id, browser_dir)
    return {
        "path": path,
        "file_size_bytes": os.path.getsize(file_path),
        "last_modified_ns": next_mtime_ns,
        "encoding": detected_encoding,
    }


def get_file_metadata(manager: MultiBotManager, alias: str, user_id: int, filename: str) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    file_path = resolve_safe_path(browser_dir, filename)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")
    return {
        "filename": filename,
        "path": file_path,
        "size": os.path.getsize(file_path),
        "content_type": "application/octet-stream",
    }


def read_file_content(
    manager: MultiBotManager,
    alias: str,
    user_id: int,
    filename: str,
    mode: str = "cat",
    lines: int = 20,
) -> dict[str, Any]:
    session = get_session_for_alias(manager, alias, user_id)
    browser_dir = require_real_browser_directory(get_browser_directory(session))
    file_path = resolve_safe_path(browser_dir, filename)
    if not os.path.isfile(file_path):
        _raise(404, "file_not_found", "文件不存在")

    file_size = os.path.getsize(file_path)
    raster_preview = build_raster_image_preview(
        filename=filename,
        file_path=file_path,
        working_dir=browser_dir,
        mode=mode,
        file_size=file_size,
    )
    if raster_preview is not None:
        return raster_preview

    try:
        if mode == "head":
            decoded = read_text_file_head(file_path, lines)
            content_lines = decoded.text.splitlines()
            content = "\n".join(content_lines[:lines])
            is_full_content = file_size == len(decoded.text.encode(decoded.encoding, errors="replace"))
            if len(content_lines) > lines:
                is_full_content = False
        else:
            decoded = read_text_file(file_path)
            content = decoded.text
            is_full_content = True
    except UnsupportedTextEncoding:
        _raise(400, "unsupported_encoding", "文件不是文本文件或编码不支持")
    except Exception as exc:
        _raise(500, "read_file_failed", str(exc))

    return {
        "filename": filename,
        "mode": mode,
        "content": content,
        "working_dir": browser_dir,
        "file_size_bytes": file_size,
        "is_full_content": is_full_content,
        "last_modified_ns": stat_file_version(file_path),
        "encoding": decoded.encoding,
    }


def build_raster_image_preview(
    *,
    filename: str,
    file_path: str,
    working_dir: str,
    mode: str,
    file_size: int,
) -> dict[str, Any] | None:
    content_type = _RASTER_IMAGE_CONTENT_TYPES.get(Path(filename).suffix.lower())
    if not content_type:
        return None

    return {
        "filename": filename,
        "mode": mode,
        "content": "",
        "preview_kind": "image",
        "content_type": content_type,
        "content_base64": base64.b64encode(Path(file_path).read_bytes()).decode("ascii"),
        "working_dir": working_dir,
        "file_size_bytes": file_size,
        "is_full_content": True,
        "last_modified_ns": stat_file_version(file_path),
    }
