from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from bot.assistant_home import AssistantHome


def apply_approved_upgrade(home: AssistantHome, proposal_id: str, *, repo_root: Path) -> dict:
    patch_path = home.root / "upgrades" / "approved" / f"{proposal_id}.patch"
    repo_root = Path(repo_root).resolve()

    subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    result = {
        "id": proposal_id,
        "status": "applied",
        "patch_path": str(patch_path),
        "repo_root": str(repo_root),
        "applied_at": datetime.now(UTC).isoformat(),
    }
    applied_path = home.root / "upgrades" / "applied" / f"{proposal_id}.json"
    applied_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    proposal_path = home.root / "proposals" / f"{proposal_id}.json"
    if proposal_path.exists():
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal["status"] = "applied"
        proposal["applied_at"] = result["applied_at"]
        proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")

    return result
