from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _normalize_for_key(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_for_key(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_key(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(_normalize_for_key(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_source_identity(input_payload: dict[str, Any]) -> str:
    payload = dict(input_payload or {})
    path_value = payload.pop("path", None)
    if path_value is None:
        return _stable_json({"input": payload})
    return _stable_json({"path": str(Path(str(path_value)).resolve()), "options": payload})


def build_source_fingerprint(input_payload: dict[str, Any]) -> str:
    payload = dict(input_payload or {})
    path_value = payload.pop("path", None)
    if path_value is None:
        return _stable_json({"input": payload})
    path = Path(str(path_value)).resolve()
    stat = path.stat()
    return _stable_json(
        {
            "path": str(path),
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "options": payload,
        }
    )


@dataclass
class PluginViewSessionRecord:
    bot_alias: str
    plugin_id: str
    view_id: str
    session_id: str
    renderer: str
    source_identity: str
    source_fingerprint: str
    resolved_input: dict[str, Any]
    opened_payload: dict[str, Any]
    last_window_request: dict[str, Any] | None = None


class PluginViewSessionStore:
    def __init__(self) -> None:
        self._records_by_session: dict[str, PluginViewSessionRecord] = {}
        self._records_by_cache_key: dict[str, PluginViewSessionRecord] = {}
        self._records_by_identity: dict[str, PluginViewSessionRecord] = {}

    @staticmethod
    def build_cache_key(bot_alias: str, plugin_id: str, view_id: str, source_fingerprint: str) -> str:
        return _stable_json(
            {
                "botAlias": bot_alias,
                "pluginId": plugin_id,
                "viewId": view_id,
                "sourceFingerprint": source_fingerprint,
            }
        )

    @staticmethod
    def build_identity_key(bot_alias: str, source_identity: str) -> str:
        return _stable_json({"botAlias": bot_alias, "sourceIdentity": source_identity})

    def get_cached(self, cache_key: str) -> PluginViewSessionRecord | None:
        return self._records_by_cache_key.get(cache_key)

    def get(self, session_id: str) -> PluginViewSessionRecord:
        return self._records_by_session[session_id]

    def get_optional(self, session_id: str) -> PluginViewSessionRecord | None:
        return self._records_by_session.get(session_id)

    def replace(self, record: PluginViewSessionRecord) -> PluginViewSessionRecord | None:
        identity_key = self.build_identity_key(record.bot_alias, record.source_identity)
        stale = self._records_by_identity.get(identity_key)
        if stale is not None:
            self.remove(stale.session_id)
        cache_key = self.build_cache_key(record.bot_alias, record.plugin_id, record.view_id, record.source_fingerprint)
        self._records_by_session[record.session_id] = record
        self._records_by_cache_key[cache_key] = record
        self._records_by_identity[identity_key] = record
        return stale

    def remember_window_request(self, session_id: str, request_payload: dict[str, Any]) -> None:
        record = self._records_by_session.get(session_id)
        if record is None:
            return
        record.last_window_request = dict(request_payload or {})

    def remove(self, session_id: str) -> PluginViewSessionRecord | None:
        record = self._records_by_session.pop(session_id, None)
        if record is None:
            return None
        cache_key = self.build_cache_key(record.bot_alias, record.plugin_id, record.view_id, record.source_fingerprint)
        self._records_by_cache_key.pop(cache_key, None)
        identity_key = self.build_identity_key(record.bot_alias, record.source_identity)
        current = self._records_by_identity.get(identity_key)
        if current is not None and current.session_id == session_id:
            self._records_by_identity.pop(identity_key, None)
        return record

    def clear_plugin(self, plugin_id: str, *, bot_alias: str | None = None) -> list[PluginViewSessionRecord]:
        removed: list[PluginViewSessionRecord] = []
        for record in list(self._records_by_session.values()):
            if record.plugin_id != plugin_id:
                continue
            if bot_alias is not None and record.bot_alias != bot_alias:
                continue
            removed_record = self.remove(record.session_id)
            if removed_record is not None:
                removed.append(removed_record)
        return removed

    def records(self) -> list[PluginViewSessionRecord]:
        return list(self._records_by_session.values())
