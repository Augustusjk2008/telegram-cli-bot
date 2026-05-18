"""Web announcement storage."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
from pathlib import Path
from typing import Any


_CATEGORIES = {"release", "feature", "fix", "maintenance", "notice"}
_SEVERITIES = {"info", "success", "warning", "danger"}


def _now_announcement_datetime() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _now_iso() -> str:
    return _now_announcement_datetime().isoformat(timespec="seconds")


def _announcement_id_base(published_at: datetime) -> str:
    return f"ann-{published_at.strftime('%Y-%m-%d-%H-%M')}"


def _next_announcement_id(existing_ids: set[str], base_id: str) -> str:
    if base_id not in existing_ids:
        return base_id
    index = 2
    while True:
        candidate = f"{base_id}-{index:02d}"
        if candidate not in existing_ids:
            return candidate
        index += 1


class AnnouncementStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def list_for_user(self, account_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            items = self._sorted_items(data)
            latest_id = items[0]["id"] if items else ""
            read = data.get("reads", {}).get(str(account_id or "").strip(), {})
            last_seen_id = str(read.get("last_seen_id") or "")
        return {
            "items": items,
            "latest_id": latest_id,
            "last_seen_id": last_seen_id,
            "has_unseen": bool(latest_id and latest_id != last_seen_id),
        }

    def mark_seen(self, account_id: str, latest_id: str) -> dict[str, Any]:
        account_key = str(account_id or "").strip()
        resolved_id = str(latest_id or "").strip()
        if not account_key:
            raise ValueError("账号 ID 不能为空")
        with self._lock:
            data = self._load()
            ids = {str(item.get("id") or "") for item in data.get("items", [])}
            if resolved_id and resolved_id not in ids:
                raise ValueError("公告不存在")
            data.setdefault("reads", {})[account_key] = {
                "last_seen_id": resolved_id,
                "seen_at": _now_iso(),
            }
            data["updated_at"] = _now_iso()
            self._save(data)
        return self.list_for_user(account_key)

    def upsert_item(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate_item(item)
        with self._lock:
            data = self._load()
            items = [current for current in data.get("items", []) if current.get("id") != normalized["id"]]
            items.append(normalized)
            data["items"] = items
            data["updated_at"] = _now_iso()
            self._save(data)
        return deepcopy(normalized)

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        published_at = _now_announcement_datetime().replace(second=0, microsecond=0)
        with self._lock:
            data = self._load()
            existing_ids = {str(current.get("id") or "") for current in data.get("items", []) if isinstance(current, dict)}
            generated = dict(item)
            generated["id"] = _next_announcement_id(existing_ids, _announcement_id_base(published_at))
            generated["published_at"] = published_at.isoformat(timespec="seconds")
            normalized = self._validate_item(generated)
            data.setdefault("items", []).append(normalized)
            data["updated_at"] = _now_iso()
            self._save(data)
        return deepcopy(normalized)

    def delete_item(self, item_id: str) -> bool:
        resolved_id = str(item_id or "").strip()
        with self._lock:
            data = self._load()
            before = len(data.get("items", []))
            data["items"] = [item for item in data.get("items", []) if str(item.get("id") or "") != resolved_id]
            changed = len(data["items"]) != before
            if changed:
                data["updated_at"] = _now_iso()
                self._save(data)
        return changed

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "updated_at": _now_iso(), "items": [], "reads": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", 1)
        data.setdefault("updated_at", _now_iso())
        if not isinstance(data.get("items"), list):
            data["items"] = []
        if not isinstance(data.get("reads"), dict):
            data["reads"] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _sorted_items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        items = [self._validate_item(item) for item in data.get("items", []) if isinstance(item, dict)]
        return sorted(items, key=lambda item: (item["published_at"], item["id"]), reverse=True)

    def _validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        published_at = item.get("published_at", item.get("publishedAt", ""))
        normalized = {
            "id": str(item.get("id", "")).strip(),
            "published_at": str(published_at).strip(),
            "publisher": str(item.get("publisher", "")).strip(),
            "title": str(item.get("title", "")).strip(),
            "category": str(item.get("category", "")).strip(),
            "severity": str(item.get("severity", "")).strip(),
            "summary": str(item.get("summary", "")).strip(),
            "sections": item.get("sections", []),
        }
        if not normalized["id"]:
            raise ValueError("公告 id 不能为空")
        if normalized["category"] not in _CATEGORIES:
            raise ValueError("公告分类无效")
        if normalized["severity"] not in _SEVERITIES:
            raise ValueError("公告级别无效")
        try:
            datetime.fromisoformat(normalized["published_at"])
        except ValueError as exc:
            raise ValueError("公告发布时间无效") from exc
        if not normalized["publisher"] or not normalized["title"] or not normalized["summary"]:
            raise ValueError("公告发布者、标题、摘要不能为空")
        sections = []
        if isinstance(normalized["sections"], list):
            for section in normalized["sections"]:
                if not isinstance(section, dict):
                    continue
                label = str(section.get("label", "")).strip()
                entries = [str(value).strip() for value in section.get("items", []) if str(value).strip()]
                if label and entries:
                    sections.append({"label": label, "items": entries})
        normalized["sections"] = sections
        return normalized
