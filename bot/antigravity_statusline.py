"""Capture Antigravity statusline JSON for Orbit Safe Claw context telemetry."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.web.cli_context_usage import record_antigravity_statusline_payload


def main() -> int:
    raw = sys.stdin.read()
    result = record_antigravity_statusline_payload(
        raw,
        path=os.environ.get("TCB_ANTIGRAVITY_STATUSLINE_PATH") or None,
        cwd_hint=os.getcwd(),
    )
    if result is None:
        return 0
    left = result.get("context_left_percent")
    window = result.get("context_window")
    used = result.get("used_tokens")
    if isinstance(left, (int, float)) and isinstance(window, int):
        text = f"{left:.1f}% context left · {used or '?'} / {window}"
    else:
        text = "Antigravity context telemetry"
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
