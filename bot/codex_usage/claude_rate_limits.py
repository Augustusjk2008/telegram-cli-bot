"""Claude Code subscription quota parsing.

Claude Code reports quota through the ``rate_limit_event`` line of
``--output-format stream-json``. Its ``rate_limit_info.unifiedWindows`` mirrors
the ``anthropic-ratelimit-unified-*`` response headers::

    {"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed", "rateLimitType": "five_hour", "resetsAt": 1793900400,
        "unifiedWindows": {
            "five_hour": {"utilization": 0.01, "resetsAt": 1793900400, "status": "allowed"},
            "seven_day": {"utilization": 0.02, "resetsAt": 1793941200, "status": "allowed"}}}}

``utilization`` is the used fraction of the window (usually 0-1; it may exceed
1 when usage runs past a cap) and ``resetsAt`` is epoch seconds. Plan type is
not part of the event, so it comes from ``claude auth status --json``; only the
whitelisted, non-identifying fields of that output are retained.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .models import (
    CLAUDE_OVERAGE_RATE_LIMIT_ID,
    GENERAL_CLAUDE_RATE_LIMIT_ID,
    CodexRateLimitSample,
    ProviderInfo,
)


# (unifiedWindows key, stored limit id, window minutes)
CLAUDE_UNIFIED_WINDOWS = (
    ("five_hour", GENERAL_CLAUDE_RATE_LIMIT_ID, 5 * 60),
    ("seven_day", GENERAL_CLAUDE_RATE_LIMIT_ID, 7 * 24 * 60),
    ("seven_day_overage_included", CLAUDE_OVERAGE_RATE_LIMIT_ID, 7 * 24 * 60),
)
_OFFICIAL_API_HOSTS = frozenset({"api.anthropic.com"})
_AUTH_STATUS_TIMEOUT_SECONDS = 5.0
_AUTH_STATUS_CACHE_SECONDS = 600.0
_AUTH_STATUS_FIELDS = ("loggedIn", "authMethod", "apiProvider", "subscriptionType")


def _window_sample(
    window: object,
    *,
    sampled_at: datetime,
    limit_id: str,
    window_minutes: int,
    plan_type: str | None,
) -> CodexRateLimitSample | None:
    if not isinstance(window, Mapping):
        return None
    utilization = window.get("utilization")
    resets_at = window.get("resetsAt")
    if (
        isinstance(utilization, bool)
        or not isinstance(utilization, (int, float))
        or not math.isfinite(utilization)
        or utilization < 0
    ):
        return None
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return None
    if not math.isfinite(resets_at) or resets_at < 0:
        return None
    try:
        return CodexRateLimitSample(
            sampled_at=sampled_at,
            used_percent=min(float(utilization) * 100.0, 100.0),
            window_minutes=window_minutes,
            resets_at=datetime.fromtimestamp(int(resets_at), timezone.utc),
            plan_type=plan_type,
            limit_id=limit_id,
        )
    except (OSError, OverflowError, ValueError):
        return None


def samples_from_rate_limit_info(
    info: object,
    *,
    sampled_at: datetime,
    plan_type: str | None = None,
) -> tuple[CodexRateLimitSample, ...]:
    """Convert one ``rate_limit_info`` object into per-window quota samples."""

    if not isinstance(info, Mapping):
        return ()
    windows = info.get("unifiedWindows")
    if not isinstance(windows, Mapping):
        return ()
    samples = (
        _window_sample(
            windows.get(key),
            sampled_at=sampled_at,
            limit_id=limit_id,
            window_minutes=window_minutes,
            plan_type=plan_type,
        )
        for key, limit_id, window_minutes in CLAUDE_UNIFIED_WINDOWS
    )
    return tuple(sample for sample in samples if sample is not None)


def claude_config_dir(env: Mapping[str, str] | None) -> Path:
    source = os.environ if env is None else env
    configured = str(source.get("CLAUDE_CONFIG_DIR") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def _settings_base_url(config_dir: Path) -> str:
    try:
        settings = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    settings_env = settings.get("env") if isinstance(settings, Mapping) else None
    if not isinstance(settings_env, Mapping):
        return ""
    return str(settings_env.get("ANTHROPIC_BASE_URL") or "").strip()


def resolve_claude_base_url(env: Mapping[str, str] | None) -> str:
    """Return the configured base URL; the process env wins over settings.json."""

    source = os.environ if env is None else env
    configured = str(source.get("ANTHROPIC_BASE_URL") or "").strip()
    return configured or _settings_base_url(claude_config_dir(env))


def _normalized_base_url(value: str) -> str | None:
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    netloc = parts.hostname.lower()
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}"


@dataclass(frozen=True, slots=True)
class ClaudeAuthStatus:
    logged_in: bool
    auth_method: str | None
    api_provider: str | None
    subscription_type: str | None

    @property
    def is_subscription(self) -> bool:
        return (
            self.logged_in
            and self.auth_method == "claude.ai"
            and self.api_provider in {None, "firstParty"}
        )


def _parse_auth_status(raw: str) -> ClaudeAuthStatus | None:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    # Email and organization fields are deliberately never read.
    fields = {key: payload.get(key) for key in _AUTH_STATUS_FIELDS}

    def text(key: str) -> str | None:
        value = fields[key]
        return (value.strip() or None) if isinstance(value, str) else None

    return ClaudeAuthStatus(
        logged_in=fields["loggedIn"] is True,
        auth_method=text("authMethod"),
        api_provider=text("apiProvider"),
        subscription_type=text("subscriptionType"),
    )


class ClaudeAuthStatusReader:
    """Short-lived, cached ``claude auth status --json`` lookups."""

    def __init__(
        self,
        *,
        runner: Any | None = None,
        cache_seconds: float = _AUTH_STATUS_CACHE_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        self._runner = runner or _run_auth_status
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], tuple[float, ClaudeAuthStatus | None]] = {}

    def read(self, *, executable: str, env: Mapping[str, str] | None) -> ClaudeAuthStatus | None:
        executable_text = str(executable or "").strip()
        if not executable_text:
            return None
        key = (executable_text, str(claude_config_dir(env)))
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] < self._cache_seconds:
                return cached[1]
        try:
            raw = self._runner(executable=executable_text, env=env)
        except Exception:
            raw = None
        status = _parse_auth_status(raw) if raw else None
        with self._lock:
            self._cache[key] = (now, status)
        return status

    def cached(self) -> ClaudeAuthStatus | None:
        """The freshest cached status without spawning a process."""

        with self._lock:
            entries = sorted(self._cache.values(), key=lambda item: item[0], reverse=True)
        return next((status for _, status in entries if status is not None), None)


def _run_auth_status(*, executable: str, env: Mapping[str, str] | None) -> str | None:
    try:
        completed = subprocess.run(
            [shutil.which(executable) or executable, "auth", "status", "--json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(env) if env is not None else None,
            timeout=_AUTH_STATUS_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def resolve_claude_provider(
    *,
    env: Mapping[str, str] | None,
    auth_status: ClaudeAuthStatus | None,
) -> ProviderInfo:
    """Identify whether quota windows belong to a Claude subscription account."""

    base_url = resolve_claude_base_url(env)
    if base_url:
        normalized = _normalized_base_url(base_url)
        if normalized is None:
            return ProviderInfo(key="unknown", kind="unknown", base_url=None, resolution="invalid_base_url")
        if (urlsplit(normalized).hostname or "") not in _OFFICIAL_API_HOSTS:
            return ProviderInfo(key=normalized, kind="base_url", base_url=normalized)
    if auth_status is not None and not auth_status.is_subscription:
        return ProviderInfo(
            key=f"claude_{auth_status.api_provider or auth_status.auth_method or 'unknown'}",
            kind="unknown",
            base_url=None,
            resolution="unsupported_override",
        )
    return ProviderInfo(key="claude_official", kind="claude_official", base_url=None)


__all__ = [
    "CLAUDE_UNIFIED_WINDOWS",
    "ClaudeAuthStatus",
    "ClaudeAuthStatusReader",
    "claude_config_dir",
    "resolve_claude_base_url",
    "resolve_claude_provider",
    "samples_from_rate_limit_info",
]
