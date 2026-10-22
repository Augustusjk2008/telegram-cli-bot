"""Text routing and result formatting for Telegram."""

from __future__ import annotations

import math
import re
from html import escape
from typing import Any

from .formatting import markdown_to_telegram_html, split_telegram_html, telegram_html_to_text

MESSAGE_LIMIT = 4096
BROADCAST_PREVIEW_CHARS = 300
SHORTCUTS = {
    "🤖 智能体": "targets", "✉️ 发消息": "prompt", "🆕 新会话": "new",
    "📊 状态": "status", "⏹ 停止任务": "stop", "⚙️ 配置": "config", "❓ 帮助": "help",
}
_ROUTE = re.compile(r"\Ato[ \t]+(\S+)(?:[ \t]*\r?\n|[ \t]+)([\s\S]*)\Z", re.IGNORECASE)
_CONFIG_SETTINGS = {"model", "reasoning", "cluster"}


def parse_target_text(text: str) -> tuple[str, str] | None:
    match = _ROUTE.fullmatch(text)
    if match is None or not match[2].strip():
        return None
    return match[1].lower(), match[2]


def parse_config_text(text: str) -> tuple[str | None, str | None, str | None] | None:
    """Parse ``/config [alias] [model|reasoning|cluster value]``."""
    parts = str(text or "").strip().split(None, 3)
    if not parts or parts[0].lower() != "/config":
        return None
    if len(parts) == 1:
        return None, None, None

    alias: str | None = None
    setting: str | None = None
    value: str | None = None
    index = 1
    if parts[index].lower() not in _CONFIG_SETTINGS:
        alias = parts[index].lower()
        index += 1
    if index < len(parts):
        setting = parts[index].lower()
        if setting not in _CONFIG_SETTINGS:
            return None
        index += 1
        value = parts[index].strip() if index < len(parts) else ""
    return alias, setting, value


def help_text(aliases: list[str]) -> str:
    targets = "\n".join(f"• {alias}" for alias in aliases) or "暂无已启用的智能体"
    return (
        f"可用智能体：\n{targets}\n\n"
        "发送：to <智能体别名> <正文>\n"
        "例如：to dev 帮我分析这个问题\n"
        "也可以在 to dev 后换行输入多行正文或代码。\n"
        "新会话：to <智能体别名> /new（保留旧历史）\n"
        "底部“智能体”选择目标，“配置”查询并修改模型、思考强度和集群开关。\n"
        "也可以使用 /config [智能体]，或 /config [智能体] model|reasoning|cluster <值>。\n"
        "“发消息”弹出定向回复提示；答复下可点击“继续聊”。\n"
        "回复提示中的全部文字会作为正文发送到提示标注的目标和会话。\n"
        "消息使用对应智能体的当前 Web 会话；完成后回复最终结果和 context left。\n"
        "广播摘要可点击“展开全文”，或回复该通知发送 /expand；单独发送 /expand 展开最近一条摘要。\n"
        "人工审批请在 Web 中处理。"
    )


def reply_keyboard() -> dict[str, Any]:
    labels = list(SHORTCUTS)
    return {"keyboard": [[{"text": label} for label in labels[i:i + 2]] for i in range(0, len(labels), 2)],
            "resize_keyboard": True, "is_persistent": True}


def force_reply() -> dict[str, Any]:
    return {"force_reply": True, "input_field_placeholder": "回复此消息，发送正文"}


def conversation_label(conversation_id: str | None) -> str:
    return conversation_id or "尚无会话（首次发送时创建）"


def status_text(alias: str, snapshot: dict[str, Any]) -> str:
    phases = {"idle": "空闲", "preparing": "准备中", "running": "执行中",
              "waiting_approval": "等待审批（请在 Web 完成审批）", "stopping": "正在停止"}
    lines = [f"[{alias}] 状态：{phases.get(snapshot['phase'], snapshot['phase'])}",
             f"会话：{conversation_label(snapshot.get('conversation_id'))}",
             f"执行模式：{snapshot['execution_mode']}"]
    identity = snapshot.get("turn_id") or snapshot.get("execution_id")
    if identity:
        lines.append(f"任务：{identity}")
    task_ids = snapshot.get("cluster_task_ids") or []
    if task_ids:
        if not identity:
            lines.append("主任务已结束，子任务仍在执行。")
        lines.append(f"运行中或排队的子任务：{len(task_ids)} 个")
    lines.append(f"context left: {context_left(snapshot.get('context_usage'))}")
    return "\n".join(lines)


def configuration_text(alias: str, configuration: dict[str, Any]) -> str:
    model_value = str(configuration.get("model") or "").strip()
    model = "默认" if model_value.lower() in {"", "none"} else model_value
    reasoning = str(configuration.get("reasoning_effort") or "默认")
    mode = str(configuration.get("execution_mode") or "cli")
    cluster = "开启" if configuration.get("cluster_enabled") else "关闭"
    return "\n".join([
        f"[{alias}] 智能体配置",
        f"执行模式：{mode}",
        f"模型：{model}",
        f"思考强度：{reasoning}",
        f"集群：{cluster}",
    ])


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


def agent_header(alias: str) -> str:
    return f"🤖 <b>[{escape(alias)}]</b>"


def format_plain_text(text: str) -> list[str]:
    """Escape control messages and emphasize their existing agent label."""
    match = re.match(r"\A\[([^\]\n]+)\]", text)
    rendered = (agent_header(match[1]) + escape(text[match.end():])) if match else escape(text)
    return split_telegram_html(rendered)


def format_result(alias: str, content: str, usage: dict[str, Any] | None) -> list[str]:
    header = agent_header(alias) + "\n\n"
    footer = f"\n\ncontext left: {context_left(usage)}"
    # Reserve room for a target on every segment and the complete final footer.
    capacity = MESSAGE_LIMIT - len(telegram_html_to_text(header).encode("utf-16-le")) // 2 - len(footer)
    rendered = markdown_to_telegram_html(content)
    if not telegram_html_to_text(rendered).strip():
        rendered = "任务已完成，没有文本答复。"
    chunks = split_telegram_html(rendered, capacity)
    return [header + chunk + (footer if index == len(chunks) - 1 else "") for index, chunk in enumerate(chunks)]


def format_broadcast_preview(alias: str, content: str) -> str | None:
    text = telegram_html_to_text(markdown_to_telegram_html(content)).strip()
    if len(text) <= BROADCAST_PREVIEW_CHARS:
        return None
    preview = text[:BROADCAST_PREVIEW_CHARS].rstrip() + "…"
    return (
        f"{agent_header(alias)}\n\n{escape(preview)}\n\n"
        "点击“展开全文”，或回复此消息发送 /expand。"
    )
