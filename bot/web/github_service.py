"""GitHub account connections, repository API and local Git credentials.

Each Web account connects its own GitHub identity, either through the OAuth
device flow (when ``GITHUB_OAUTH_CLIENT_ID`` names an OAuth App with device
flow enabled) or with a personal access token. Tokens are encrypted at rest,
never returned to clients, and only reach local Git through command-scope
configuration in the child environment.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from cryptography.fernet import Fernet, InvalidToken

from bot import config
from bot.runtime_paths import get_github_data_dir
from bot.web.api_common import WebApiError


GITHUB_API_URL = "https://api.github.com"
GITHUB_WEB_URL = "https://github.com"
GITHUB_GIT_URL_PREFIX = f"{GITHUB_WEB_URL}/"
GITHUB_DEVICE_CODE_URL = f"{GITHUB_WEB_URL}/login/device/code"
GITHUB_DEVICE_VERIFICATION_URL = f"{GITHUB_WEB_URL}/login/device"
GITHUB_OAUTH_TOKEN_URL = f"{GITHUB_WEB_URL}/login/oauth/access_token"
GITHUB_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
GITHUB_OAUTH_SCOPES = ("repo", "read:org")
GITHUB_TOKEN_CREATE_URL = (
    f"{GITHUB_WEB_URL}/settings/tokens/new?scopes=repo,read:org&description=Orbit%20Safe%20Claw"
)
GITHUB_API_VERSION = "2022-11-28"
GITHUB_USER_AGENT = "Orbit-Safe-Claw"
GITHUB_REQUEST_TIMEOUT_SECONDS = 20.0
GITHUB_REPOS_PER_PAGE = 100
GITHUB_REPOS_MAX_PAGE = 50
GITHUB_DEVICE_FLOWS_PER_ACCOUNT = 3
GITHUB_REPO_DESCRIPTION_MAX_LENGTH = 350

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]{20,255}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_LINK_NEXT_RE = re.compile(r'<[^>]+>\s*;\s*rel="next"')
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True)
class GitHubResponse:
    status: int
    data: Any
    headers: Mapping[str, str]


GitHubTransport = Callable[..., Awaitable[GitHubResponse]]


async def aiohttp_github_transport(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json_body: Any = None,
    form: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> GitHubResponse:
    """Send one GitHub request, following the system proxy environment."""
    timeout = ClientTimeout(total=GITHUB_REQUEST_TIMEOUT_SECONDS)
    try:
        async with ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.request(
                method,
                url,
                headers=dict(headers),
                json=json_body,
                data=form,
                params=params,
            ) as response:
                text = await response.text()
                try:
                    data = json.loads(text) if text.strip() else {}
                except json.JSONDecodeError:
                    data = {"message": text[:500]}
                return GitHubResponse(
                    response.status,
                    data,
                    {key.lower(): value for key, value in response.headers.items()},
                )
    except asyncio.TimeoutError as exc:
        raise WebApiError(504, "github_network_failed", "连接 GitHub 超时，请检查网络或系统代理设置") from exc
    except ClientError as exc:
        detail = str(exc)[:200] or exc.__class__.__name__
        raise WebApiError(502, "github_network_failed", f"无法连接 GitHub：{detail}") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _token_kind(token: str) -> str:
    if token.startswith("github_pat_"):
        return "fine_grained"
    if token.startswith("ghp_"):
        return "classic"
    if token.startswith("gho_"):
        return "oauth"
    return "other"


def build_github_git_auth_config(login: str, token: str) -> tuple[tuple[str, str], ...]:
    """Git config entries that authenticate HTTPS requests to github.com only.

    The empty ``extraheader`` resets inherited headers for the same URL, and
    the empty credential helper keeps a rejected token from falling back to a
    credential window. Other hosts keep their own helpers.
    """
    basic = base64.b64encode(f"{login}:{token}".encode("utf-8")).decode("ascii")
    header_key = f"http.{GITHUB_GIT_URL_PREFIX}.extraheader"
    return (
        (header_key, ""),
        (header_key, f"Authorization: Basic {basic}"),
        (f"credential.{GITHUB_WEB_URL}.helper", ""),
    )


@dataclass(frozen=True)
class GitHubCredential:
    token: str
    login: str
    github_user_id: int = 0
    name: str = ""
    avatar_url: str = ""
    html_url: str = ""
    auth_method: str = "token"
    token_kind: str = "other"
    scopes: tuple[str, ...] = ()
    connected_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "connected": True,
            "login": self.login,
            "name": self.name,
            "avatar_url": self.avatar_url,
            "html_url": self.html_url,
            "auth_method": self.auth_method,
            "token_kind": self.token_kind,
            "scopes": list(self.scopes),
            "connected_at": self.connected_at,
        }


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    # mkstemp creates the file with 0600 on POSIX before any secret is written.
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class GitHubCredentialStore:
    """One encrypted credential file per Web account."""

    def __init__(self, root: str | Path | None = None):
        self._root_override = Path(root) if root is not None else None
        self._lock = threading.RLock()
        self._fernet_cache: tuple[Path, Fernet] | None = None

    @property
    def root(self) -> Path:
        # Resolved per call so a storage-root change is never served stale.
        return self._root_override or get_github_data_dir()

    def _account_path(self, account_id: str) -> Path:
        digest = hashlib.sha256(str(account_id).encode("utf-8")).hexdigest()[:40]
        return self.root / "accounts" / f"{digest}.json"

    @staticmethod
    def _read_or_create_key(path: Path) -> bytes:
        try:
            return path.read_bytes().strip()
        except FileNotFoundError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = Fernet.generate_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            return path.read_bytes().strip()
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key

    def _fernet(self) -> Fernet:
        key_path = self.root / "secret.key"
        with self._lock:
            if self._fernet_cache is not None and self._fernet_cache[0] == key_path:
                return self._fernet_cache[1]
            try:
                fernet = Fernet(self._read_or_create_key(key_path))
            except ValueError as exc:
                raise WebApiError(500, "github_store_unavailable", "GitHub 凭据密钥损坏，请删除后重新连接账号") from exc
            self._fernet_cache = (key_path, fernet)
            return fernet

    def get(self, account_id: str) -> GitHubCredential | None:
        path = self._account_path(account_id)
        with self._lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                return None
            if not isinstance(payload, dict) or payload.get("account_id") != account_id:
                return None
            try:
                token = self._fernet().decrypt(str(payload.get("token_enc") or "").encode("ascii")).decode("utf-8")
            except (InvalidToken, ValueError, UnicodeError):
                return None
        scopes = payload.get("scopes")
        return GitHubCredential(
            token=token,
            login=str(payload.get("login") or ""),
            github_user_id=int(payload.get("github_user_id") or 0),
            name=str(payload.get("name") or ""),
            avatar_url=str(payload.get("avatar_url") or ""),
            html_url=str(payload.get("html_url") or ""),
            auth_method=str(payload.get("auth_method") or "token"),
            token_kind=str(payload.get("token_kind") or _token_kind(token)),
            scopes=tuple(str(item) for item in scopes) if isinstance(scopes, list) else (),
            connected_at=str(payload.get("connected_at") or ""),
        )

    def save(self, account_id: str, credential: GitHubCredential) -> None:
        payload = {
            "schema": "github_account_v1",
            "account_id": account_id,
            "login": credential.login,
            "github_user_id": credential.github_user_id,
            "name": credential.name,
            "avatar_url": credential.avatar_url,
            "html_url": credential.html_url,
            "auth_method": credential.auth_method,
            "token_kind": credential.token_kind,
            "scopes": list(credential.scopes),
            "connected_at": credential.connected_at,
            "token_enc": self._fernet().encrypt(credential.token.encode("utf-8")).decode("ascii"),
        }
        with self._lock:
            _write_private_json(self._account_path(account_id), payload)

    def delete(self, account_id: str) -> bool:
        with self._lock:
            try:
                self._account_path(account_id).unlink()
            except FileNotFoundError:
                return False
        return True


@dataclass
class _DeviceFlow:
    flow_id: str
    account_id: str
    client_id: str
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: int
    next_poll_at: float
    polling: bool = False


def _github_error_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    parts = [str(data.get("message") or "").strip()]
    errors = data.get("errors")
    if isinstance(errors, list):
        for item in errors[:5]:
            if isinstance(item, dict):
                parts.append(str(item.get("message") or item.get("code") or "").strip())
            elif isinstance(item, str):
                parts.append(item.strip())
    return "；".join(part for part in parts if part)[:500]


def _raise_github_api_error(response: GitHubResponse) -> None:
    status = response.status
    message = _github_error_message(response.data)
    if status == 401:
        # Not 401: that status means the Orbit session itself is invalid.
        raise WebApiError(409, "github_token_invalid", "GitHub 令牌无效或已撤销，请重新连接 GitHub 账号")
    if status == 429 or (status == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
        raise WebApiError(429, "github_rate_limited", "GitHub API 请求过于频繁，请稍后重试")
    if status == 403:
        raise WebApiError(
            403,
            "github_permission_denied",
            f"GitHub 拒绝了此操作：{message or '权限不足'}。请确认令牌包含 repo 权限；组织仓库还需要组织授权",
        )
    if status == 404:
        raise WebApiError(404, "github_not_found", f"GitHub 未找到目标或令牌无权访问：{message or 'Not Found'}")
    if status == 422:
        if "already exists" in message.lower():
            raise WebApiError(409, "github_repo_exists", "该所有者下已存在同名仓库")
        raise WebApiError(422, "github_validation_failed", f"GitHub 校验失败：{message or '请求参数无效'}")
    raise WebApiError(502, "github_request_failed", f"GitHub 请求失败（HTTP {status}）{('：' + message) if message else ''}")


def _device_error(error: str, description: str, status: int) -> WebApiError:
    if error == "device_flow_disabled":
        return WebApiError(409, "github_device_flow_disabled", "该 GitHub OAuth App 未启用 Device Flow，请在应用设置中开启后重试")
    if error in {"incorrect_client_credentials", "unsupported_grant_type"}:
        return WebApiError(409, "github_device_flow_misconfigured", "GITHUB_OAUTH_CLIENT_ID 无效，请检查 OAuth App 配置")
    detail = description or error or f"HTTP {status}"
    return WebApiError(502, "github_device_flow_failed", f"GitHub 授权失败：{detail}"[:500])


def _repository_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    permissions = item.get("permissions") if isinstance(item.get("permissions"), dict) else {}
    return {
        "id": int(item.get("id") or 0),
        "name": str(item.get("name") or ""),
        "full_name": str(item.get("full_name") or ""),
        "owner": str(owner.get("login") or ""),
        "private": bool(item.get("private")),
        "archived": bool(item.get("archived")),
        "description": str(item.get("description") or ""),
        "html_url": str(item.get("html_url") or ""),
        "clone_url": str(item.get("clone_url") or ""),
        "ssh_url": str(item.get("ssh_url") or ""),
        "default_branch": str(item.get("default_branch") or ""),
        "pushed_at": str(item.get("pushed_at") or item.get("updated_at") or ""),
        "can_push": bool(permissions.get("push") or permissions.get("admin")),
    }


def _normalize_token(token: Any) -> str:
    value = str(token or "").strip()
    if not _TOKEN_RE.fullmatch(value):
        raise WebApiError(400, "invalid_github_token", "GitHub 令牌格式不正确")
    return value


def _normalize_page(page: Any) -> int:
    try:
        value = int(str(page or "1").strip())
    except (TypeError, ValueError):
        raise WebApiError(400, "invalid_page", "page 必须是正整数") from None
    if value < 1 or value > GITHUB_REPOS_MAX_PAGE:
        raise WebApiError(400, "invalid_page", f"page 必须在 1 到 {GITHUB_REPOS_MAX_PAGE} 之间")
    return value


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


class GitHubService:
    def __init__(
        self,
        store: GitHubCredentialStore | None = None,
        transport: GitHubTransport | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        client_id_provider: Callable[[], str] | None = None,
    ):
        self.store = store or GitHubCredentialStore()
        self._transport = transport or aiohttp_github_transport
        self._clock = clock
        self._client_id_provider = client_id_provider or (
            lambda: str(getattr(config, "GITHUB_OAUTH_CLIENT_ID", "") or "").strip()
        )
        self._flows: dict[str, _DeviceFlow] = {}
        self._flows_lock = threading.Lock()

    # ----- account -----

    def device_flow_available(self) -> bool:
        return bool(self._client_id_provider())

    def _status_payload(self, credential: GitHubCredential | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connected": False,
            "login": "",
            "name": "",
            "avatar_url": "",
            "html_url": "",
            "auth_method": "",
            "token_kind": "",
            "scopes": [],
            "connected_at": "",
            "device_flow_available": self.device_flow_available(),
            "token_create_url": GITHUB_TOKEN_CREATE_URL,
            "required_scopes": list(GITHUB_OAUTH_SCOPES),
        }
        if credential is not None:
            payload.update(credential.public_dict())
        return payload

    async def account_status(self, account_id: str) -> dict[str, Any]:
        return self._status_payload(await asyncio.to_thread(self.store.get, account_id))

    async def _api(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: Any = None,
        params: Mapping[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> GitHubResponse:
        response = await self._transport(
            method,
            f"{GITHUB_API_URL}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": GITHUB_USER_AGENT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            json_body=json_body,
            params=params,
        )
        if response.status not in expected:
            _raise_github_api_error(response)
        return response

    async def _credential_from_token(self, token: str, *, auth_method: str, granted_scopes: str = "") -> GitHubCredential:
        response = await self._api("GET", "/user", token=token)
        user = response.data if isinstance(response.data, dict) else {}
        login = str(user.get("login") or "").strip()
        if not _OWNER_RE.fullmatch(login):
            raise WebApiError(502, "github_unexpected_response", "GitHub 未返回有效的账号信息")
        raw_scopes = response.headers.get("x-oauth-scopes", granted_scopes) or ""
        return GitHubCredential(
            token=token,
            login=login,
            github_user_id=int(user.get("id") or 0),
            name=str(user.get("name") or ""),
            avatar_url=str(user.get("avatar_url") or ""),
            html_url=str(user.get("html_url") or f"{GITHUB_WEB_URL}/{login}"),
            auth_method=auth_method,
            token_kind=_token_kind(token),
            scopes=tuple(scope.strip() for scope in raw_scopes.replace(" ", ",").split(",") if scope.strip()),
            connected_at=_utc_now(),
        )

    async def connect_with_token(self, account_id: str, token: Any) -> dict[str, Any]:
        credential = await self._credential_from_token(_normalize_token(token), auth_method="token")
        await asyncio.to_thread(self.store.save, account_id, credential)
        return self._status_payload(credential)

    async def disconnect(self, account_id: str) -> dict[str, Any]:
        await asyncio.to_thread(self.store.delete, account_id)
        with self._flows_lock:
            for flow_id in [key for key, flow in self._flows.items() if flow.account_id == account_id]:
                self._flows.pop(flow_id, None)
        return self._status_payload(None)

    async def _require_credential(self, account_id: str) -> GitHubCredential:
        credential = await asyncio.to_thread(self.store.get, account_id)
        if credential is None:
            raise WebApiError(409, "github_not_connected", "请先连接 GitHub 账号")
        return credential

    def git_auth_config(self, account_id: str) -> tuple[tuple[str, str], ...]:
        """Blocking lookup used by Git workers running off the event loop."""
        credential = self.store.get(account_id) if account_id else None
        if credential is None or not credential.login:
            return ()
        return build_github_git_auth_config(credential.login, credential.token)

    # ----- device flow -----

    def _prune_flows(self, now: float) -> None:
        for flow_id in [key for key, flow in self._flows.items() if flow.expires_at <= now]:
            self._flows.pop(flow_id, None)

    async def start_device_flow(self, account_id: str) -> dict[str, Any]:
        client_id = self._client_id_provider()
        if not client_id:
            raise WebApiError(409, "github_device_flow_unavailable", "管理员尚未配置 GITHUB_OAUTH_CLIENT_ID，请改用个人访问令牌")
        response = await self._transport(
            "POST",
            GITHUB_DEVICE_CODE_URL,
            headers={"Accept": "application/json", "User-Agent": GITHUB_USER_AGENT},
            form={"client_id": client_id, "scope": " ".join(GITHUB_OAUTH_SCOPES)},
        )
        data = response.data if isinstance(response.data, dict) else {}
        if response.status != 200 or data.get("error"):
            raise _device_error(str(data.get("error") or ""), str(data.get("error_description") or ""), response.status)
        device_code = str(data.get("device_code") or "")
        user_code = str(data.get("user_code") or "")
        if not device_code or not user_code:
            raise WebApiError(502, "github_unexpected_response", "GitHub 未返回设备授权码")
        verification_uri = str(data.get("verification_uri") or "")
        if not verification_uri.startswith(GITHUB_GIT_URL_PREFIX):
            verification_uri = GITHUB_DEVICE_VERIFICATION_URL
        expires_in = _clamp_int(data.get("expires_in"), 900, 60, 1800)
        interval = _clamp_int(data.get("interval"), 5, 1, 60)
        now = self._clock()
        flow = _DeviceFlow(
            flow_id=secrets.token_urlsafe(18),
            account_id=account_id,
            client_id=client_id,
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            expires_at=now + expires_in,
            interval=interval,
            next_poll_at=now + interval,
        )
        with self._flows_lock:
            self._prune_flows(now)
            mine = sorted(
                (item for item in self._flows.values() if item.account_id == account_id),
                key=lambda item: item.expires_at,
            )
            for stale in mine[: max(0, len(mine) - GITHUB_DEVICE_FLOWS_PER_ACCOUNT + 1)]:
                self._flows.pop(stale.flow_id, None)
            self._flows[flow.flow_id] = flow
        return {
            "flow_id": flow.flow_id,
            "user_code": user_code,
            "verification_uri": verification_uri,
            "expires_in": expires_in,
            "interval": interval,
        }

    def _pending(self, flow: _DeviceFlow, now: float) -> dict[str, Any]:
        return {
            "status": "pending",
            "interval": flow.interval,
            "expires_in": max(0, int(flow.expires_at - now)),
        }

    async def poll_device_flow(self, account_id: str, flow_id: Any) -> dict[str, Any]:
        now = self._clock()
        with self._flows_lock:
            self._prune_flows(now)
            flow = self._flows.get(str(flow_id or ""))
            if flow is None or flow.account_id != account_id:
                raise WebApiError(404, "github_device_flow_not_found", "授权请求已过期或不存在，请重新开始")
            # GitHub rejects polls faster than the interval with slow_down.
            if flow.polling or now < flow.next_poll_at:
                return self._pending(flow, now)
            flow.polling = True
        try:
            response = await self._transport(
                "POST",
                GITHUB_OAUTH_TOKEN_URL,
                headers={"Accept": "application/json", "User-Agent": GITHUB_USER_AGENT},
                form={
                    "client_id": flow.client_id,
                    "device_code": flow.device_code,
                    "grant_type": GITHUB_DEVICE_GRANT_TYPE,
                },
            )
        finally:
            with self._flows_lock:
                flow.polling = False
                flow.next_poll_at = self._clock() + flow.interval
        data = response.data if isinstance(response.data, dict) else {}
        token = str(data.get("access_token") or "")
        error = str(data.get("error") or "")
        if token:
            credential = await self._credential_from_token(
                token,
                auth_method="device",
                granted_scopes=str(data.get("scope") or ""),
            )
            await asyncio.to_thread(self.store.save, account_id, credential)
            with self._flows_lock:
                self._flows.pop(flow.flow_id, None)
            return {"status": "connected", "account": self._status_payload(credential)}
        if error == "authorization_pending":
            return self._pending(flow, self._clock())
        if error == "slow_down":
            with self._flows_lock:
                flow.interval = _clamp_int(data.get("interval"), flow.interval + 5, flow.interval + 5, 60)
                flow.next_poll_at = self._clock() + flow.interval
            return self._pending(flow, self._clock())
        with self._flows_lock:
            self._flows.pop(flow.flow_id, None)
        if error == "expired_token":
            return {"status": "expired"}
        if error == "access_denied":
            return {"status": "denied"}
        raise _device_error(error, str(data.get("error_description") or ""), response.status)

    # ----- repositories -----

    async def list_repositories(self, account_id: str, *, page: Any = 1) -> dict[str, Any]:
        credential = await self._require_credential(account_id)
        page_number = _normalize_page(page)
        response = await self._api(
            "GET",
            "/user/repos",
            token=credential.token,
            params={
                "per_page": str(GITHUB_REPOS_PER_PAGE),
                "page": str(page_number),
                "sort": "pushed",
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        items = response.data if isinstance(response.data, list) else []
        return {
            "items": [_repository_payload(item) for item in items if isinstance(item, dict)],
            "page": page_number,
            "has_more": bool(_LINK_NEXT_RE.search(response.headers.get("link", ""))),
        }

    async def list_owners(self, account_id: str) -> dict[str, Any]:
        credential = await self._require_credential(account_id)
        owners = [{"login": credential.login, "type": "user", "avatar_url": credential.avatar_url}]
        try:
            response = await self._api("GET", "/user/orgs", token=credential.token, params={"per_page": "100"})
        except WebApiError as exc:
            # Fine-grained tokens may not list organizations; the user can
            # still create repositories under their own account.
            if exc.code not in {"github_permission_denied", "github_not_found"}:
                raise
            return {"items": owners}
        for item in response.data if isinstance(response.data, list) else []:
            login = str(item.get("login") or "") if isinstance(item, dict) else ""
            if _OWNER_RE.fullmatch(login):
                owners.append({"login": login, "type": "org", "avatar_url": str(item.get("avatar_url") or "")})
        return {"items": owners}

    async def create_repository(
        self,
        account_id: str,
        *,
        owner: Any = "",
        name: Any,
        description: Any = "",
        private: bool = True,
    ) -> dict[str, Any]:
        credential = await self._require_credential(account_id)
        owner_login = str(owner or "").strip() or credential.login
        if not _OWNER_RE.fullmatch(owner_login):
            raise WebApiError(400, "invalid_github_owner", "仓库所有者不合法")
        repo_name = str(name or "").strip()
        if (
            not _REPO_NAME_RE.fullmatch(repo_name)
            or repo_name in {".", ".."}
            or repo_name.lower().endswith(".git")
        ):
            raise WebApiError(
                400,
                "invalid_github_repo_name",
                "仓库名只能包含字母、数字、点、下划线和连字符，最长 100 个字符，且不能以 .git 结尾",
            )
        text = _CONTROL_CHARS_RE.sub(" ", str(description or "")).strip()
        if len(text) > GITHUB_REPO_DESCRIPTION_MAX_LENGTH:
            raise WebApiError(400, "invalid_github_repo_description", f"仓库描述不能超过 {GITHUB_REPO_DESCRIPTION_MAX_LENGTH} 个字符")
        path = "/user/repos" if owner_login.lower() == credential.login.lower() else f"/orgs/{owner_login}/repos"
        response = await self._api(
            "POST",
            path,
            token=credential.token,
            # An empty repository lets the local history be published as-is.
            json_body={"name": repo_name, "description": text, "private": bool(private), "auto_init": False},
            expected=(201,),
        )
        if not isinstance(response.data, dict):
            raise WebApiError(502, "github_unexpected_response", "GitHub 未返回新仓库信息")
        return _repository_payload(response.data)


_SERVICE: GitHubService | None = None
_SERVICE_LOCK = threading.Lock()


def get_github_service() -> GitHubService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = GitHubService()
        return _SERVICE
