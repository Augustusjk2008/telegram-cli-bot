"""Claude done detector helpers."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from bot.cli import parse_claude_stream_json_line, parse_claude_stream_json_output
from bot.config import (
    CLAUDE_DONE_DETECTOR_ENABLED,
    CLAUDE_DONE_QUIET_SECONDS,
    CLAUDE_DONE_SENTINEL_MODE,
)

logger = logging.getLogger(__name__)

CLAUDE_DONE_SENTINEL_PREFIX = "__TCB_DONE_"
CLAUDE_DONE_PROTOCOL = (
    "Host completion protocol:\n"
    "When you have completely finished this turn, output the following sentinel on its own line "
    "as the last non-empty line of your final response.\n"
    "After outputting the sentinel, do not add any more content.\n"
    "Sentinel: {sentinel}"
)


def _normalize_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _build_sentinel(nonce: str) -> str:
    return f"{CLAUDE_DONE_SENTINEL_PREFIX}{nonce}__"


def _append_protocol(prompt_text: str, sentinel: str) -> str:
    base = prompt_text or ""
    suffix = CLAUDE_DONE_PROTOCOL.format(sentinel=sentinel)
    if not base.strip():
        return suffix
    return f"{base.rstrip()}\n\n{suffix}"


def _last_nonempty_line(text: str) -> Optional[str]:
    for line in reversed(_normalize_newlines(text).split("\n")):
        if line.strip():
            return line
    return None


@dataclass
class ClaudeDoneSession:
    enabled: bool
    prompt_text: str
    sentinel: Optional[str]
    quiet_seconds: float
    nonce: Optional[str] = None


class ClaudeDoneDetector:
    def __init__(self, sentinel: str, quiet_seconds: float):
        self.sentinel = sentinel
        self.quiet_seconds = max(0.0, float(quiet_seconds))
        self.state = "idle"
        self.pending_since: Optional[float] = None

    def observe_text(self, text: str, *, now: Optional[float] = None) -> None:
        current_time = time.monotonic() if now is None else now
        last_line = _last_nonempty_line(text)
        if last_line == self.sentinel:
            if self.state == "idle":
                self.state = "done_pending"
                self.pending_since = current_time
            return

        if self.state == "done_pending":
            self.state = "idle"
            self.pending_since = None

    def poll(self, *, now: Optional[float] = None) -> bool:
        if self.state == "completed":
            return True
        if self.state != "done_pending" or self.pending_since is None:
            return False

        current_time = time.monotonic() if now is None else now
        if (current_time - self.pending_since) >= self.quiet_seconds:
            self.state = "completed"
            return True
        return False


class ClaudeDoneCollector:
    def __init__(self, done_session: ClaudeDoneSession):
        self.done_session = done_session
        self.session_id: Optional[str] = None
        self.detector: Optional[ClaudeDoneDetector] = None
        if done_session.enabled and done_session.sentinel:
            self.detector = ClaudeDoneDetector(done_session.sentinel, done_session.quiet_seconds)
        self._raw_output_parts: list[str] = []
        self._delta_parts: list[str] = []
        self._completed_text: Optional[str] = None
        self._error_parts: list[str] = []

    def _detector_text(self) -> str:
        if self._completed_text and self._completed_text.strip():
            return self._completed_text
        delta_text = "".join(self._delta_parts)
        if delta_text.strip():
            return delta_text
        if self._error_parts:
            return "\n".join(part for part in self._error_parts if part).strip()
        return ""

    def consume_chunk(self, chunk: str, *, now: Optional[float] = None) -> None:
        if not chunk:
            return

        self._raw_output_parts.append(chunk)
        for line in chunk.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parsed = parse_claude_stream_json_line(stripped)
            if parsed["session_id"]:
                self.session_id = parsed["session_id"]
            if parsed["delta_text"]:
                self._delta_parts.append(parsed["delta_text"])
            if parsed["completed_text"]:
                self._completed_text = parsed["completed_text"]
            if parsed["error_text"]:
                self._error_parts.append(parsed["error_text"])

        if self.detector is not None:
            self.detector.observe_text(self._detector_text(), now=now)

    @property
    def raw_output(self) -> str:
        return "".join(self._raw_output_parts)

    @property
    def preview_text(self) -> Optional[str]:
        delta_text = "".join(self._delta_parts)
        if delta_text.strip():
            preview = strip_claude_done_sentinel(delta_text, self.done_session.sentinel).strip()
            return preview or None
        if self._completed_text and self._completed_text.strip():
            preview = strip_claude_done_sentinel(self._completed_text, self.done_session.sentinel).strip()
            return preview or None
        if self._error_parts:
            preview = strip_claude_done_sentinel(
                "\n".join(part for part in self._error_parts if part),
                self.done_session.sentinel,
            ).strip()
            return preview or None
        return None

    @property
    def final_text(self) -> Optional[str]:
        final_text, _ = parse_claude_stream_json_output(self.raw_output)
        stripped = strip_claude_done_sentinel(final_text, self.done_session.sentinel).strip()
        return stripped or None


def strip_claude_done_sentinel(text: str, sentinel: Optional[str]) -> str:
    if not text or not sentinel:
        return text or ""

    normalized = _normalize_newlines(text)
    kept_lines = [line for line in normalized.split("\n") if line != sentinel]
    return "\n".join(kept_lines).strip("\n")


def build_claude_done_session(
    prompt_text: str,
    *,
    cli_type: str,
    enabled: Optional[bool] = None,
    quiet_seconds: Optional[float] = None,
    sentinel_mode: Optional[str] = None,
    nonce: Optional[str] = None,
) -> ClaudeDoneSession:
    effective_enabled = CLAUDE_DONE_DETECTOR_ENABLED if enabled is None else enabled
    effective_quiet_seconds = CLAUDE_DONE_QUIET_SECONDS if quiet_seconds is None else quiet_seconds
    effective_sentinel_mode = CLAUDE_DONE_SENTINEL_MODE if sentinel_mode is None else sentinel_mode

    if cli_type != "claude" or not effective_enabled:
        return ClaudeDoneSession(
            enabled=False,
            prompt_text=prompt_text,
            sentinel=None,
            quiet_seconds=float(effective_quiet_seconds),
        )

    if effective_sentinel_mode != "nonce":
        logger.info("Claude done detector disabled because sentinel mode is unsupported: %s", effective_sentinel_mode)
        return ClaudeDoneSession(
            enabled=False,
            prompt_text=prompt_text,
            sentinel=None,
            quiet_seconds=float(effective_quiet_seconds),
        )

    session_nonce = nonce or uuid.uuid4().hex
    sentinel = _build_sentinel(session_nonce)
    return ClaudeDoneSession(
        enabled=True,
        prompt_text=_append_protocol(prompt_text, sentinel),
        sentinel=sentinel,
        quiet_seconds=float(effective_quiet_seconds),
        nonce=session_nonce,
    )
