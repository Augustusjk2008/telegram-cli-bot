from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.assistant.home import AssistantHome
from bot.assistant.proposals import get_proposal


def _upgrade_state_dir(home: AssistantHome, state: str) -> Path:
    if state not in {"pending", "approved", "applied"}:
        raise ValueError(f"unsupported_upgrade_state:{state}")
    return home.root / "upgrades" / state


def upgrade_patch_path(home: AssistantHome, proposal_id: str, state: str) -> Path:
    return _upgrade_state_dir(home, state) / f"{proposal_id}.patch"


def upgrade_metadata_path(home: AssistantHome, proposal_id: str, state: str) -> Path:
    return _upgrade_state_dir(home, state) / f"{proposal_id}.json"


def read_upgrade_metadata(home: AssistantHome, proposal_id: str, state: str) -> dict[str, Any] | None:
    path = upgrade_metadata_path(home, proposal_id, state)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_upgrade_metadata(
    home: AssistantHome,
    proposal_id: str,
    state: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    path = upgrade_metadata_path(home, proposal_id, state)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(metadata)
    payload["id"] = str(payload.get("id") or proposal_id)
    payload["proposal_id"] = str(payload.get("proposal_id") or proposal_id)
    payload["state"] = state
    payload["patch_path"] = f"upgrades/{state}/{proposal_id}.patch"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def resolve_approved_upgrade_patch_path(home: AssistantHome, proposal_id: str) -> Path:
    patch_path = upgrade_patch_path(home, proposal_id, "approved")
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


def _git_rev_parse(repo_root: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def dirty_status_lines(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def ensure_upgrade_repo_clean(repo_root: Path) -> None:
    dirty = dirty_status_lines(Path(repo_root).resolve())
    if dirty:
        preview = "\n".join(dirty[:20])
        raise RuntimeError(f"upgrade_target_dirty\n{preview}")


def resolve_approved_upgrade_repo_root(
    home: AssistantHome,
    proposal_id: str,
    *,
    fallback_repo_root: Path,
) -> Path:
    metadata = read_upgrade_metadata(home, proposal_id, "approved")
    if metadata and metadata.get("target_repo_root"):
        return Path(str(metadata["target_repo_root"])).resolve()
    return Path(fallback_repo_root).resolve()


def approve_pending_upgrade_patch(home: AssistantHome, proposal_id: str, *, reviewer: str) -> dict[str, Any]:
    proposal = get_proposal(home, proposal_id)
    if proposal.get("status") != "approved":
        raise PermissionError("proposal_not_approved")
    pending_patch = upgrade_patch_path(home, proposal_id, "pending")
    pending_metadata = read_upgrade_metadata(home, proposal_id, "pending")
    if not pending_patch.exists():
        raise FileNotFoundError(str(pending_patch))
    if pending_metadata is None:
        raise FileNotFoundError(str(upgrade_metadata_path(home, proposal_id, "pending")))
    sensitive_hits = [str(item) for item in pending_metadata.get("sensitive_hits") or [] if str(item)]
    if sensitive_hits:
        raise PermissionError("sensitive_patch_path")

    approved_patch = upgrade_patch_path(home, proposal_id, "approved")
    approved_patch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pending_patch, approved_patch)
    metadata = dict(pending_metadata)
    metadata["approved_by"] = str(reviewer)
    metadata["approved_at"] = datetime.now(UTC).isoformat()
    return write_upgrade_metadata(home, proposal_id, "approved", metadata)


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


def write_upgrade_dry_run_result(home: AssistantHome, proposal_id: str, result: dict[str, Any]) -> dict[str, Any]:
    metadata = read_upgrade_metadata(home, proposal_id, "approved") or {}
    metadata["dry_run"] = {
        "ok": bool(result.get("ok")),
        "checked_at": str(result.get("checked_at") or ""),
        "stdout": str(result.get("stdout") or ""),
        "stderr": str(result.get("stderr") or ""),
        "repo_root": str(result.get("repo_root") or ""),
        "patch_path": str(result.get("patch_path") or ""),
    }
    return write_upgrade_metadata(home, proposal_id, "approved", metadata)


def apply_approved_upgrade(home: AssistantHome, proposal_id: str, *, repo_root: Path) -> dict:
    proposal = get_proposal(home, proposal_id)
    if proposal.get("status") != "approved":
        raise PermissionError("proposal_not_approved")
    patch_path = resolve_approved_upgrade_patch_path(home, proposal_id)
    repo_root = resolve_approved_upgrade_repo_root(home, proposal_id, fallback_repo_root=repo_root)
    approved_metadata = read_upgrade_metadata(home, proposal_id, "approved") or {}
    applied_commit_before = _git_rev_parse(repo_root, "HEAD")
    ensure_upgrade_repo_clean(repo_root)

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
        "target_repo_root": str(repo_root),
        "base_commit": str(approved_metadata.get("base_commit") or ""),
        "applied_commit_before": applied_commit_before,
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
