"""Tencent iLink Bot HTTP client used by the optional personal Weixin gateway."""

from __future__ import annotations

import asyncio
import base64
import inspect
import secrets
import struct
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import aiohttp


ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = "1"
CHANNEL_VERSION = "orbit-safe-claw"
BOT_TYPE = "3"
LONG_POLL_TIMEOUT_MS = 35_000
API_TIMEOUT_SECONDS = 20.0
QR_TIMEOUT_SECONDS = 35.0

EP_GET_BOT_QRCODE = "ilink/bot/get_bot_qrcode"
EP_GET_QRCODE_STATUS = "ilink/bot/get_qrcode_status"
EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"


class WeixinError(Exception):
    """Base exception whose string representation never includes credentials."""

    def __init__(
        self,
        method: str,
        code: int = 0,
        *,
        retry_after: float = 0.0,
        retryable: bool = False,
        is_network_error: bool = False,
        is_timeout: bool = False,
        session_expired: bool = False,
    ) -> None:
        self.method = str(method or "request")
        self.code = int(code or 0)
        self.errcode = self.code
        self.retry_after = max(0.0, float(retry_after or 0.0))
        self.retryable = bool(retryable or self.retry_after > 0)
        self.is_retryable = self.retryable
        self.is_network_error = bool(is_network_error)
        self.network_error = self.is_network_error
        self.is_timeout = bool(is_timeout)
        self.timeout = self.is_timeout
        self.session_expired = bool(session_expired)
        super().__init__(self._safe_message())

    def _safe_message(self) -> str:
        return f"Weixin {self.method} failed (code={self.code})"


class WeixinTransportError(WeixinError):
    """A network failure safe to retry without exposing the request URL."""

    def __init__(self, method: str, *, timeout: bool = False) -> None:
        super().__init__(
            method,
            retryable=True,
            is_network_error=not timeout,
            is_timeout=timeout,
        )


class WeixinTimeoutError(WeixinTransportError):
    def __init__(self, method: str) -> None:
        super().__init__(method, timeout=True)


class WeixinNetworkError(WeixinTransportError):
    def __init__(self, method: str) -> None:
        super().__init__(method, timeout=False)


class WeixinApiError(WeixinError):
    """An HTTP or iLink API response error."""


class WeixinRateLimitError(WeixinApiError):
    def __init__(self, method: str, code: int, *, retry_after: float = 0.0) -> None:
        super().__init__(method, code, retry_after=retry_after, retryable=True)


class WeixinSessionExpiredError(WeixinApiError):
    def __init__(self, method: str, code: int = -14) -> None:
        super().__init__(method, code, session_expired=True)


Transport = Callable[..., Any]


def _random_wechat_uin() -> str:
    value = struct.unpack(">I", secrets.token_bytes(4))[0]
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


class WeixinClient:
    """Small, injectable iLink transport for QR login and text messaging.

    ``transport`` may be an async callable or an object with an async
    ``request`` method.  A test transport can return a mapping directly, or a
    response-like object with ``status`` and ``json`` attributes.
    """

    def __init__(
        self,
        token: str = "",
        *,
        account_id: str = "",
        base_url: str = ILINK_BASE_URL,
        transport: Transport | Any | None = None,
        http_transport: Transport | Any | None = None,
        app_id: str = ILINK_APP_ID,
        client_version: str = ILINK_APP_CLIENT_VERSION,
        channel_version: str = CHANNEL_VERSION,
        timeout_seconds: float = API_TIMEOUT_SECONDS,
        max_retries: int = 2,
        retry_base_seconds: float = 0.5,
    ) -> None:
        self.token = str(token or "").strip()
        self.account_id = str(account_id or "").strip()
        self.base_url = str(base_url or ILINK_BASE_URL).strip().rstrip("/") or ILINK_BASE_URL
        self.app_id = str(app_id or ILINK_APP_ID).strip() or ILINK_APP_ID
        self.client_version = str(client_version or ILINK_APP_CLIENT_VERSION).strip() or ILINK_APP_CLIENT_VERSION
        self.channel_version = str(channel_version or CHANNEL_VERSION).strip() or CHANNEL_VERSION
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.max_retries = max(0, int(max_retries))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._transport = transport if transport is not None else http_transport
        self._session: aiohttp.ClientSession | None = None

    def _headers(self, *, authenticated: bool, include_body: bool) -> dict[str, str]:
        headers = {
            "iLink-App-Id": self.app_id,
            "iLink-App-ClientVersion": self.client_version,
        }
        if include_body:
            headers.update({
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "X-WECHAT-UIN": _random_wechat_uin(),
            })
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def build_headers(self, *, authenticated: bool = True, include_body: bool = True) -> dict[str, str]:
        """Return request headers for tests and callers that need inspection."""
        return self._headers(authenticated=authenticated, include_body=include_body)

    def _url(self, endpoint: str, params: Mapping[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{str(endpoint).lstrip('/')}"
        if params:
            encoded = urlencode({key: value for key, value in params.items() if value is not None})
            if encoded:
                url = f"{url}?{encoded}"
        return url

    @staticmethod
    def _response_status(response: Any) -> int:
        try:
            return int(getattr(response, "status", 200) or 200)
        except (TypeError, ValueError):
            return 200

    async def _response_json(self, response: Any) -> Any:
        if isinstance(response, Mapping):
            return dict(response)
        json_method = getattr(response, "json", None)
        if callable(json_method):
            value = json_method(content_type=None)
            if inspect.isawaitable(value):
                value = await value
            return value
        text_method = getattr(response, "text", None)
        if callable(text_method):
            value = text_method()
            if inspect.isawaitable(value):
                value = await value
            return value
        return response

    async def _call_transport(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> tuple[int, Any]:
        if self._transport is None:
            if self._session is None:
                self._session = aiohttp.ClientSession(trust_env=True)
            try:
                request = self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                )
                async with request as response:
                    return self._response_status(response), await self._response_json(response)
            except (aiohttp.ServerTimeoutError, asyncio.TimeoutError, TimeoutError):
                raise WeixinTimeoutError(method) from None
            except aiohttp.ClientError:
                raise WeixinNetworkError(method) from None
            except Exception:
                raise WeixinNetworkError(method) from None

        target = self._transport
        request_method = getattr(target, "request", None)
        if not callable(request_method) and callable(target):
            request_method = target
        if not callable(request_method):
            raise WeixinNetworkError(method)
        try:
            result = request_method(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if inspect.isawaitable(result):
                result = await result
            if hasattr(result, "__aenter__") and hasattr(result, "__aexit__"):
                async with result as response:
                    return self._response_status(response), await self._response_json(response)
            return self._response_status(result), await self._response_json(result)
        except WeixinError:
            raise
        except (aiohttp.ServerTimeoutError, asyncio.TimeoutError, TimeoutError):
            raise WeixinTimeoutError(method) from None
        except (aiohttp.ClientError, OSError, ConnectionError):
            raise WeixinNetworkError(method) from None
        except Exception:
            raise WeixinNetworkError(method) from None

    @staticmethod
    def _int_value(payload: Mapping[str, Any], *names: str) -> int:
        for name in names:
            value = payload.get(name)
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    @classmethod
    def _check_payload(cls, method: str, status: int, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise WeixinApiError(method, status or 0)
        data = dict(payload)
        code = cls._int_value(data, "ret", "errcode", "error_code", "code")
        if status == 429 or code == 429 or code == -2:
            retry_after = 0.0
            try:
                retry_after = float(data.get("retry_after") or data.get("retryAfter") or 0.0)
            except (TypeError, ValueError):
                pass
            raise WeixinRateLimitError(method, code or status or 429, retry_after=retry_after)
        if code == -14:
            raise WeixinSessionExpiredError(method, code)
        if status >= 500 or code >= 500:
            raise WeixinApiError(method, code or status, retryable=True)
        if status >= 400 or ("ret" in data and code != 0) or ("errcode" in data and code != 0):
            raise WeixinApiError(method, code or status)
        return data

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        authenticated: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        method = str(method or "GET").upper()
        include_body = method in {"POST", "PUT", "PATCH"}
        headers = self._headers(authenticated=authenticated, include_body=include_body)
        url = self._url(endpoint, params)
        timeout_value = max(0.1, float(timeout if timeout is not None else self.timeout_seconds))
        for attempt in range(self.max_retries + 1):
            try:
                status, raw = await self._call_transport(
                    method,
                    url,
                    headers=headers,
                    payload=payload,
                    timeout=timeout_value,
                )
                return self._check_payload(endpoint, status, raw)
            except asyncio.CancelledError:
                raise
            except WeixinError as exc:
                if exc.session_expired or not exc.retryable or attempt >= self.max_retries:
                    raise
                delay = exc.retry_after or self.retry_base_seconds * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
        raise WeixinApiError(endpoint)

    def _base_info(self) -> dict[str, str]:
        return {"channel_version": self.channel_version}

    async def get_bot_qrcode(self) -> dict[str, Any]:
        return await self._request(
            "GET",
            EP_GET_BOT_QRCODE,
            params={"bot_type": BOT_TYPE},
            timeout=QR_TIMEOUT_SECONDS,
        )

    async def get_qrcode_status(self, qrcode: str) -> dict[str, Any]:
        value = str(qrcode or "").strip()
        if not value:
            raise ValueError("qrcode 不能为空")
        return await self._request(
            "GET",
            EP_GET_QRCODE_STATUS,
            params={"qrcode": value},
            timeout=QR_TIMEOUT_SECONDS,
        )

    async def get_updates(self, sync_buf: str = "", *, timeout_ms: int = LONG_POLL_TIMEOUT_MS) -> dict[str, Any]:
        timeout_value = max(1.0, min(60.0, float(timeout_ms) / 1000.0 + 10.0))
        try:
            return await self._request(
                "POST",
                EP_GET_UPDATES,
                payload={"get_updates_buf": str(sync_buf or ""), "base_info": self._base_info()},
                authenticated=True,
                timeout=timeout_value,
            )
        except WeixinTimeoutError:
            return {"ret": 0, "msgs": [], "get_updates_buf": str(sync_buf or "")}

    async def send_message(
        self,
        to_user_id: str,
        text: str,
        *,
        context_token: str = "",
        client_id: str | None = None,
    ) -> dict[str, Any]:
        peer = str(to_user_id or "").strip()
        body = str(text or "")
        if not peer:
            raise ValueError("to_user_id 不能为空")
        if not body.strip():
            raise ValueError("text 不能为空")
        message: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": peer,
            "client_id": str(client_id or uuid.uuid4().hex),
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": body}}],
        }
        if str(context_token or "").strip():
            message["context_token"] = str(context_token).strip()
        return await self._request(
            "POST",
            EP_SEND_MESSAGE,
            payload={"msg": message, "base_info": self._base_info()},
            authenticated=True,
        )

    # Protocol-shaped aliases make the client convenient for callers and tests.
    get_qr_code = get_bot_qrcode
    get_qr = get_bot_qrcode
    get_qrcode = get_bot_qrcode
    get_qr_status = get_qrcode_status
    poll_qr_status = get_qrcode_status
    getupdates = get_updates
    sendmessage = send_message
    send_text = send_message

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


__all__ = [
    "BOT_TYPE",
    "CHANNEL_VERSION",
    "EP_GET_BOT_QRCODE",
    "EP_GET_QRCODE_STATUS",
    "EP_GET_UPDATES",
    "EP_SEND_MESSAGE",
    "ILINK_APP_CLIENT_VERSION",
    "ILINK_APP_ID",
    "ILINK_BASE_URL",
    "WeixinApiError",
    "WeixinClient",
    "WeixinError",
    "WeixinNetworkError",
    "WeixinRateLimitError",
    "WeixinSessionExpiredError",
    "WeixinTimeoutError",
    "WeixinTransportError",
]
