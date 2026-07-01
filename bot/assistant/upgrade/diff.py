from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.git_runtime import build_git_fsmonitor_disabled_command


def parse_patch_files(diff_text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    chunks: list[str] = []
    for line in str(diff_text or "").splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                current["text"] = "\n".join(chunks)
                files.append(current)
            parts = line.split()
            path = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            current = {
                "path": path,
                "old_path": "",
                "status": "modified",
                "additions": 0,
                "deletions": 0,
                "text": "",
            }
            chunks = [line]
            continue
        if current is None:
            continue
        chunks.append(line)
        if line.startswith("new file mode"):
            current["status"] = "added"
        elif line.startswith("deleted file mode"):
            current["status"] = "deleted"
        elif line.startswith("rename from "):
            current["old_path"] = line.removeprefix("rename from ").strip()
            current["status"] = "renamed"
        elif line.startswith("rename to "):
            current["path"] = line.removeprefix("rename to ").strip()
            current["status"] = "renamed"
        elif line.startswith("+++ b/") and not current.get("path"):
            current["path"] = line.removeprefix("+++ b/").strip()
        elif line.startswith("+") and not line.startswith("+++"):
            current["additions"] = int(current["additions"]) + 1
        elif line.startswith("-") and not line.startswith("---"):
            current["deletions"] = int(current["deletions"]) + 1
    if current is not None:
        current["text"] = "\n".join(chunks)
        files.append(current)
    return files


def run_upgrade_dry_run(*, repo_root: Path, patch_path: Path) -> dict[str, Any]:
    resolved_repo_root = Path(repo_root).resolve()
    resolved_patch_path = Path(patch_path).resolve()
    completed = subprocess.run(
        build_git_fsmonitor_disabled_command(["apply", "--check", str(resolved_patch_path)]),
        cwd=resolved_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "ok": completed.returncode == 0,
        "checked_at": datetime.now(UTC).isoformat(),
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "patch_path": str(resolved_patch_path),
        "repo_root": str(resolved_repo_root),
    }
