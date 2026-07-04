"""Web user to bot permission storage."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class BotPermissionStore:
    MEMBER_BOT_LIMIT = 10

    def __init__(self, path: Path | str, *, legacy_path: Path | str | None = None) -> None:
        self.path = Path(path)
        self.root = self.path
        self.legacy_path = Path(legacy_path) if legacy_path is not None else None
        self._directory_mode = self.path.suffix == ""
        if self._directory_mode:
            self.accounts_dir = self.root / "accounts"
            self.bots_path = self.root / "bots.json"
        else:
            self.accounts_dir = self.path.parent / "accounts"
            self.bots_path = self.path
        self._lock = threading.RLock()
        self.ensure_exists()

    def ensure_exists(self) -> None:
        with self._lock:
            if self._directory_mode:
                self.accounts_dir.mkdir(parents=True, exist_ok=True)
                if self.legacy_path is not None and self.legacy_path.exists() and not any(self.accounts_dir.glob("*.json")):
                    legacy = self._read_legacy_path()
                    for account_id, item in self._users(legacy).items():
                        if isinstance(item, dict):
                            self._write_account(str(account_id), item)
                    if not self.bots_path.exists():
                        self._write_bots(self._bots(legacy))
                    return
                if not self.bots_path.exists():
                    self._write_bots({})
                return
            if self.path.exists():
                self._read()
                return
            self._write({"version": 1, "users": {}, "bots": {}})

    def allowed_bots_for_account(self, account_id: str) -> set[str]:
        account_key = str(account_id or "").strip()
        if not account_key:
            return set()
        with self._lock:
            item = self._read_account(account_key)
            if not isinstance(item, dict):
                return set()
            return {
                normalized
                for alias in item.get("allowed_bots", [])
                if (normalized := self._normalize_alias(alias))
            }

    def can_operate_bot(self, account_id: str, alias: str) -> bool:
        normalized_alias = self._normalize_alias(alias)
        return bool(normalized_alias and normalized_alias in self.allowed_bots_for_account(account_id))

    def grant_bot_to_account(self, account_id: str, alias: str) -> dict[str, Any]:
        allowed = self.allowed_bots_for_account(account_id)
        if normalized := self._normalize_alias(alias):
            allowed.add(normalized)
        return self.set_allowed_bots(account_id, sorted(allowed))

    def set_allowed_bots(self, account_id: str, allowed_bots: list[str]) -> dict[str, Any]:
        account_key = str(account_id or "").strip()
        if not account_key:
            raise ValueError("账号 ID 不能为空")
        aliases = sorted(
            {
                normalized
                for alias in allowed_bots
                if (normalized := self._normalize_alias(alias))
            }
        )
        with self._lock:
            if self._directory_mode:
                current = self._read_account(account_key)
                self._write_account(account_key, {**current, "allowed_bots": aliases})
            else:
                data = self._read()
                users = self._users(data)
                current = users.get(account_key) if isinstance(users.get(account_key), dict) else {}
                users[account_key] = {**current, "allowed_bots": aliases}
                self._write(data)
        return {"account_id": account_key, "allowed_bots": aliases}

    def list_user_permissions(self) -> dict[str, Any]:
        with self._lock:
            users = self._read_users()
            items = [
                {
                    "account_id": account_id,
                    "allowed_bots": sorted(
                        normalized
                        for alias in item.get("allowed_bots", [])
                        if (normalized := self._normalize_alias(alias))
                    ),
                    "updated_at": str(item.get("updated_at") or ""),
                }
                for account_id, item in users.items()
                if isinstance(item, dict)
            ]
        items.sort(key=lambda item: item["account_id"])
        return {"items": items}

    def list_user_permission_summaries(self) -> dict[str, Any]:
        with self._lock:
            if self._directory_mode:
                users = self._read_users()
                bots = self._read_bots()
            else:
                data = self._read()
                users = self._users(data)
                bots = self._bots(data)
            owned_by_account: dict[str, list[str]] = {}
            for alias, item in bots.items():
                if not isinstance(item, dict):
                    continue
                owner = str(item.get("owner_account_id") or "").strip()
                normalized_alias = self._normalize_alias(alias)
                if not owner or not normalized_alias:
                    continue
                owned_by_account.setdefault(owner, []).append(normalized_alias)

            account_ids = sorted(set(users) | set(owned_by_account))
            items = []
            for account_id in account_ids:
                raw_item = users.get(account_id)
                item = raw_item if isinstance(raw_item, dict) else {}
                owned_bots = sorted(set(owned_by_account.get(account_id, [])))
                items.append(
                    {
                        "account_id": account_id,
                        "allowed_bots": sorted(
                            normalized
                            for alias in item.get("allowed_bots", [])
                            if (normalized := self._normalize_alias(alias))
                        ),
                        "owned_bots": owned_bots,
                        "owned_bot_count": len(owned_bots),
                        "bot_create_limit": self.MEMBER_BOT_LIMIT,
                        "updated_at": str(item.get("updated_at") or ""),
                    }
                )
        items.sort(key=lambda item: item["account_id"])
        return {"items": items}

    def set_bot_owner(self, alias: str, account_id: str, *, grant_owner: bool = True) -> dict[str, Any]:
        normalized_alias = self._normalize_alias(alias)
        account_key = str(account_id or "").strip()
        if not normalized_alias:
            raise ValueError("Bot 别名不能为空")
        if not account_key:
            raise ValueError("账号 ID 不能为空")
        with self._lock:
            if self._directory_mode:
                bots = self._read_bots()
                current = bots.get(normalized_alias) if isinstance(bots.get(normalized_alias), dict) else {}
                bots[normalized_alias] = {**current, "owner_account_id": account_key}
                self._write_bots(bots)
            else:
                data = self._read()
                bots = self._bots(data)
                current = bots.get(normalized_alias) if isinstance(bots.get(normalized_alias), dict) else {}
                bots[normalized_alias] = {**current, "owner_account_id": account_key}
                self._write(data)
        if grant_owner:
            self.grant_bot_to_account(account_key, normalized_alias)
        return {"alias": normalized_alias, "owner_account_id": account_key}

    def bot_owner(self, alias: str) -> str:
        normalized_alias = self._normalize_alias(alias)
        if not normalized_alias:
            return ""
        with self._lock:
            item = self._read_bots().get(normalized_alias)
        if not isinstance(item, dict):
            return ""
        return str(item.get("owner_account_id") or "").strip()

    def owned_bot_aliases(self, account_id: str) -> set[str]:
        account_key = str(account_id or "").strip()
        if not account_key:
            return set()
        with self._lock:
            return {
                alias
                for alias, item in self._read_bots().items()
                if isinstance(item, dict) and str(item.get("owner_account_id") or "").strip() == account_key
            }

    def count_owned_bots(self, account_id: str) -> int:
        return len(self.owned_bot_aliases(account_id))

    def assert_can_create_bot(self, account_id: str, *, is_local_admin: bool) -> None:
        if is_local_admin:
            return
        if self.count_owned_bots(account_id) >= self.MEMBER_BOT_LIMIT:
            raise ValueError(f"普通用户最多只能创建 {self.MEMBER_BOT_LIMIT} 个 Bot")

    def remove_account(self, account_id: str) -> None:
        account_key = str(account_id or "").strip()
        if not account_key:
            return
        with self._lock:
            if self._directory_mode:
                self._account_path(account_key).unlink(missing_ok=True)
            else:
                data = self._read()
                self._users(data).pop(account_key, None)
                self._write(data)

    def remove_bot_owner(self, alias: str) -> None:
        normalized_alias = self._normalize_alias(alias)
        if not normalized_alias:
            return
        with self._lock:
            if self._directory_mode:
                bots = self._read_bots()
                bots.pop(normalized_alias, None)
                self._write_bots(bots)
                for account_id, item in self._read_users().items():
                    item["allowed_bots"] = [
                        current
                        for current in item.get("allowed_bots", [])
                        if self._normalize_alias(current) != normalized_alias
                    ]
                    self._write_account(account_id, item)
                return
            data = self._read()
            self._bots(data).pop(normalized_alias, None)
            for item in self._users(data).values():
                if not isinstance(item, dict):
                    continue
                item["allowed_bots"] = [
                    current
                    for current in item.get("allowed_bots", [])
                    if self._normalize_alias(current) != normalized_alias
                ]
            self._write(data)

    def rename_bot(self, old_alias: str, new_alias: str) -> None:
        normalized_old = self._normalize_alias(old_alias)
        normalized_new = self._normalize_alias(new_alias)
        if not normalized_old or not normalized_new or normalized_old == normalized_new:
            return
        with self._lock:
            if self._directory_mode:
                bots = self._read_bots()
                if normalized_old in bots:
                    bots[normalized_new] = bots.pop(normalized_old)
                    self._write_bots(bots)
                for account_id, item in self._read_users().items():
                    item["allowed_bots"] = self._renamed_allowed_bots(item, normalized_old, normalized_new)
                    self._write_account(account_id, item)
                return
            data = self._read()
            bots = self._bots(data)
            if normalized_old in bots:
                current = bots.pop(normalized_old)
                bots[normalized_new] = current
            for item in self._users(data).values():
                if not isinstance(item, dict):
                    continue
                item["allowed_bots"] = self._renamed_allowed_bots(item, normalized_old, normalized_new)
            self._write(data)

    def _renamed_allowed_bots(self, item: dict[str, Any], old_alias: str, new_alias: str) -> list[str]:
        rewritten: list[str] = []
        for alias in item.get("allowed_bots", []):
            normalized_alias = self._normalize_alias(alias)
            if not normalized_alias:
                continue
            rewritten.append(new_alias if normalized_alias == old_alias else normalized_alias)
        return sorted(set(rewritten))

    def _read(self) -> dict[str, Any]:
        if self._directory_mode:
            return {"version": 1, "users": self._read_users(), "bots": self._read_bots()}
        if not self.path.exists():
            return {"version": 1, "users": {}, "bots": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"无法解析权限配置文件: {self.path.name}") from exc
        return self._normalize_legacy_data(data)

    def _write(self, data: dict[str, Any]) -> None:
        if self._directory_mode:
            for account_id, item in self._users(data).items():
                if isinstance(item, dict):
                    self._write_account(str(account_id), item)
            self._write_bots(self._bots(data))
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _normalize_legacy_data(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            data = {"version": 1, "users": {}, "bots": {}}
        data["version"] = 1
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        if not isinstance(data.get("bots"), dict):
            data["bots"] = {}
        return data

    def _read_users(self) -> dict[str, Any]:
        if not self._directory_mode:
            return self._users(self._read())
        users: dict[str, Any] = {}
        if self.accounts_dir.exists():
            for path in sorted(self.accounts_dir.glob("*.json")):
                if not path.is_file():
                    continue
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"无法解析权限配置文件: {path.name}") from exc
                if isinstance(item, dict):
                    account_id = str(item.get("account_id") or path.stem).strip()
                    if account_id:
                        users[account_id] = item
        if not users and self.legacy_path is not None and self.legacy_path.exists():
            return self._users(self._read_legacy_path())
        return users

    def _read_account(self, account_id: str) -> dict[str, Any]:
        if not self._directory_mode:
            item = self._users(self._read()).get(account_id)
            return dict(item) if isinstance(item, dict) else {}
        path = self._account_path(account_id)
        if path.exists():
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"无法解析权限配置文件: {path.name}") from exc
            return dict(item) if isinstance(item, dict) else {}
        if self.legacy_path is not None and self.legacy_path.exists():
            item = self._users(self._read_legacy_path()).get(account_id)
            return dict(item) if isinstance(item, dict) else {}
        return {}

    def _write_account(self, account_id: str, item: dict[str, Any]) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "account_id": account_id,
            "allowed_bots": sorted(
                normalized
                for alias in item.get("allowed_bots", [])
                if (normalized := self._normalize_alias(alias))
            ),
            "updated_at": str(item.get("updated_at") or ""),
        }
        self._write_json(self._account_path(account_id), payload)

    def _read_bots(self) -> dict[str, Any]:
        if not self._directory_mode:
            return self._bots(self._read())
        if self.bots_path.exists():
            try:
                data = json.loads(self.bots_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"无法解析权限配置文件: {self.bots_path.name}") from exc
            if isinstance(data, dict) and isinstance(data.get("bots"), dict):
                return data["bots"]
        if self.legacy_path is not None and self.legacy_path.exists():
            return self._bots(self._read_legacy_path())
        return {}

    def _write_bots(self, bots: dict[str, Any]) -> None:
        self._write_json(self.bots_path, {"version": 1, "bots": bots})

    def _read_legacy_path(self) -> dict[str, Any]:
        if self.legacy_path is None or not self.legacy_path.exists():
            return {"version": 1, "users": {}, "bots": {}}
        try:
            data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"无法解析权限配置文件: {self.legacy_path.name}") from exc
        return self._normalize_legacy_data(data)

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def _account_path(self, account_id: str) -> Path:
        return self.accounts_dir / f"{account_id}.json"

    def _users(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        return data["users"]

    def _bots(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data.get("bots"), dict):
            data["bots"] = {}
        return data["bots"]

    def _normalize_alias(self, alias: Any) -> str:
        return str(alias or "").strip().lower()
