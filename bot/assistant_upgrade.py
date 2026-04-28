from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from bot.assistant_home import AssistantHome
from bot.assistant_proposals import get_proposal


def resolve_approved_upgrade_patch_path(home: AssistantHome, proposal_id: str) -> Path:
    patch_path = home.root / "upgrades" / "approved" / f"{proposal_id}.patch"
    if not patch_path.exists():
        raise FileNotFoundError(str(patch_path))
    return patch_path


def read_upgrade_apply_result(home: AssistantHome, proposal_id: str) -> dict | None:
    path = home.root / "upgrades" / "applied" / f"{proposal_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_upgrade_apply_failure(home: AssistantHome, proposal_id: str) -> dict | None:
    path = home.root / "upgrades" / "applied" / f"{proposal_id}.last-error.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_upgrade_apply_failure(
    home: AssistantHome,
    proposal_id: str,
    *,
    repo_root: Path,
    patch_path: Path,
    error: str,
) -> dict:
    result = {
        "id": proposal_id,
        "status": "failed",
        "repo_root": str(Path(repo_root).resolve()),
        "patch_path": str(Path(patch_path).resolve()),
        "failed_at": datetime.now(UTC).isoformat(),
        "error": str(error or "").strip(),
    }
    audit_path = home.root / "upgrades" / "applied" / f"{proposal_id}.last-error.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def apply_approved_upgrade(home: AssistantHome, proposal_id: str, *, repo_root: Path) -> dict:
    proposal = get_proposal(home, proposal_id)
    if proposal.get("status") != "approved":
        raise PermissionError("proposal_not_approved")
    patch_path = resolve_approved_upgrade_patch_path(home, proposal_id)
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
