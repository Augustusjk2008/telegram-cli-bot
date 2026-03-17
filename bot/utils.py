"""与业务逻辑无关的通用工具函数"""

import logging
from typing import List, Optional

from bot.config import ALLOWED_USER_IDS, DANGEROUS_COMMANDS

logger = logging.getLogger(__name__)


def check_auth(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def is_dangerous_command(command: str) -> bool:
    command_lower = command.lower().strip()
    first_word = command_lower.split()[0] if command_lower else ""

    if first_word in DANGEROUS_COMMANDS:
        return True

    dangerous_patterns = [";rm ", "|rm ", "`rm ", "$(rm ", "&rm ", "&&rm "]
    return any(pattern in command_lower for pattern in dangerous_patterns)


def truncate_for_markdown(text: str, max_len: int = 3900) -> str:
    """截断文本（用于非流式输出的场景）"""
    if len(text) <= max_len:
        return text

    truncated = text[: max_len - 20]

    if truncated.count("```") % 2 != 0:
        last_block = truncated.rfind("\n```")
        if last_block > max_len * 0.5:
            truncated = truncated[:last_block]

    while truncated.endswith("`") and not truncated.endswith("```"):
        truncated = truncated[:-1]

    if truncated.count("```") % 2 != 0:
        truncated += "\n```"

    return truncated + "\n\n... (已截断)"


def split_text_into_chunks(text: str, max_len: int = 3800) -> List[str]:
    """
    将长文本分割成多个块，尽量在代码块边界处分割。
    每个块都会正确处理代码块标记。
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    lines = text.split('\n')
    current_chunk_lines = []
    current_len = 0
    in_code_block = False

    def close_code_block(lines_list: List[str]) -> None:
        """如果当前在代码块内，添加关闭标记"""
        if in_code_block and (not lines_list or not lines_list[-1].rstrip().endswith('```')):
            lines_list.append('```')

    def reopen_code_block(lines_list: List[str]) -> None:
        """为新块添加代码块开启标记"""
        if in_code_block:
            lines_list.insert(0, '```')

    for line in lines:
        line_len = len(line) + 1  # +1 for newline

        # 检查是否需要分割
        if current_len + line_len > max_len and current_chunk_lines:
            # 关闭当前代码块（如果在代码块内）
            close_code_block(current_chunk_lines)
            chunks.append('\n'.join(current_chunk_lines))

            # 开始新块
            current_chunk_lines = []
            current_len = 0

            # 如果在代码块内，新块需要重新开启代码块
            reopen_code_block(current_chunk_lines)

        current_chunk_lines.append(line)
        current_len += line_len

        # 检测代码块边界
        stripped = line.strip()
        if stripped.startswith('```') and not stripped[3:].strip():
            in_code_block = not in_code_block

    # 处理最后一个块
    if current_chunk_lines:
        chunks.append('\n'.join(current_chunk_lines))

    return chunks


async def safe_edit_text(message, text: str, parse_mode: Optional[str] = None, reply_markup=None):
    """安全编辑消息：Markdown 失败时自动降级为纯文本"""
    try:
        kwargs = {}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        await message.edit_text(text, **kwargs)
        return
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return
        if parse_mode and (
            "can't parse entities" in err
            or "parse entities" in err
            or "markdown" in err
            or "entity" in err
        ):
            try:
                kwargs = {}
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                await message.edit_text(text, **kwargs)
            except Exception:
                pass
            return
        raise


def is_safe_filename(filename: str) -> bool:
    forbidden = ["\\", "..", "\x00", ":", "*", "?", '"', "<", ">", "|"]
    for char in forbidden:
        if char in filename:
            return False
    return filename.strip() not in ("", ".")
