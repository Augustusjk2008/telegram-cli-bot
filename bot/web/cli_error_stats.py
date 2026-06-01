from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bot.manager import MultiBotManager
from bot.runtime_paths import normalize_workspace_dir
from bot.web.chat_store import ChatStore

_ERROR_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("auth", ("authentication_failed", "unauthorized", "invalid api key")),
    ("rate_limit", ("429", "rate limit")),
    ("server_5xx", ("500", "502", "503", "upstream error")),
    ("network", ("timeout", "connection", "dns", "fetch failed")),
    ("resume_session", ("failed to resume", "conversation not found")),
    ("mcp", ("mcp", "tool unavailable", "server not configured")),
    ("permission", ("permission denied", "approval", "sandbox")),
    ("parse", ("json decode", "invalid json")),
]

_LONG_WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\[^\s\"'<>|]+")
_LONG_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])/(?:[^\s\"'<>/]+/){2,}[^\s\"'<>]+")
_TOKEN_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|secret|session|token)\b\s*[:=]\s*[^\s,;\"']+"
)
_LONG_HEX_RE = re.compile(r"\b[a-fA-F0-9]{32,}\b")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{48,}\b")


def classify_cli_error(message: str) -> str:
    text = str(message or "").lower()
    for category, needles in _ERROR_RULES:
        if any(needle in text for needle in needles):
            return category
    return "unknown"


def normalize_error_message(message: str) -> str:
    text = " ".join(str(message or "").split())
    if not text:
        return ""
    text = re.sub(r"https?://[^\s\"'<>]+", _strip_url_query, text)
    text = _LONG_WINDOWS_PATH_RE.sub("<path>", text)
    text = _LONG_POSIX_PATH_RE.sub("<path>", text)
    text = _TOKEN_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _LONG_HEX_RE.sub("<hash>", text)
    text = _LONG_TOKEN_RE.sub("<token>", text)
    if len(text) > 240:
        return f"{text[:237].rstrip()}..."
    return text


def collect_cli_error_stats(
    manager: MultiBotManager,
    hours: int = 24,
    alias: str = "",
    cli_type: str = "",
    category: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    normalized_hours = max(1, min(int(hours or 24), 24 * 30))
    normalized_limit = max(1, min(int(limit or 200), 1000))
    alias_filter = str(alias or "").strip().lower()
    cli_type_filter = str(cli_type or "").strip().lower()
    category_filter = str(category or "").strip().lower()
    to_at = datetime.now(UTC)
    from_at = to_at - timedelta(hours=normalized_hours)

    items: list[dict[str, Any]] = []
    seen_turns: set[str] = set()
    fetch_limit = max(normalized_limit, 1000)
    for workspace in _iter_profile_workspaces(manager, alias_filter=alias_filter, cli_type_filter=cli_type_filter):
        for item in ChatStore(Path(workspace)).list_error_turns(
            from_at=from_at.isoformat(),
            to_at=to_at.isoformat(),
            limit=fetch_limit,
        ):
            turn_id = str(item.get("turn_id") or "")
            if not turn_id or turn_id in seen_turns:
                continue
            if alias_filter and str(item.get("bot_alias") or "").strip().lower() != alias_filter:
                continue
            if cli_type_filter and str(item.get("cli_type") or "").strip().lower() != cli_type_filter:
                continue
            if category_filter and str(item.get("category") or "").strip().lower() != category_filter:
                continue
            seen_turns.add(turn_id)
            items.append(item)

    items.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    summary_items = items
    limited_items = items[:normalized_limit]

    by_cli_type = Counter(str(item.get("cli_type") or "unknown") or "unknown" for item in summary_items)
    by_bot = Counter(str(item.get("bot_alias") or "unknown") or "unknown" for item in summary_items)
    by_category = Counter(str(item.get("category") or "unknown") or "unknown" for item in summary_items)
    latest_at = max((str(item.get("started_at") or "") for item in summary_items), default="")

    return {
        "summary": {
            "total": len(summary_items),
            "by_cli_type": dict(sorted(by_cli_type.items())),
            "by_bot": dict(sorted(by_bot.items())),
            "by_category": dict(sorted(by_category.items())),
            "latest_at": latest_at,
        },
        "items": limited_items,
        "top_errors": _build_top_errors(summary_items),
    }


def _strip_url_query(match: re.Match[str]) -> str:
    raw_url = match.group(0)
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return raw_url.split("?", 1)[0]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _iter_profile_workspaces(
    manager: MultiBotManager,
    *,
    alias_filter: str = "",
    cli_type_filter: str = "",
) -> list[str]:
    profiles = [manager.main_profile, *[manager.managed_profiles[key] for key in sorted(manager.managed_profiles)]]
    workspaces: list[str] = []
    seen: set[str] = set()
    for profile in profiles:
        if alias_filter and str(profile.alias or "").strip().lower() != alias_filter:
            continue
        if cli_type_filter and str(profile.cli_type or "").strip().lower() != cli_type_filter:
            continue
        workspace = str(profile.working_dir or "").strip()
        if not workspace:
            continue
        key = normalize_workspace_dir(workspace)
        if key in seen:
            continue
        seen.add(key)
        workspaces.append(workspace)
    return workspaces


def _build_top_errors(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        raw_message = str(item.get("error_message") or item.get("error_code") or "").strip()
        normalized = normalize_error_message(raw_message) or "unknown"
        bucket = buckets.setdefault(
            normalized,
            {
                "message": normalized,
                "count": 0,
                "category": str(item.get("category") or "unknown"),
                "latest_at": "",
            },
        )
        bucket["count"] += 1
        started_at = str(item.get("started_at") or "")
        if started_at > str(bucket.get("latest_at") or ""):
            bucket["latest_at"] = started_at
            bucket["category"] = str(item.get("category") or bucket.get("category") or "unknown")

    return sorted(
        buckets.values(),
        key=lambda item: (-int(item.get("count") or 0), str(item.get("latest_at") or "")),
    )[:10]
