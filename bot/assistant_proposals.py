from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from bot.assistant_home import AssistantHome


def _proposal_path(home: AssistantHome, proposal_id: str) -> Path:
    return home.root / "proposals" / f"{proposal_id}.json"


def create_proposal(home: AssistantHome, *, kind: str, title: str, body: str) -> dict:
    proposal = {
        "id": f"pr_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "title": title,
        "body": body,
        "status": "proposed",
        "created_at": datetime.now(UTC).isoformat(),
    }
    _proposal_path(home, proposal["id"]).write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return proposal


def list_proposals(home: AssistantHome, *, status: str | None = None) -> list[dict]:
    items = []
    for path in sorted((home.root / "proposals").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if status and data.get("status") != status:
            continue
        items.append(data)
    return items


def set_proposal_status(home: AssistantHome, proposal_id: str, status: str, *, reviewer: str) -> dict:
    path = _proposal_path(home, proposal_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["reviewed_by"] = reviewer
    data["reviewed_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
