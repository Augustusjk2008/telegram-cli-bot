"""Web 账号、邀请码和内存 session 存储。"""

from __future__ import annotations

import base64
import hashlib
import hmac
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
CAP_VIEW_PLUGINS = "view_plugins"
CAP_RUN_PLUGINS = "run_plugins"
CAP_ADMIN_OPS = "admin_ops"
CAP_MANAGE_REGISTER_CODES = "manage_register_codes"

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
        CAP_VIEW_PLUGINS,
        CAP_RUN_PLUGINS,
        CAP_ADMIN_OPS,
    }
)

LOCAL_ADMIN_CAPABILITIES = frozenset({*MEMBER_CAPABILITIES, CAP_MANAGE_REGISTER_CODES})

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
_PASSWORD_MIN_LENGTH = 6
_PBKDF2_ITERATIONS = 120_000
_STREAM_BLOCK_SIZE = 32


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


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
    def __init__(
        self,
        users_path: Path | str,
        register_codes_path: Path | str,
        secret_path: Path | str | None = None,
    ) -> None:
        self.users_path = Path(users_path)
        self.register_codes_path = Path(register_codes_path)
        self.secret_path = Path(secret_path) if secret_path else self.users_path.parent / ".web_auth_secret.json"
        self._lock = threading.RLock()
        self._sessions: dict[str, WebAuthSession] = {}
        self._secret: bytes | None = None

    def create_guest_session(self) -> WebAuthSession:
        return self._issue_session(self._guest_account())

    def register_member(self, username: str, password: str, register_code: str) -> WebAuthSession:
        normalized_username = self._normalize_username(username)
        resolved_username = str(username or "").strip()
        resolved_password = self._validate_password(password)
        resolved_code = str(register_code or "").strip()
        if not resolved_code:
            self._raise(400, "register_code_required", "邀请码不能为空")

        with self._lock:
            users_data = self._read_json(self.users_path)
            user_items = self._items(users_data)
            if self._find_user_item(user_items, normalized_username) is not None:
                self._raise(409, "username_taken", "用户名已存在")

            codes_data = self._read_json(self.register_codes_path)
            code_items = self._items(codes_data)
            code_item = self._find_register_code_item(code_items, resolved_code)
            if code_item is None:
                self._raise(400, "invalid_register_code", "邀请码无效")
            self._upgrade_register_code_item(code_item, plaintext_code=resolved_code)
            if bool(code_item.get("disabled")):
                self._raise(403, "register_code_disabled", "邀请码已停用")

            used_count = self._register_code_used_count(code_item)
            max_uses = self._register_code_max_uses(code_item)
            if used_count >= max_uses:
                self._raise(409, "register_code_exhausted", "邀请码已用完")

            salt = secrets.token_bytes(16)
            hashed_password = self._hash_password(resolved_password, salt, _PBKDF2_ITERATIONS)
            account_id = f"member_{secrets.token_hex(8)}"
            created_at = _utc_now()
            user_items.append(
                {
                    "account_id": account_id,
                    "username_key": self._stable_lookup_key(normalized_username),
                    "username_enc": self._encrypt_text(resolved_username),
                    "role": ROLE_MEMBER,
                    "disabled": False,
                    "password_salt": salt.hex(),
                    "password_hash": hashed_password,
                    "password_iterations": _PBKDF2_ITERATIONS,
                    "created_at": created_at,
                }
            )
            usage = self._register_code_usage_items(code_item)
            usage.append(
                {
                    "used_at": created_at,
                    "used_by_key": self._stable_lookup_key(normalized_username),
                    "used_by_enc": self._encrypt_text(resolved_username),
                }
            )
            code_item["used_count"] = len(usage)
            code_item["last_used_at"] = created_at
            self._write_json(self.users_path, users_data)
            self._write_json(self.register_codes_path, codes_data)
        return self._issue_session(
            WebAccount(
                account_id=account_id,
                username=resolved_username,
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

    def create_register_code(
        self,
        *,
        created_by: str,
        max_uses: int = 1,
        code: str | None = None,
    ) -> dict[str, Any]:
        resolved_max_uses = self._validate_register_code_max_uses(max_uses)
        plaintext = str(code or "").strip() or self._generate_register_code()
        created_at = _utc_now()
        item = {
            "code_id": f"invite_{secrets.token_hex(8)}",
            "code_key": self._stable_lookup_key(plaintext),
            "code_preview": self._code_preview(plaintext),
            "max_uses": resolved_max_uses,
            "used_count": 0,
            "usage": [],
            "disabled": False,
            "created_at": created_at,
            "created_by_enc": self._encrypt_text(str(created_by or "").strip() or "local-admin"),
        }
        with self._lock:
            data = self._read_json(self.register_codes_path)
            items = self._items(data)
            if self._find_register_code_item(items, plaintext) is not None:
                self._raise(409, "register_code_exists", "邀请码已存在")
            items.append(item)
            self._write_json(self.register_codes_path, data)
        return {
            **self._serialize_register_code_item(item),
            "code": plaintext,
        }

    def list_register_codes(self) -> dict[str, Any]:
        with self._lock:
            data = self._read_json(self.register_codes_path)
            items = [self._serialize_register_code_item(item) for item in self._items(data)]
        items.sort(key=lambda item: (item["disabled"], item["created_at"]), reverse=True)
        return {"items": items}

    def update_register_code(
        self,
        code_id: str,
        *,
        max_uses_delta: int | None = None,
        disabled: bool | None = None,
    ) -> dict[str, Any]:
        resolved_id = str(code_id or "").strip()
        if not resolved_id:
            self._raise(400, "invalid_register_code_id", "邀请码 ID 不能为空")

        with self._lock:
            data = self._read_json(self.register_codes_path)
            items = self._items(data)
            item = self._find_register_code_item_by_id(items, resolved_id)
            if item is None:
                self._raise(404, "register_code_not_found", "邀请码不存在")
            self._upgrade_register_code_item(item)
            if max_uses_delta is not None:
                current_max = self._register_code_max_uses(item)
                used_count = self._register_code_used_count(item)
                next_max = current_max + int(max_uses_delta)
                if next_max < used_count or next_max <= 0:
                    self._raise(400, "invalid_register_code_max_uses", "使用次数不能小于已使用次数，且至少为 1")
                item["max_uses"] = next_max
            if disabled is not None:
                item["disabled"] = bool(disabled)
            self._write_json(self.register_codes_path, data)
            return self._serialize_register_code_item(item)

    def delete_register_code(self, code_id: str) -> None:
        resolved_id = str(code_id or "").strip()
        if not resolved_id:
            self._raise(400, "invalid_register_code_id", "邀请码 ID 不能为空")
        with self._lock:
            data = self._read_json(self.register_codes_path)
            items = self._items(data)
            next_items = [item for item in items if str(item.get("code_id") or "").strip() != resolved_id]
            if len(next_items) == len(items):
                self._raise(404, "register_code_not_found", "邀请码不存在")
            data["items"] = next_items
            self._write_json(self.register_codes_path, data)

    def _issue_session(self, account: WebAccount, *, capabilities: frozenset[str] | None = None) -> WebAuthSession:
        token = f"web_sess_{secrets.token_urlsafe(24)}"
        resolved_capabilities = capabilities or capabilities_for_role(account.role)
        session = WebAuthSession(
            token=token,
            account=account,
            created_at=_utc_now(),
            capabilities=tuple(sorted(resolved_capabilities)),
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def build_local_admin_session(self, username: str = "127.0.0.1") -> WebAuthSession:
        return self._issue_session(
            WebAccount(
                account_id="local-admin",
                username=username,
                role=ROLE_MEMBER,
                disabled=False,
            ),
            capabilities=LOCAL_ADMIN_CAPABILITIES,
        )

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
            self._raise(400, "invalid_password", f"密码至少 {_PASSWORD_MIN_LENGTH} 位")
        return resolved

    def _validate_register_code_max_uses(self, max_uses: int) -> int:
        try:
            resolved = int(max_uses)
        except (TypeError, ValueError) as exc:
            self._raise(400, "invalid_register_code_max_uses", "使用次数必须是整数")
            raise exc
        if resolved <= 0:
            self._raise(400, "invalid_register_code_max_uses", "使用次数至少为 1")
        return resolved

    def _account_from_item(self, item: dict[str, Any]) -> WebAccount:
        return WebAccount(
            account_id=str(item.get("account_id") or ""),
            username=self._read_username_from_item(item),
            role=str(item.get("role") or ROLE_MEMBER),
            disabled=bool(item.get("disabled")),
        )

    def _find_user_item(self, items: list[dict[str, Any]], normalized_username: str) -> dict[str, Any] | None:
        expected_key = self._stable_lookup_key(normalized_username)
        for item in items:
            username_key = str(item.get("username_key") or "").strip()
            if username_key:
                if secrets.compare_digest(username_key, expected_key):
                    return item
                continue
            legacy_username = str(item.get("username") or "").strip().casefold()
            if legacy_username == normalized_username:
                return item
        return None

    def _find_register_code_item(self, items: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
        expected_key = self._stable_lookup_key(code)
        for item in items:
            code_key = str(item.get("code_key") or "").strip()
            if code_key:
                if secrets.compare_digest(code_key, expected_key):
                    return item
                continue
            legacy_code = str(item.get("code") or "").strip()
            if legacy_code == code:
                return item
        return None

    def _find_register_code_item_by_id(self, items: list[dict[str, Any]], code_id: str) -> dict[str, Any] | None:
        for item in items:
            if str(item.get("code_id") or "").strip() == code_id:
                return item
        return None

    def _upgrade_register_code_item(self, item: dict[str, Any], *, plaintext_code: str = "") -> None:
        legacy_code = plaintext_code or str(item.get("code") or "").strip()
        if legacy_code and not str(item.get("code_key") or "").strip():
            item["code_key"] = self._stable_lookup_key(legacy_code)
            item["code_preview"] = self._code_preview(legacy_code)
        if "code" in item:
            item.pop("code", None)
        if not str(item.get("code_id") or "").strip():
            item["code_id"] = f"invite_{secrets.token_hex(8)}"
        if not str(item.get("created_at") or "").strip():
            item["created_at"] = _utc_now()

    def _hash_password(self, password: str, salt: bytes, iterations: int) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        ).hex()

    def _stable_lookup_key(self, value: str) -> str:
        normalized = str(value or "").strip()
        secret = self._load_secret()
        return hmac.new(secret, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    def _keystream(self, nonce: bytes, size: int) -> bytes:
        secret = self._load_secret()
        blocks: list[bytes] = []
        counter = 0
        while sum(len(block) for block in blocks) < size:
            blocks.append(hashlib.sha256(secret + nonce + counter.to_bytes(4, "big")).digest())
            counter += 1
        return b"".join(blocks)[:size]

    def _encrypt_text(self, value: str) -> str:
        plaintext = str(value or "").encode("utf-8")
        nonce = secrets.token_bytes(16)
        stream = self._keystream(nonce, len(plaintext))
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
        mac = hmac.new(self._load_secret(), nonce + ciphertext, hashlib.sha256).digest()
        return f"v1:{_b64encode(nonce)}:{_b64encode(ciphertext)}:{_b64encode(mac)}"

    def _decrypt_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if not text.startswith("v1:"):
            return text
        parts = text.split(":")
        if len(parts) != 4:
            self._raise(500, "invalid_auth_store", "密文数据损坏")
        _, nonce_text, cipher_text, mac_text = parts
        nonce = _b64decode(nonce_text)
        ciphertext = _b64decode(cipher_text)
        expected_mac = hmac.new(self._load_secret(), nonce + ciphertext, hashlib.sha256).digest()
        actual_mac = _b64decode(mac_text)
        if not hmac.compare_digest(expected_mac, actual_mac):
            self._raise(500, "invalid_auth_store", "密文校验失败")
        stream = self._keystream(nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode("utf-8")

    def _load_secret(self) -> bytes:
        with self._lock:
            if self._secret is not None:
                return self._secret
            data = self._read_json(self.secret_path)
            encoded = str(data.get("key") or "").strip()
            if not encoded:
                secret = secrets.token_bytes(_STREAM_BLOCK_SIZE)
                self.secret_path.parent.mkdir(parents=True, exist_ok=True)
                self.secret_path.write_text(json.dumps({"key": _b64encode(secret)}, ensure_ascii=False) + "\n", encoding="utf-8")
                self._secret = secret
                return secret
            self._secret = _b64decode(encoded)
            return self._secret

    def _read_username_from_item(self, item: dict[str, Any]) -> str:
        encrypted = str(item.get("username_enc") or "").strip()
        if encrypted:
            return self._decrypt_text(encrypted)
        return str(item.get("username") or "").strip()

    def _register_code_usage_items(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        usage = item.get("usage")
        if isinstance(usage, list):
            return usage
        item["usage"] = []
        legacy_user = str(item.get("used_by") or "").strip()
        if legacy_user:
            item["usage"].append(
                {
                    "used_at": str(item.get("used_at") or item.get("last_used_at") or item.get("created_at") or _utc_now()),
                    "used_by_enc": self._encrypt_text(legacy_user),
                    "used_by_key": self._stable_lookup_key(legacy_user.casefold()),
                }
            )
        return item["usage"]

    def _register_code_used_count(self, item: dict[str, Any]) -> int:
        usage = self._register_code_usage_items(item)
        stored_count = item.get("used_count")
        if isinstance(stored_count, int) and stored_count >= len(usage):
            return stored_count
        item["used_count"] = len(usage)
        return len(usage)

    def _register_code_max_uses(self, item: dict[str, Any]) -> int:
        stored = item.get("max_uses")
        if isinstance(stored, int) and stored > 0:
            return stored
        if str(item.get("used_by") or "").strip():
            item["max_uses"] = 1
            return 1
        item["max_uses"] = 1
        return 1

    def _code_preview(self, code: str) -> str:
        value = str(code or "").strip()
        if len(value) <= 6:
            return value[:1] + "***"
        return f"{value[:3]}***{value[-3:]}"

    def _generate_register_code(self) -> str:
        return f"INV-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"

    def _serialize_register_code_item(self, item: dict[str, Any]) -> dict[str, Any]:
        usage_items = self._register_code_usage_items(item)
        used_count = self._register_code_used_count(item)
        max_uses = self._register_code_max_uses(item)
        last_used_at = str(item.get("last_used_at") or "")
        if not last_used_at and usage_items:
            last_used_at = str(usage_items[-1].get("used_at") or "")
        return {
            "code_id": str(item.get("code_id") or ""),
            "code_preview": str(item.get("code_preview") or ""),
            "disabled": bool(item.get("disabled")),
            "max_uses": max_uses,
            "used_count": used_count,
            "remaining_uses": max(max_uses - used_count, 0),
            "created_at": str(item.get("created_at") or ""),
            "created_by": self._decrypt_text(str(item.get("created_by_enc") or "")),
            "last_used_at": last_used_at,
            "usage": [
                {
                    "used_at": str(entry.get("used_at") or ""),
                    "used_by": self._decrypt_text(str(entry.get("used_by_enc") or "")),
                }
                for entry in usage_items
            ],
        }

    def _items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        items = data.get("items")
        if not isinstance(items, list):
            data["items"] = []
            return data["items"]
        return items

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"items": []} if path != self.secret_path else {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthStoreError(
                status=500,
                code="invalid_auth_store",
                message=f"无法解析存储文件: {path.name}",
            ) from exc
        if not isinstance(data, dict):
            return {"items": []} if path != self.secret_path else {}
        if path != self.secret_path and not isinstance(data.get("items"), list):
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
    "CAP_MANAGE_REGISTER_CODES",
    "CAP_MUTATE_BROWSE_STATE",
    "CAP_READ_FILE_CONTENT",
    "CAP_RUN_PLUGINS",
    "CAP_RUN_SCRIPTS",
    "CAP_TERMINAL_EXEC",
    "CAP_VIEW_BOTS",
    "CAP_VIEW_BOT_STATUS",
    "CAP_VIEW_CHAT_HISTORY",
    "CAP_VIEW_CHAT_TRACE",
    "CAP_VIEW_FILE_TREE",
    "CAP_VIEW_PLUGINS",
    "CAP_WRITE_FILES",
    "GUEST_CAPABILITIES",
    "LOCAL_ADMIN_CAPABILITIES",
    "MEMBER_CAPABILITIES",
    "ROLE_GUEST",
    "ROLE_MEMBER",
    "WebAccount",
    "WebAuthSession",
    "WebAuthStore",
    "capabilities_for_role",
]
