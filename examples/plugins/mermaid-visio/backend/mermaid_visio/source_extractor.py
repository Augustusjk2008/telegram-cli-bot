from __future__ import annotations

import re
from pathlib import Path

from .models import DiagramSource

FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[ \t]*(?P<lang>mermaid|mmd)\b[^\n]*\n"
    r"(?P<body>.*?)(?:\n(?P=fence)[ \t]*$)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)
SAFE_NAME_RE = re.compile(r"[^\w.\-]+", re.UNICODE)


def safe_stem(value: str, fallback: str) -> str:
    cleaned = SAFE_NAME_RE.sub("_", value.strip()).strip("._")
    return cleaned or fallback


def _heading_before(text: str, offset: int) -> str:
    title = ""
    for match in HEADING_RE.finditer(text[:offset]):
        title = match.group(2).strip()
    return title


def extract_diagrams(path: str, content: str) -> list[DiagramSource]:
    suffix = Path(path).suffix.lower()
    matches = list(FENCE_RE.finditer(content))
    if suffix == ".md" or matches:
        diagrams: list[DiagramSource] = []
        for index, match in enumerate(matches, start=1):
            heading = _heading_before(content, match.start())
            title = heading or f"diagram-{index}"
            start_line = content[:match.start("body")].count("\n") + 1
            diagrams.append(
                DiagramSource(
                    source_id=f"diagram-{index}",
                    title=title,
                    code=match.group("body").strip(),
                    start_line=start_line,
                    suggested_filename=f"{safe_stem(title, f'diagram-{index}')}.vsdx",
                )
            )
        return diagrams

    title = Path(path).stem or "diagram-1"
    return [
        DiagramSource(
            source_id="diagram-1",
            title=title,
            code=content.strip(),
            start_line=1,
            suggested_filename=f"{safe_stem(title, 'diagram-1')}.vsdx",
        )
    ]
