"""Telegram 内联按钮文件浏览器。"""

import html
import logging
import math
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.context_helpers import get_current_session
from bot.handlers.basic import resolve_working_directory, update_session_working_directory
from bot.handlers.file import (
    FilePathError,
    IMAGE_EXTENSIONS,
    resolve_session_path,
    send_document_from_path,
    send_photo_from_path,
)
from bot.messages import msg
from bot.utils import check_auth, safe_edit_text

logger = logging.getLogger(__name__)

PAGE_SIZE = 8
TEXT_PREVIEW_LINES = 80
TEXT_PREVIEW_CHARS = 3200


def _get_browser_state(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    states = context.application.bot_data.setdefault("file_browser_state", {})
    return states.setdefault(
        user_id,
        {
            "page": 0,
            "preview_file": None,
            "preview_offset": 0,
        },
    )


def _reset_preview_state(state: dict):
    state["preview_file"] = None
    state["preview_offset"] = 0


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size:,} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _list_directory_entries(working_dir: str) -> list[dict]:
    entries = []
    for entry in sorted(os.scandir(working_dir), key=lambda item: (not item.is_dir(), item.name.lower())):
        item = {
            "name": entry.name,
            "is_dir": entry.is_dir(),
        }
        if entry.is_file():
            item["size"] = entry.stat().st_size
        entries.append(item)
    return entries


def _paginate_entries(entries: list[dict], page: int) -> tuple[list[dict], int, int]:
    total_pages = max(1, math.ceil(len(entries) / PAGE_SIZE))
    current_page = min(max(page, 0), total_pages - 1)
    start = current_page * PAGE_SIZE
    end = start + PAGE_SIZE
    return entries[start:end], current_page, total_pages


def _build_directory_text(working_dir: str, visible_entries: list[dict], page: int, total_pages: int) -> str:
    lines = [f"📂 <code>{html.escape(working_dir)}</code>"]
    if total_pages > 1:
        lines.append(f"📄 第 {page + 1}/{total_pages} 页")
    lines.append("")

    if not visible_entries:
        lines.append(msg("ls", "empty"))
        return "\n".join(lines)

    for entry in visible_entries:
        if entry["is_dir"]:
            lines.append(f"📁 {html.escape(entry['name'])}/")
        else:
            lines.append(f"📄 {html.escape(entry['name'])} ({_format_file_size(entry['size'])})")
    return "\n".join(lines)


def _build_directory_markup(visible_entries: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    keyboard = []
    for entry in visible_entries:
        icon = "📁" if entry["is_dir"] else "📄"
        suffix = "/" if entry["is_dir"] else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{icon} {entry['name']}{suffix}",
                    callback_data=f"fb:open:{entry['name']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("⬆ 上一级", callback_data="fb:nav:up")])

    page_row = []
    if page > 0:
        page_row.append(InlineKeyboardButton("◀ 上一页", callback_data=f"fb:page:{page - 1}"))
    if page + 1 < total_pages:
        page_row.append(InlineKeyboardButton("下一页 ▶", callback_data=f"fb:page:{page + 1}"))
    if page_row:
        keyboard.append(page_row)

    return InlineKeyboardMarkup(keyboard)


def _build_file_detail_text(file_name: str, file_path: str, note: str | None = None) -> str:
    file_size = _format_file_size(os.path.getsize(file_path))
    suffix = os.path.splitext(file_name)[1].lower()
    if suffix in IMAGE_EXTENSIONS:
        file_type = "图片文件"
    else:
        file_type = "普通文件"

    lines = [
        f"📄 <b>{html.escape(file_name)}</b>",
        f"📦 大小: {file_size}",
        f"🧩 类型: {file_type}",
        f"📁 <code>{html.escape(file_path)}</code>",
    ]
    if note:
        lines.extend(["", note])
    return "\n".join(lines)


def _build_file_detail_markup(file_name: str, page: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("👁 预览", callback_data=f"fb:act:preview:{file_name}"),
            InlineKeyboardButton("⬇ 下载", callback_data=f"fb:act:download:{file_name}"),
        ],
        [InlineKeyboardButton("返回列表", callback_data=f"fb:page:{page}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _read_text_preview(file_path: str, offset: int) -> dict:
    lines = []
    line_index = 0
    has_next = False

    with open(file_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            if line_index < offset:
                line_index += 1
                continue

            line = raw_line.rstrip("\r\n")
            candidate = "\n".join(lines + [line])
            if lines and (len(lines) >= TEXT_PREVIEW_LINES or len(candidate) > TEXT_PREVIEW_CHARS):
                has_next = True
                break

            lines.append(line)
            line_index += 1

    return {
        "content": "\n".join(lines),
        "start_line": offset + 1 if lines else 0,
        "end_line": offset + len(lines),
        "has_next": has_next,
        "next_offset": offset + len(lines),
    }


def _build_text_preview_markup(file_name: str, page: int, offset: int, preview: dict) -> InlineKeyboardMarkup:
    keyboard = []
    nav_row = []
    if offset > 0:
        nav_row.append(
            InlineKeyboardButton(
                "⬅ 上一段",
                callback_data=f"fb:prev:{max(0, offset - TEXT_PREVIEW_LINES)}",
            )
        )
    if preview["has_next"]:
        nav_row.append(
            InlineKeyboardButton(
                "下一段 ➡",
                callback_data=f"fb:next:{preview['next_offset']}",
            )
        )
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append(
        [
            InlineKeyboardButton("⬇ 下载", callback_data=f"fb:act:download:{file_name}"),
            InlineKeyboardButton("返回列表", callback_data=f"fb:page:{page}"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


async def _edit_directory_message(message, session, state: dict, page: int):
    entries = _list_directory_entries(session.working_dir)
    visible_entries, current_page, total_pages = _paginate_entries(entries, page)
    state["page"] = current_page
    text = _build_directory_text(session.working_dir, visible_entries, current_page, total_pages)
    reply_markup = _build_directory_markup(visible_entries, current_page, total_pages)
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=reply_markup)


async def _send_directory_message(message, session, state: dict, page: int):
    entries = _list_directory_entries(session.working_dir)
    visible_entries, current_page, total_pages = _paginate_entries(entries, page)
    state["page"] = current_page
    text = _build_directory_text(session.working_dir, visible_entries, current_page, total_pages)
    reply_markup = _build_directory_markup(visible_entries, current_page, total_pages)
    await message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def _show_file_detail(message, state: dict, file_name: str, file_path: str, note: str | None = None):
    text = _build_file_detail_text(file_name, file_path, note=note)
    reply_markup = _build_file_detail_markup(file_name, state["page"])
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=reply_markup)


async def _show_error(message, state: dict, text: str):
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("返回列表", callback_data=f"fb:page:{state['page']}")]]
    )
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=reply_markup)


async def _preview_text_file(message, state: dict, file_name: str, file_path: str, offset: int):
    preview = _read_text_preview(file_path, offset)
    state["preview_file"] = file_name
    state["preview_offset"] = offset

    content = preview["content"] or "(空文件)"
    if preview["start_line"] > 0:
        range_text = f"📃 第 {preview['start_line']}-{preview['end_line']} 行"
    else:
        range_text = "📃 空文件"

    text = (
        f"📄 <b>{html.escape(file_name)}</b>\n"
        f"{range_text}\n\n"
        f"<pre>{html.escape(content)}</pre>"
    )
    reply_markup = _build_text_preview_markup(file_name, state["page"], offset, preview)
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=reply_markup)


async def _handle_preview_action(message, state: dict, file_name: str, file_path: str):
    if os.path.splitext(file_name)[1].lower() in IMAGE_EXTENSIONS:
        await send_photo_from_path(message, file_path)
        await _show_file_detail(message, state, file_name, file_path, note="✅ 已发送图片预览")
        return

    try:
        await _preview_text_file(message, state, file_name, file_path, 0)
    except UnicodeDecodeError:
        await _show_file_detail(message, state, file_name, file_path, note="⚠️ 当前文件不是 UTF-8 文本，无法内联预览")


async def _handle_download_action(message, state: dict, file_name: str, file_path: str):
    if os.path.getsize(file_path) > 50 * 1024 * 1024:
        await _show_file_detail(message, state, file_name, file_path, note="❌ 文件太大 (>50MB)，无法通过 Telegram 发送")
        return

    await send_document_from_path(message, file_path)
    await _show_file_detail(message, state, file_name, file_path, note="✅ 文件已发送")


async def show_file_browser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    state = _get_browser_state(context, user_id)
    state["page"] = 0
    _reset_preview_state(state)

    try:
        await _send_directory_message(update.message, session, state, 0)
    except Exception as exc:
        logger.warning("显示文件浏览器失败 dir=%s error=%s", session.working_dir, exc)
        await update.message.reply_text(msg("ls", "error", error=str(exc)))


async def handle_file_browser_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or query.message is None:
        return

    await query.answer()

    user_id = update.effective_user.id
    if not check_auth(user_id):
        return

    session = get_current_session(update, context)
    state = _get_browser_state(context, user_id)
    data = query.data or ""

    try:
        if data == "fb:nav:up":
            parent_dir = resolve_working_directory(session.working_dir, "..")
            if parent_dir != session.working_dir:
                await update_session_working_directory(context, session, "..")
            state["page"] = 0
            _reset_preview_state(state)
            await _edit_directory_message(query.message, session, state, 0)
            return

        if data.startswith("fb:page:"):
            page = int(data.rsplit(":", 1)[1])
            _reset_preview_state(state)
            await _edit_directory_message(query.message, session, state, page)
            return

        if data.startswith("fb:open:"):
            name = data[len("fb:open:") :]
            target_path = resolve_session_path(session, name)
            if os.path.isdir(target_path):
                await update_session_working_directory(context, session, name)
                state["page"] = 0
                _reset_preview_state(state)
                await _edit_directory_message(query.message, session, state, 0)
                return
            if os.path.isfile(target_path):
                _reset_preview_state(state)
                await _show_file_detail(query.message, state, name, target_path)
                return
            await _show_error(query.message, state, f"❌ 文件不存在:\n<code>{html.escape(name)}</code>")
            return

        if data.startswith("fb:act:preview:"):
            name = data[len("fb:act:preview:") :]
            file_path = resolve_session_path(session, name)
            if not os.path.isfile(file_path):
                await _show_error(query.message, state, f"❌ 文件不存在:\n<code>{html.escape(name)}</code>")
                return
            await _handle_preview_action(query.message, state, name, file_path)
            return

        if data.startswith("fb:act:download:"):
            name = data[len("fb:act:download:") :]
            file_path = resolve_session_path(session, name)
            if not os.path.isfile(file_path):
                await _show_error(query.message, state, f"❌ 文件不存在:\n<code>{html.escape(name)}</code>")
                return
            await _handle_download_action(query.message, state, name, file_path)
            return

        if data.startswith("fb:prev:") or data.startswith("fb:next:"):
            preview_file = state.get("preview_file")
            if not preview_file:
                await _show_error(query.message, state, "❌ 当前没有可继续翻页的文本预览")
                return
            offset = int(data.rsplit(":", 1)[1])
            file_path = resolve_session_path(session, preview_file)
            if not os.path.isfile(file_path):
                await _show_error(query.message, state, f"❌ 文件不存在:\n<code>{html.escape(preview_file)}</code>")
                return
            await _preview_text_file(query.message, state, preview_file, file_path, offset)
            return

        await _show_error(query.message, state, "❌ 无效的文件浏览操作")
    except FileNotFoundError as exc:
        await _show_error(query.message, state, f"❌ 目录不存在:\n<code>{html.escape(str(exc))}</code>")
    except FilePathError as exc:
        error_text = "⛔ 文件路径不安全"
        if exc.code == "unsafe_filename":
            error_text = "⛔ 文件名包含非法字符"
        await _show_error(query.message, state, error_text)
    except Exception as exc:
        logger.exception("处理文件浏览回调失败 data=%s", data)
        await _show_error(query.message, state, f"❌ 文件浏览失败: {html.escape(str(exc))}")
