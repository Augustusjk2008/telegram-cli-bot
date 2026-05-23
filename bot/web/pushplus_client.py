from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

logger = logging.getLogger(__name__)


def _mask_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


class PushPlusClient:
    def __init__(
        self,
        *,
        enabled: bool,
        token: str,
        topic: str = "",
        template: str = "markdown",
        channel: str = "wechat",
        api_url: str = "https://www.pushplus.plus/send",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.token = str(token or "").strip()
        self.topic = str(topic or "").strip()
        self.template = str(template or "markdown").strip() or "markdown"
        self.channel = str(channel or "wechat").strip() or "wechat"
        self.api_url = str(api_url or "https://www.pushplus.plus/send").strip()
        self.timeout_seconds = max(0.1, float(timeout_seconds or 5.0))

    async def send(self, title: str, content: str, *, topic: str | None = None) -> bool:
        if not self.enabled or not self.token:
            return False

        payload: dict[str, Any] = {
            "token": self.token,
            "title": str(title or ""),
            "content": str(content or ""),
            "topic": str(topic if topic is not None else self.topic or ""),
            "template": self.template,
            "channel": self.channel,
        }
        payload = {key: value for key, value in payload.items() if value != ""}
        timeout = ClientTimeout(total=self.timeout_seconds)
        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, json=payload) as response:
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        data = {}
                    if response.status == 200 and int(data.get("code") or 0) == 200:
                        return True
                    logger.warning(
                        "PushPlus 推送失败 status=%s code=%s token=%s",
                        response.status,
                        data.get("code"),
                        _mask_token(self.token),
                    )
                    return False
        except (ClientError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("PushPlus 推送异常 token=%s error=%s", _mask_token(self.token), exc)
            return False
