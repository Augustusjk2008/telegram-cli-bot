"""Telegram Bot API transport with credential-free errors."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class TelegramError(Exception):
    def __init__(
        self,
        method: str,
        code: int = 0,
        retry_after: int = 0,
        *,
        is_network_error: bool = False,
        is_timeout: bool = False,
    ):
        self.method = method
        self.code = code
        self.retry_after = retry_after
        self.is_network_error = is_network_error
        self.is_timeout = is_timeout
        self.network_error = is_network_error
        self.timeout = is_timeout
        self.retryable = bool(is_network_error or is_timeout or retry_after or code == 429 or code >= 500)
        self.is_retryable = self.retryable
        super().__init__(f"Telegram {method} failed (code={code})")


class TelegramTransportError(TelegramError):
    """A network or timeout failure safe to classify without exposing the token."""

    pass


class TelegramClient:
    def __init__(self, token: str):
        bot_id, separator, secret = token.partition(":")
        if not separator or not bot_id.isascii() or not bot_id.isdigit() or not secret.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN 格式无效")
        self.bot_id = bot_id
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._session: aiohttp.ClientSession | None = None

    async def _request(self, method: str, payload: dict[str, Any], *, timeout: int = 30) -> Any:
        if self._session is None:
            self._session = aiohttp.ClientSession(trust_env=True)
        try:
            async with self._session.post(
                f"{self._base_url}/{method}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    raise TelegramError(method, response.status)
                if response.status != 200 or not data.get("ok"):
                    parameters = data.get("parameters") or {}
                    raise TelegramError(
                        method,
                        int(data.get("error_code") or response.status),
                        int(parameters.get("retry_after") or 0),
                    )
                return data.get("result")
        except TelegramError:
            raise
        except (aiohttp.ServerTimeoutError, asyncio.TimeoutError, TimeoutError):
            raise TelegramTransportError(method, is_timeout=True) from None
        except aiohttp.ClientError:
            # aiohttp exceptions can include the URL, which contains the token.
            raise TelegramTransportError(method, is_network_error=True) from None
        except (ValueError, TypeError):
            raise TelegramError(method) from None

    async def get_updates(self, offset: int, *, timeout: int = 30) -> list[dict[str, Any]]:
        result = await self._request(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]},
            timeout=timeout + 10,
        )
        if not isinstance(result, list):
            raise TelegramError("getUpdates")
        return result

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._request("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        await self._request("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
