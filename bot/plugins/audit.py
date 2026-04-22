from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def append_plugin_audit_event(repo_root: Path, event: dict[str, Any]) -> None:
    audit_dir = repo_root / ".plugins" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl"
    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **event,
    }
    with (audit_dir / filename).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
