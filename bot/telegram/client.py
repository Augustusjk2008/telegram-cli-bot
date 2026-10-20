"""Telegram Bot API transport with credential-free errors."""

from __future__ import annotations

from typing import Any

import aiohttp


class TelegramError(Exception):
    def __init__(self, method: str, code: int = 0, retry_after: int = 0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Telegram {method} failed (code={code})")


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
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            # aiohttp exceptions can include the URL, which contains the token.
            raise TelegramError(method) from None

    async def get_updates(self, offset: int, *, timeout: int = 30) -> list[dict[str, Any]]:
        result = await self._request(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
            timeout=timeout + 10,
        )
        if not isinstance(result, list):
            raise TelegramError("getUpdates")
        return result

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        return await self._request("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        })

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
