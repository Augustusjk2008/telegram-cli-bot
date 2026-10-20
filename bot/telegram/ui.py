"""Text routing and result formatting for Telegram."""

from __future__ import annotations

import math
import re
from typing import Any

MESSAGE_LIMIT = 4096
_ROUTE = re.compile(r"\Ato[ \t]+(\S+)(?:[ \t]*\r?\n|[ \t]+)([\s\S]*)\Z", re.IGNORECASE)


def parse_target_text(text: str) -> tuple[str, str] | None:
    match = _ROUTE.fullmatch(text)
    if match is None or not match[2].strip():
        return None
    return match[1].lower(), match[2]


def help_text(aliases: list[str]) -> str:
    targets = "\n".join(f"• {alias}" for alias in aliases) or "暂无已启用的智能体"
    return (
        f"可用智能体：\n{targets}\n\n"
        "发送：to <智能体别名> <正文>\n"
        "例如：to dev 帮我分析这个问题\n"
        "也可以在 to dev 后换行输入多行正文或代码。\n"
        "消息使用对应智能体的当前 Web 会话；完成后回复最终结果和 context left。\n"
        "人工审批请在 Web 中处理。"
    )


def context_left(usage: dict[str, Any] | None) -> str:
    if not isinstance(usage, dict):
        return "unknown"

    def number(*keys: str) -> float | None:
        for key in keys:
            value = usage.get(key)
            if type(value) in (int, float) and math.isfinite(value):
                return float(value)
        return None

    left = number("contextLeftPercent", "context_left_percent")
    if left is None:
        used_percent = number("contextUsedPercent", "context_used_percent")
        if used_percent is not None:
            left = 100 - used_percent
    if left is None:
        used = number("contextUsed", "context_used", "usedTokens", "used_tokens")
        window = number("contextWindow", "context_window")
        if used is not None and used >= 0 and window is not None and window > 0:
            left = 100 - used / window * 100
    if left is None:
        return "unknown"
    rounded = math.floor(max(0, min(100, left)) * 10 + 0.5) / 10
    return f"{rounded:g}%"


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Count UTF-16 units as well, so emoji never overflow Telegram's limit."""
    chunks: list[str] = []
    start = 0
    units = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > limit:
            chunks.append(text[start:index])
            start, units = index, 0
        units += width
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def format_result(alias: str, content: str, usage: dict[str, Any] | None) -> list[str]:
    header = f"[{alias}]\n\n"
    footer = f"\n\ncontext left: {context_left(usage)}"
    # Reserve room for a target on every segment and the complete final footer.
    capacity = MESSAGE_LIMIT - len(header.encode("utf-16-le")) // 2 - len(footer)
    chunks = split_text(content or "任务已完成，没有文本答复。", capacity)
    return [header + chunk + (footer if index == len(chunks) - 1 else "") for index, chunk in enumerate(chunks)]
