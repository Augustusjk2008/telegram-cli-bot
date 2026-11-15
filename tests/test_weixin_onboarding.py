from __future__ import annotations

import pytest

from bot import config
from bot.weixin.onboarding import WeixinOnboardingService, WeixinOnboardingError


class FakeClient:
    def __init__(self):
        self.statuses = [{"status": "wait"}, {"status": "confirmed", "bot_token": "super-secret", "ilink_bot_id": "bot@im.bot", "ilink_user_id": "user@im.wechat", "baseurl": "https://region.invalid"}]
        self.closed = False

    async def get_bot_qrcode(self):
        return {"qrcode": "qr-token", "qrcode_img_content": "https://weixin.invalid/qr"}

    async def get_qrcode_status(self, _qrcode):
        return self.statuses.pop(0)

    async def close(self):
        self.closed = True


class FakeEnv:
    def __init__(self):
        self.payloads = []

    def patch(self, payload):
        self.payloads.append(payload)
        return {"changedKeys": ["WEIXIN_TOKEN"]}


@pytest.mark.asyncio
async def test_qr_setup_persists_credentials_without_returning_token(monkeypatch):
    monkeypatch.setattr(config, "WEIXIN_ALLOWED_USER_IDS", set(), raising=False)
    client = FakeClient()
    env = FakeEnv()
    service = WeixinOnboardingService(
        env_service=env,
        client_factory=lambda **_: client,
        poll_interval=0.01,
        setup_ttl_seconds=10,
    )
    initial = await service.start_setup()
    assert initial["status"] == "waiting_scan"
    assert "super-secret" not in str(initial)
    setup = await service.get_setup(initial["setup_id"])
    for _ in range(100):
        if setup["status"] == "confirmed":
            break
        await __import__("asyncio").sleep(0.01)
        setup = await service.get_setup(initial["setup_id"])
    assert setup["status"] == "confirmed"
    assert setup["needs_restart"] is True
    assert setup["account_id"] == "bot@….bot"
    assert "super-secret" not in str(setup)
    assert env.payloads[0]["values"]["WEIXIN_TOKEN"] == "super-secret"
    assert env.payloads[0]["values"]["WEIXIN_ACCOUNT_ID"] == "bot@im.bot"
    assert env.payloads[0]["values"]["WEIXIN_ALLOWED_USER_IDS"] == ["user@im.wechat"]
    await service.close()


@pytest.mark.asyncio
async def test_only_one_setup_is_active_and_cancel_is_stable():
    service = WeixinOnboardingService(
        env_service=FakeEnv(),
        client_factory=lambda **_: FakeClient(),
        poll_interval=10,
    )
    setup = await service.start_setup()
    with pytest.raises(WeixinOnboardingError) as error:
        await service.start_setup()
    assert error.value.code == "weixin_setup_active"
    cancelled = await service.cancel_setup(setup["setup_id"])
    assert cancelled["status"] == "cancelled"
    await service.close()


@pytest.mark.asyncio
async def test_qr_setup_preserves_an_existing_allowlist(monkeypatch):
    monkeypatch.setattr(config, "WEIXIN_ALLOWED_USER_IDS", {"existing@im.wechat"}, raising=False)
    client = FakeClient()
    env = FakeEnv()
    service = WeixinOnboardingService(
        env_service=env,
        client_factory=lambda **_: client,
        poll_interval=0.01,
        setup_ttl_seconds=10,
    )
    setup = await service.start_setup()
    for _ in range(100):
        snapshot = await service.get_setup(setup["setup_id"])
        if snapshot["status"] == "confirmed":
            break
        await __import__("asyncio").sleep(0.01)
    assert "WEIXIN_ALLOWED_USER_IDS" not in env.payloads[0]["values"]
    await service.close()
