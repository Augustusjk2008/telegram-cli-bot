"""Output normalization helpers shared by Web and CLI runtimes."""

import re

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[@-_]")


def strip_ansi_escape(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")
