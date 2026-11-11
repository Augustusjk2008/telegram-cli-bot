from __future__ import annotations

from unittest.mock import Mock

import pytest

from bot import config
from bot.telegram.gateway import TelegramGateway
from bot.telegram.state import TelegramState
from bot.web.server import WebApiServer
from tests.test_telegram_controls import button, callback
from tests.test_telegram_gateway import FakeTelegramClient, gateway, update  # noqa: F401


class FakeHost:
    def __init__(self, *, refusal=""):
        self.refusal = refusal
        self.exposure_restarts = 0
        self.restart_requests = 0
        self.status = {
            "version": "9.9.9", "pid": 4321, "uptime_seconds": 3700, "busy_reason": "",
            "exposure": {
                "mode": "fixed_public_forward", "status": "error",
                "public_url": "https://hub.example/node/n1", "last_error": "frps 端口不通/安全组未放通",
                "heartbeat_status": "error", "heartbeat_last_error": "Hub 心跳超时",
                "log_tail": ["connect to server error: dial tcp: i/o timeout"],
            },
        }

    async def host_status(self):
        return self.status

    async def restart_public_exposure(self):
        self.exposure_restarts += 1
        self.status["exposure"].update(status="running", last_error="", heartbeat_status="online")
        return self.status["exposure"]

    def host_restart_refusal(self):
        return self.refusal

    def request_host_restart(self):
        self.restart_requests += 1
        return self.refusal


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["/host", "🖥 宿主"])
async def test_host_panel_reconnects_exposure_once_per_button(gateway, entry):
    host = gateway.host = FakeHost()
    await gateway.receive_update(update(1, entry))
    panel = gateway.client.messages[-1][1]
    assert "固定公网转发（frp），异常" in panel and "frps 端口不通" in panel and "i/o timeout" in panel

    token = button(gateway, "🔁 重连 frp")["callback_data"]
    await gateway.receive_update(callback(2, token))
    await gateway.receive_update(callback(3, token))
    assert host.exposure_restarts == 1
    assert "固定公网转发（frp），运行中" in gateway.client.messages[-2][1]
    assert "已执行重连" in gateway.client.messages[-1][1]

    expired = gateway.state.new_interaction("host_exposure_restart", 42, 42, "", None, ttl=-1)
    await gateway.receive_update(callback(4, expired))
    assert host.exposure_restarts == 1
    assert "/host" in gateway.client.messages[-1][1]


@pytest.mark.asyncio
async def test_confirmed_restart_replies_first_and_next_host_reports_back_online(gateway, tmp_path):
    host = gateway.host = FakeHost()
    host.status["busy_reason"] = "智能体仍有运行中的任务"
    await gateway.receive_update(update(1, "/host"))
    await gateway.receive_update(callback(2, button(gateway, "♻️ 重启后端")["callback_data"]))
    assert "智能体仍有运行中的任务" in gateway.client.messages[-1][1]
    assert host.restart_requests == 0

    confirm = button(gateway, "确认重启后端")["callback_data"]
    await gateway.receive_update(callback(3, confirm))
    await gateway.receive_update(callback(4, confirm))
    assert host.restart_requests == 1
    assert "已请求重启后端" in gateway.client.messages[-1][1]

    restarted = TelegramGateway(
        gateway.manager, FakeTelegramClient(), TelegramState(tmp_path / "telegram.sqlite3", "123"), {42}, host=host,
    )
    try:
        await restarted._recover_state()
        await restarted._recover_state()
        notices = [text for _, text in restarted.client.messages if "恢复在线" in text]
        assert len(notices) == 1 and "PID：4321" in notices[0]
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_restart_is_refused_without_back_online_marker(gateway):
    host = gateway.host = FakeHost(refusal="升级交接进行中，暂不能重启")
    token = gateway.state.new_interaction("host_restart_confirm", 42, 42, "", None)
    await gateway.receive_update(callback(1, token))
    assert host.restart_requests == 0
    assert gateway.client.messages[-1][1] == "重启未执行：升级交接进行中，暂不能重启。"
    assert gateway.state.list_restart_notices() == []


def test_server_refuses_restart_during_update_handoff(monkeypatch):
    server = object.__new__(WebApiServer)
    server._update_exit_pending = False
    server._schedule_restart_request = Mock()
    monkeypatch.setattr(config, "RESTART_REQUESTED", False)
    monkeypatch.setattr(config, "UPDATE_REQUESTED", False)
    monkeypatch.setattr(config, "UPDATE_DRAINING", True)
    assert server.request_host_restart() == "升级交接进行中，暂不能重启"
    server._schedule_restart_request.assert_not_called()
    monkeypatch.setattr(config, "UPDATE_DRAINING", False)
    assert server.request_host_restart() == ""
    server._schedule_restart_request.assert_called_once_with()
