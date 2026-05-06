from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.assistant_home import AssistantHome


def _day_path(home: AssistantHome, created_at: datetime | None = None) -> Path:
    stamp = (created_at or datetime.now(UTC)).strftime("%Y%m%d")
    return home.root / "audit" / "admin" / f"{stamp}.jsonl"


def _clip(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def summarize_request(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    summary: dict[str, Any] = {}
    for key, value in body.items():
        lowered = key.lower()
        if lowered in {"token", "password", "secret", "api_key"}:
            summary[key] = "***"
        elif isinstance(value, str):
            summary[key] = _clip(value, 200)
        elif isinstance(value, list):
            summary[key] = {"count": len(value), "items": [_clip(item, 80) for item in value[:5]]}
        elif isinstance(value, dict):
            summary[key] = {"keys": sorted(str(item) for item in value.keys())[:20]}
        else:
            summary[key] = value
    return summary


def write_admin_audit(home: AssistantHome, record: dict[str, Any]) -> dict[str, Any]:
    created_at = datetime.now(UTC)
    payload = {
        "id": uuid.uuid4().hex,
        "created_at": created_at.isoformat(),
        "account_id": str(record.get("account_id") or ""),
        "user_id": int(record.get("user_id") or 0),
        "username": str(record.get("username") or ""),
        "method": str(record.get("method") or ""),
        "path": str(record.get("path") or ""),
        "action": str(record.get("action") or ""),
        "target": record.get("target") if isinstance(record.get("target"), dict) else {},
        "request_summary": (
            record.get("request_summary") if isinstance(record.get("request_summary"), dict) else {}
        ),
        "status_code": int(record.get("status_code") or 0),
        "ok": bool(record.get("ok")),
        "error_code": str(record.get("error_code") or ""),
        "error_message": _clip(record.get("error_message") or "", 500),
        "elapsed_ms": int(record.get("elapsed_ms") or 0),
    }
    path = _day_path(home, created_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")
    return payload


def list_admin_audit(
    home: AssistantHome,
    *,
    limit: int = 50,
    action: str = "",
    resource: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    root = home.root / "audit" / "admin"
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.jsonl"), reverse=True):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action and item.get("action") != action:
                continue
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            if resource and target.get("resource") != resource:
                continue
            if status == "ok" and not item.get("ok"):
                continue
            if status == "failed" and item.get("ok"):
                continue
            items.append(item)
            if len(items) >= max(1, int(limit)):
                return items
    return items
