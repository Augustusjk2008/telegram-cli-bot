from __future__ import annotations

import aiohttp
import pytest

from bot.weixin.client import (
    WeixinClient,
    WeixinError,
    WeixinRateLimitError,
    WeixinSessionExpiredError,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.asyncio
async def test_qr_updates_and_message_requests_use_ilink_headers_and_context_token():
    transport = FakeTransport([
        {"qrcode": "qr-1", "qrcode_img_content": "https://weixin.example/qr"},
        {"status": "confirmed", "bot_token": "secret"},
        {"ret": 0, "msgs": [], "get_updates_buf": "next"},
        {"ret": 0},
    ])
    client = WeixinClient("secret", account_id="bot@im.bot", base_url="https://test.invalid", transport=transport, max_retries=0)

    assert (await client.get_bot_qrcode())["qrcode"] == "qr-1"
    assert (await client.get_qrcode_status("qr-1"))["status"] == "confirmed"
    updates = await client.get_updates("cursor")
    await client.send_message("user@im.wechat", "hello", context_token="ctx-1", client_id="client-1")

    qr_method, qr_url, qr_options = transport.calls[0]
    assert qr_method == "GET" and "bot_type=3" in qr_url
    assert qr_options["headers"]["iLink-App-Id"] == "bot"
    assert "Authorization" not in qr_options["headers"]
    assert updates["get_updates_buf"] == "next"
    method, url, options = transport.calls[-1]
    assert method == "POST" and url.endswith("/ilink/bot/sendmessage")
    assert options["headers"]["AuthorizationType"] == "ilink_bot_token"
    assert options["headers"]["Authorization"] == "Bearer secret"
    assert options["json"]["msg"]["context_token"] == "ctx-1"
    assert options["json"]["base_info"]["channel_version"]


@pytest.mark.asyncio
async def test_transport_and_api_errors_are_classified_without_token_or_url():
    secret = "secret-token-value"
    transport = FakeTransport([aiohttp.ClientConnectionError(f"https://test.invalid/{secret}")])
    client = WeixinClient(secret, base_url="https://test.invalid", transport=transport, max_retries=0)
    with pytest.raises(WeixinError) as error:
        await client.get_updates()
    assert secret not in str(error.value)
    assert "test.invalid" not in str(error.value)

    rate_limited = WeixinClient("secret", transport=FakeTransport([{"ret": -2}]), max_retries=0)
    with pytest.raises(WeixinRateLimitError):
        await rate_limited.get_updates()

    expired = WeixinClient("secret", transport=FakeTransport([{"ret": -14}]), max_retries=0)
    with pytest.raises(WeixinSessionExpiredError) as expired_error:
        await expired.get_updates()
    assert expired_error.value.session_expired
