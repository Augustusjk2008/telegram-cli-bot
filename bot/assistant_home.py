from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

import yaml

ASSISTANT_SCHEMA_VERSION = 1
REQUIRED_DIRS = (
    "state/users",
    "inbox/captures",
    "memory/working",
    "memory/knowledge",
    "memory/skills",
    "proposals",
    "upgrades/pending",
    "upgrades/approved",
    "upgrades/applied",
    "evals/runs",
    "audit",
    "indexes",
    "prompts",
)


@dataclass(frozen=True)
class AssistantHome:
    workdir: Path
    root: Path
    manifest_path: Path
    assistant_id: str
    schema_version: int


def _manifest_payload(assistant_id: str) -> dict:
    return {
        "assistant_id": assistant_id,
        "schema_version": ASSISTANT_SCHEMA_VERSION,
        "min_host_version": "0.0.0",
    }


def bootstrap_assistant_home(workdir: str | Path) -> AssistantHome:
    workdir_path = Path(workdir).expanduser().resolve()
    root = workdir_path / ".assistant"
    root.mkdir(parents=True, exist_ok=True)
    for relative in REQUIRED_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)

    manifest_path = root / "manifest.yaml"
    if manifest_path.exists():
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    else:
        data = _manifest_payload(uuid.uuid4().hex)
        manifest_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return AssistantHome(
        workdir=workdir_path,
        root=root,
        manifest_path=manifest_path,
        assistant_id=str(data["assistant_id"]),
        schema_version=int(data["schema_version"]),
    )


def load_assistant_home(workdir: str | Path) -> AssistantHome:
    return bootstrap_assistant_home(workdir)
