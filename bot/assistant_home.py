from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

import yaml

ASSISTANT_SCHEMA_VERSION = 1
REQUIRED_DIRS = (
    "state/users",
    "state/cron",
    "inbox/captures",
    "memory/working",
    "memory/knowledge",
    "memory/skills",
    "automation/jobs",
    "proposals",
    "upgrades/pending",
    "upgrades/approved",
    "upgrades/applied",
    "evals/runs",
    "audit",
    "audit/cron",
    "audit/dream",
    "indexes",
    "prompts",
)


@dataclass(frozen=True)
class AssistantHome:
    workdir: Path
    root: Path
    manifest_path: Path
    agents_path: Path
    claude_path: Path
    assistant_id: str
    schema_version: int


def _manifest_payload(assistant_id: str) -> dict:
    return {
        "assistant_id": assistant_id,
        "schema_version": ASSISTANT_SCHEMA_VERSION,
        "min_host_version": "0.0.0",
    }


def _migrate_manifest(data: dict) -> tuple[dict, bool]:
    migrated = dict(data or {})
    changed = False

    assistant_id = str(migrated.get("assistant_id") or "").strip()
    if not assistant_id:
        migrated["assistant_id"] = uuid.uuid4().hex
        changed = True

    try:
        schema_version = int(migrated.get("schema_version", 0) or 0)
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version < ASSISTANT_SCHEMA_VERSION:
        migrated["schema_version"] = ASSISTANT_SCHEMA_VERSION
        changed = True
    else:
        migrated["schema_version"] = schema_version

    if "min_host_version" not in migrated:
        migrated["min_host_version"] = "0.0.0"
        changed = True

    return migrated, changed


def bootstrap_assistant_home(workdir: str | Path) -> AssistantHome:
    workdir_path = Path(workdir).expanduser().resolve()
    root = workdir_path / ".assistant"
    root.mkdir(parents=True, exist_ok=True)
    for relative in REQUIRED_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)

    manifest_path = root / "manifest.yaml"
    if manifest_path.exists():
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        data, changed = _migrate_manifest(data)
    else:
        data = _manifest_payload(uuid.uuid4().hex)
        changed = True

    if changed:
        manifest_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return AssistantHome(
        workdir=workdir_path,
        root=root,
        manifest_path=manifest_path,
        agents_path=workdir_path / "AGENTS.md",
        claude_path=workdir_path / "CLAUDE.md",
        assistant_id=str(data["assistant_id"]),
        schema_version=int(data["schema_version"]),
    )


def load_assistant_home(workdir: str | Path) -> AssistantHome:
    return bootstrap_assistant_home(workdir)
