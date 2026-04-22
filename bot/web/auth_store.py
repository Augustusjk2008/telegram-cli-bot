"""Web 账号、注册码和内存 session 存储。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROLE_MEMBER = "member"
ROLE_GUEST = "guest"

CAP_VIEW_BOTS = "view_bots"
CAP_VIEW_BOT_STATUS = "view_bot_status"
CAP_VIEW_FILE_TREE = "view_file_tree"
CAP_MUTATE_BROWSE_STATE = "mutate_browse_state"
CAP_VIEW_CHAT_HISTORY = "view_chat_history"
CAP_VIEW_CHAT_TRACE = "view_chat_trace"
CAP_READ_FILE_CONTENT = "read_file_content"
CAP_WRITE_FILES = "write_files"
CAP_CHAT_SEND = "chat_send"
CAP_TERMINAL_EXEC = "terminal_exec"
CAP_DEBUG_EXEC = "debug_exec"
CAP_GIT_OPS = "git_ops"
CAP_RUN_SCRIPTS = "run_scripts"
CAP_MANAGE_CLI_PARAMS = "manage_cli_params"
CAP_ADMIN_OPS = "admin_ops"

GUEST_CAPABILITIES = frozenset(
    {
        CAP_VIEW_BOTS,
        CAP_VIEW_BOT_STATUS,
        CAP_VIEW_FILE_TREE,
        CAP_VIEW_CHAT_HISTORY,
    }
)

MEMBER_CAPABILITIES = frozenset(
    {
        *GUEST_CAPABILITIES,
        CAP_MUTATE_BROWSE_STATE,
        CAP_VIEW_CHAT_TRACE,
        CAP_READ_FILE_CONTENT,
        CAP_WRITE_FILES,
        CAP_CHAT_SEND,
        CAP_TERMINAL_EXEC,
        CAP_DEBUG_EXEC,
        CAP_GIT_OPS,
        CAP_RUN_SCRIPTS,
        CAP_MANAGE_CLI_PARAMS,
        CAP_ADMIN_OPS,
    }
)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
_PASSWORD_MIN_LENGTH = 3
_PBKDF2_ITERATIONS = 120_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def capabilities_for_role(role: str) -> frozenset[str]:
    if role == ROLE_GUEST:
        return GUEST_CAPABILITIES
    return MEMBER_CAPABILITIES


class AuthStoreError(Exception):
    """账号存储层错误。"""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}


@dataclass(frozen=True)
class WebAccount:
    account_id: str
    username: str
    role: str
    disabled: bool = False


@dataclass(frozen=True)
class WebAuthSession:
    token: str
    account: WebAccount
    created_at: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)


class WebAuthStore:
    def __init__(self, users_path: Path | str, register_codes_path: Path | str) -> None:
        self.users_path = Path(users_path)
        self.register_codes_path = Path(register_codes_path)
        self._lock = threading.RLock()
        self._sessions: dict[str, WebAuthSession] = {}

    def create_guest_session(self) -> WebAuthSession:
        return self._issue_session(self._guest_account())

    def register_member(self, username: str, password: str, register_code: str) -> WebAuthSession:
        normalized_username = self._normalize_username(username)
        resolved_password = self._validate_password(password)
        resolved_code = str(register_code or "").strip()
        if not resolved_code:
            self._raise(400, "register_code_required", "注册码不能为空")

        with self._lock:
            users_data = self._read_json(self.users_path)
            user_items = self._items(users_data)
            if self._find_user_item(user_items, normalized_username) is not None:
                self._raise(409, "username_taken", "用户名已存在")

            codes_data = self._read_json(self.register_codes_path)
            code_items = self._items(codes_data)
            code_item = self._find_register_code_item(code_items, resolved_code)
            if code_item is None:
                self._raise(400, "invalid_register_code", "注册码无效")
            if bool(code_item.get("disabled")):
                self._raise(403, "register_code_disabled", "注册码已停用")
            if str(code_item.get("used_by") or "").strip():
                self._raise(409, "register_code_used", "注册码已被使用")

            salt = secrets.token_bytes(16)
            hashed_password = self._hash_password(resolved_password, salt, _PBKDF2_ITERATIONS)
            account_id = f"member_{secrets.token_hex(8)}"
            created_at = _utc_now()
            user_items.append(
                {
                    "account_id": account_id,
                    "username": str(username or "").strip(),
                    "username_key": normalized_username,
                    "role": ROLE_MEMBER,
                    "disabled": False,
                    "password_salt": salt.hex(),
                    "password_hash": hashed_password,
                    "password_iterations": _PBKDF2_ITERATIONS,
                    "created_at": created_at,
                }
            )
            code_item["used_by"] = str(username or "").strip()
            code_item["used_at"] = created_at
            self._write_json(self.users_path, users_data)
            self._write_json(self.register_codes_path, codes_data)
        return self._issue_session(
            WebAccount(
                account_id=account_id,
                username=str(username or "").strip(),
                role=ROLE_MEMBER,
                disabled=False,
            )
        )

    def login_member(self, username: str, password: str) -> WebAuthSession:
        normalized_username = self._normalize_username(username)
        resolved_password = self._validate_password(password)

        with self._lock:
            users_data = self._read_json(self.users_path)
            user_item = self._find_user_item(self._items(users_data), normalized_username)
            if user_item is None:
                self._raise(401, "invalid_credentials", "用户名或密码错误")
            if bool(user_item.get("disabled")):
                self._raise(403, "account_disabled", "账号已停用")

            salt_hex = str(user_item.get("password_salt") or "").strip()
            hash_hex = str(user_item.get("password_hash") or "").strip()
            if not salt_hex or not hash_hex:
                self._raise(500, "invalid_account_store", "账号数据损坏")
            iterations = int(user_item.get("password_iterations") or _PBKDF2_ITERATIONS)
            expected = self._hash_password(resolved_password, bytes.fromhex(salt_hex), iterations)
            if not secrets.compare_digest(expected, hash_hex):
                self._raise(401, "invalid_credentials", "用户名或密码错误")

        return self._issue_session(self._account_from_item(user_item))

    def get_session(self, token: str) -> WebAuthSession | None:
        resolved_token = str(token or "").strip()
        if not resolved_token:
            return None
        with self._lock:
            return self._sessions.get(resolved_token)

    def delete_session(self, token: str) -> None:
        resolved_token = str(token or "").strip()
        if not resolved_token:
            return
        with self._lock:
            self._sessions.pop(resolved_token, None)

    def has_member_accounts(self) -> bool:
        with self._lock:
            users_data = self._read_json(self.users_path)
            return any(item.get("role") == ROLE_MEMBER for item in self._items(users_data))

    def can_bootstrap_without_auth(self) -> bool:
        return not self.has_member_accounts()

    def _issue_session(self, account: WebAccount) -> WebAuthSession:
        token = f"web_sess_{secrets.token_urlsafe(24)}"
        session = WebAuthSession(
            token=token,
            account=account,
            created_at=_utc_now(),
            capabilities=tuple(sorted(capabilities_for_role(account.role))),
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def _guest_account(self) -> WebAccount:
        return WebAccount(
            account_id="guest",
            username="guest",
            role=ROLE_GUEST,
            disabled=False,
        )

    def _normalize_username(self, username: str) -> str:
        resolved = str(username or "").strip()
        if not resolved:
            self._raise(400, "invalid_username", "用户名不能为空")
        if resolved.lower() == ROLE_GUEST:
            self._raise(400, "reserved_username", "guest 为保留用户名")
        if not _USERNAME_RE.fullmatch(resolved):
            self._raise(400, "invalid_username", "用户名仅支持字母、数字、._-，长度 2-32")
        return resolved.casefold()

    def _validate_password(self, password: str) -> str:
        resolved = str(password or "")
        if len(resolved) < _PASSWORD_MIN_LENGTH:
            self._raise(400, "invalid_password", "密码至少 3 位")
        return resolved

    def _account_from_item(self, item: dict[str, Any]) -> WebAccount:
        return WebAccount(
            account_id=str(item.get("account_id") or ""),
            username=str(item.get("username") or ""),
            role=str(item.get("role") or ROLE_MEMBER),
            disabled=bool(item.get("disabled")),
        )

    def _find_user_item(self, items: list[dict[str, Any]], normalized_username: str) -> dict[str, Any] | None:
        for item in items:
            username_key = str(item.get("username_key") or item.get("username") or "").strip().casefold()
            if username_key == normalized_username:
                return item
        return None

    def _find_register_code_item(self, items: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
        for item in items:
            if str(item.get("code") or "").strip() == code:
                return item
        return None

    def _hash_password(self, password: str, salt: bytes, iterations: int) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        ).hex()

    def _items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        items = data.get("items")
        if not isinstance(items, list):
            data["items"] = []
            return data["items"]
        return items

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"items": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthStoreError(
                status=500,
                code="invalid_auth_store",
                message=f"无法解析存储文件: {path.name}",
            ) from exc
        if not isinstance(data, dict):
            return {"items": []}
        if not isinstance(data.get("items"), list):
            data["items"] = []
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _raise(self, status: int, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        raise AuthStoreError(status=status, code=code, message=message, data=data)


__all__ = [
    "AuthStoreError",
    "CAP_ADMIN_OPS",
    "CAP_CHAT_SEND",
    "CAP_DEBUG_EXEC",
    "CAP_GIT_OPS",
    "CAP_MANAGE_CLI_PARAMS",
    "CAP_MUTATE_BROWSE_STATE",
    "CAP_READ_FILE_CONTENT",
    "CAP_RUN_SCRIPTS",
    "CAP_TERMINAL_EXEC",
    "CAP_VIEW_BOTS",
    "CAP_VIEW_BOT_STATUS",
    "CAP_VIEW_CHAT_HISTORY",
    "CAP_VIEW_CHAT_TRACE",
    "CAP_VIEW_FILE_TREE",
    "CAP_WRITE_FILES",
    "GUEST_CAPABILITIES",
    "MEMBER_CAPABILITIES",
    "ROLE_GUEST",
    "ROLE_MEMBER",
    "WebAccount",
    "WebAuthSession",
    "WebAuthStore",
    "capabilities_for_role",
]
