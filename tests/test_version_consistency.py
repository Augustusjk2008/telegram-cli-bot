from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _documented_version(path: Path, pattern: str) -> str:
    content = path.read_text(encoding="utf-8-sig")
    match = re.search(pattern, content)
    assert match is not None, f"{path.name} 中缺少版本号"
    return match.group(1)


def test_documented_versions_match_version_file() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert _documented_version(ROOT / "README.md", r"当前版本：`([^`]+)`") == version
    assert _documented_version(ROOT / "AGENTS.md", r"当前仓库版本：`([^`]+)`") == version
