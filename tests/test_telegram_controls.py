from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from bot.chat_identity import chat_session_user_id
from bot.telegram.client import TelegramClient
from bot.telegram.state import TelegramState
from bot.web import api_service
from bot.web.exposure_service import WebExposureService
from bot.web.server import WebApiServer
from tests.test_telegram_gateway import done, gateway, install_stream, update


def callback(update_id, token, *, user_id=42, chat_id=42, chat_type="private"):
    return {"update_id": update_id, "callback_query": {
        "id": f"callback-{update_id}", "from": {"id": user_id}, "data": token,
        "message": {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": 123, "is_bot": True}},
    }}


def button(gateway, text, index=-1):
    return next(item for row in gateway.client.markups[index]["inline_keyboard"] for item in row if item["text"] == text)


def reply(update_id, message_id, text):
    event = update(update_id, text)
    event["message"]["reply_to_message"] = {"message_id": message_id}
    return event


@pytest.mark.asyncio
async def test_config_command_queries_and_updates_model_reasoning_and_cluster(gateway, monkeypatch):
    monkeypatch.setattr(api_service, "CLI_MODEL_OPTIONS", {"codex": ["gpt-5", "gpt-4"]})

    await gateway.receive_update(update(1, "/config dev"))
    assert "[dev] 智能体配置" in gateway.client.messages[-1][1]
    assert "模型：" in gateway.client.messages[-1][1]
    assert "集群：关闭" in gateway.client.messages[-1][1]

    await gateway.receive_update(update(2, "/config dev model gpt-5"))
    await gateway.receive_update(update(3, "/config dev reasoning high"))
    await gateway.receive_update(update(4, "/config dev cluster on"))

    profile = gateway.manager.get_profile("dev")
    assert profile.cli_params.get_param("codex", "model") == "gpt-5"
    assert profile.cli_params.get_param("codex", "reasoning_effort") == "high"
    assert profile.cluster.enabled is True
    assert "集群：开启" in gateway.client.messages[-1][1]


@pytest.mark.asyncio
async def test_native_config_command_uses_model_and_reasoning_api(gateway, monkeypatch):
    profile = gateway.manager.get_profile("dev")
    profile.supported_execution_modes = ["native_agent"]
    profile.default_execution_mode = "native_agent"
    models = {
        "items": [{
            "id": "openai/gpt-5",
            "label": "GPT-5",
            "reasoning_efforts": ["low", "high"],
            "default_reasoning_effort": "low",
        }],
        "selected_model": "openai/gpt-5",
        "selected_reasoning_effort": "low",
    }
    update_model = AsyncMock(return_value=models)
    monkeypatch.setattr(api_service, "get_native_agent_models_payload", lambda *_args: models)
    monkeypatch.setattr(api_service, "update_bot_native_agent_model", update_model)

    await gateway.receive_update(update(1, "/config dev model openai/gpt-5"))
    await gateway.receive_update(update(2, "/config dev reasoning high"))

    assert update_model.await_args_list[0].args[1:] == ("dev", "openai/gpt-5", "low")
    assert update_model.await_args_list[1].args[1:] == ("dev", "openai/gpt-5", "high")


@pytest.mark.asyncio
async def test_select_reply_and_final_buttons_keep_original_target(gateway, monkeypatch):
    calls = install_stream(monkeypatch, [done()])
    await gateway.receive_update(update(1, "/start"))
    assert gateway.client.markups[0]["is_persistent"] is True
    await gateway.receive_update(callback(2, button(gateway, "dev")["callback_data"]))
    assert gateway.state.selected_target(42, 42) == "dev"
    assert calls == []
    await gateway.receive_update(callback(3, button(gateway, "发消息")["callback_data"]))
    prompt_id = len(gateway.client.messages)
    assert gateway.client.markups[-1]["force_reply"] is True
    assert "[dev]" in gateway.client.messages[-1][1]
    await gateway.receive_update(update(4, "🤖 智能体"))
    await gateway.receive_update(callback(5, button(gateway, "ops")["callback_data"]))
    await gateway.receive_update(reply(6, prompt_id, "to ops /new"))
    assert calls[0][0][1:] == ("dev", chat_session_user_id(42), "to ops /new")
    assert calls[0][1]["expected_conversation_id"] is None
    assert gateway.client.messages[-1][1].startswith("[dev]")
    result_button = button(gateway, "继续聊")
    record = gateway.state.get_interaction(result_button["callback_data"])
    assert (record["alias"], record["conversation_id"]) == ("dev", "conv-1")
    assert len(result_button["callback_data"].encode("utf-8")) <= 64
    assert gateway.client.callbacks == ["callback-2", "callback-3", "callback-5"]
    # A second update replying to the same prompt must not execute again.
    await gateway.receive_update(reply(7, prompt_id, "another message"))
    assert len(calls) == 1
    assert "已使用" in gateway.client.messages[-1][1]
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42, "main")
    session.active_conversation_id = "conv-1"
    await gateway.receive_update(callback(8, result_button["callback_data"]))
    await gateway.receive_update(reply(9, len(gateway.client.messages), "continue"))
    assert calls[-1][0][1:] == ("dev", chat_session_user_id(42), "continue")
    assert calls[-1][1]["expected_conversation_id"] == "conv-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["/new", "✉️ 发消息", "📊 状态", "  多行\n正文\n"])
async def test_bound_reply_body_is_literal(gateway, monkeypatch, body):
    calls = install_stream(monkeypatch, [done()])
    gateway.state.select_target(42, 42, "dev")
    await gateway.receive_update(update(1, "✉️ 发消息"))
    await gateway.receive_update(reply(2, len(gateway.client.messages), body))
    assert calls[0][0][3] == body


@pytest.mark.asyncio
async def test_continue_button_is_invalid_after_web_switch(gateway, monkeypatch):
    install_stream(monkeypatch, [done()])
    await gateway.receive_update(update())
    token = button(gateway, "继续聊")["callback_data"]
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", chat_session_user_id(42), "main")
    session.active_conversation_id = "conv-other"
    await gateway.receive_update(callback(2, token))
    assert "刷新面板" in gateway.client.messages[-1][1]
    assert not any(markup and markup.get("force_reply") for markup in gateway.client.markups)


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,chat_id,chat_type", [(99, 42, "private"), ("42", 42, "private"), (42, 42, "group"), (43, 42, "private"), (42, 43, "private")])
async def test_callback_authenticates_actor_and_bound_chat(gateway, user_id, chat_id, chat_type):
    gateway.allowed_user_ids = frozenset({42, 43})
    token = gateway.state.new_interaction("select", 42, 42, "dev", None)
    task = gateway.receive_update(callback(1, token, user_id=user_id, chat_id=chat_id, chat_type=chat_type))
    if task:
        await task
    assert gateway.client.callbacks == ["callback-1"]
    assert gateway.state.selected_target(42, 42) is None
    assert gateway.state.selected_target(43, 42) is None
    assert gateway.state.selected_target(42, 43) is None


def test_interactions_persist_and_isolate_bot_user_chat(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = TelegramState(path, "123")
    first.select_target(42, 42, "dev")
    token = first.new_interaction("reply", 42, 42, "dev", None)
    first.bind_reply(token, 100)
    first.close()
    reopened, other_bot = TelegramState(path, "123"), TelegramState(path, "456")
    try:
        assert reopened.selected_target(42, 42) == "dev"
        assert reopened.selected_target(43, 42) is None
        assert reopened.selected_target(42, 43) is None
        assert reopened.get_reply(42, 100)["token"] == token
        assert reopened.get_reply(43, 100) is None
        assert other_bot.get_interaction(token) is None
        assert other_bot.get_reply(42, 100) is None
        assert other_bot.selected_target(42, 42) is None
        assert not reopened.claim_interaction(token, 43, 42)
        assert not reopened.claim_interaction(token, 42, 43)
        assert reopened.claim_interaction(token, 42, 42)
        assert not reopened.claim_interaction(token, 42, 42)
    finally:
        reopened.close()
        other_bot.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["expired", "consumed", "switched", "disabled", "archived", "wrong_user", "unknown"])
async def test_invalid_reply_never_falls_back_to_command_routing(gateway, monkeypatch, condition):
    calls = install_stream(monkeypatch, [done()])
    token = gateway.state.new_interaction("reply", 43 if condition == "wrong_user" else 42, 42, "dev", None,
                                          ttl=-1 if condition == "expired" else 100)
    gateway.state.bind_reply(token, 100)
    if condition == "consumed":
        gateway.state.finish_interaction(token, "done")
    elif condition == "switched":
        _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42, "main")
        session.active_conversation_id = "another"
    elif condition == "disabled":
        gateway.manager.managed_profiles["dev"].enabled = False
    elif condition == "archived":
        gateway.manager.managed_profiles["dev"].archived = True
    await gateway.receive_update(reply(1, 101 if condition == "unknown" else 100, "to ops run this"))
    assert calls == []
    assert "刷新" in gateway.client.messages[-1][1]


@pytest.mark.asyncio
async def test_create_confirmation_is_atomic_and_does_not_start_model(gateway, monkeypatch):
    original = await api_service.create_conversation(gateway.manager, "dev", 42)
    old_id = original["conversation"]["id"]
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42, "main")
    store = api_service._get_chat_store(session)
    before = store.list_messages(old_id)
    real_create = api_service.create_conversation
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def create(*args, **kwargs):
        calls.append(kwargs)
        entered.set()
        await release.wait()
        return await real_create(*args, **kwargs)

    monkeypatch.setattr(api_service, "create_conversation", create)
    model_calls = install_stream(monkeypatch, [done()])
    gateway.state.select_target(42, 42, "dev")
    await gateway.receive_update(update(1, "🆕 新会话"))
    token = button(gateway, "确认新建会话")["callback_data"]
    task = gateway.receive_update(callback(2, token))
    await asyncio.wait_for(entered.wait(), 2)
    await gateway.receive_update(callback(3, token))
    assert "处理中" in gateway.client.messages[-1][1]
    assert gateway.client.callbacks == ["callback-2", "callback-3"]
    release.set()
    await task
    result = gateway.client.messages[-1][1]
    await gateway.receive_update(callback(4, token))
    assert gateway.client.messages[-1][1] == result
    assert len(calls) == 1 and calls[0]["expected_conversation_id"] == old_id
    assert model_calls == []
    assert session.active_conversation_id != old_id
    assert store.get_conversation(old_id)["id"] == old_id
    assert store.list_messages(old_id) == before
    assert store.list_messages(session.active_conversation_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["expired", "switched", "disabled"])
async def test_create_confirmation_rejects_stale_target(gateway, condition):
    token = gateway.state.new_interaction("create_confirm", 42, 42, "dev", None,
                                          ttl=-1 if condition == "expired" else 100)
    if condition == "switched":
        await api_service.create_conversation(gateway.manager, "dev", 42)
    if condition == "disabled":
        gateway.manager.managed_profiles["dev"].enabled = False
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42, "main")
    current = session.active_conversation_id
    await gateway.receive_update(callback(1, token))
    assert session.active_conversation_id == current
    assert "刷新" in gateway.client.messages[-1][1]


@pytest.mark.asyncio
async def test_stop_confirmation_binds_exact_snapshot_and_deduplicates(gateway, monkeypatch):
    snapshot = {"conversation_id": None, "execution_mode": "cli", "phase": "preparing",
                "execution_id": "prepare-1", "turn_id": None, "cluster_run_id": "run-1",
                "cluster_task_ids": ["child-1", "child-2"], "context_usage": None}
    monkeypatch.setattr(api_service, "get_conversation_control_snapshot", AsyncMock(return_value=snapshot))
    stop = AsyncMock(return_value={"killed": True, "message": "已请求停止"})
    monkeypatch.setattr(api_service, "kill_user_process", stop)
    gateway.state.select_target(42, 42, "dev")
    await gateway.receive_update(update(1, "⏹ 停止任务"))
    assert "child-1, child-2" in gateway.client.messages[-1][1]
    stop.assert_not_called()
    token = button(gateway, "确认停止任务")["callback_data"]
    await gateway.receive_update(callback(2, token))
    await gateway.receive_update(callback(3, token))
    stop.assert_awaited_once_with(gateway.manager, "dev", chat_session_user_id(42), agent_id="main",
                                  expected_conversation_id=None, expected_control=snapshot)
    assert gateway.client.messages[-1] == gateway.client.messages[-2]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,tasks,expected", [
    ("waiting_approval", [], "等待审批"), ("running", ["child-1"], "子任务：1 个"),
    ("idle", [], "空闲"), ("preparing", [], "准备中"),
])
async def test_status_displays_service_phase_and_unknown_context(gateway, monkeypatch, phase, tasks, expected):
    snapshot = {"conversation_id": None, "execution_mode": "native_agent", "phase": phase,
                "execution_id": None, "turn_id": None, "cluster_run_id": None,
                "cluster_task_ids": tasks, "context_usage": None}
    monkeypatch.setattr(api_service, "get_conversation_control_snapshot", AsyncMock(return_value=snapshot))
    gateway.state.select_target(42, 42, "dev")
    await gateway.receive_update(update(1, "📊 状态"))
    assert expected in gateway.client.messages[-1][1]
    assert "context left: unknown" in gateway.client.messages[-1][1]


@pytest.mark.asyncio
async def test_result_buttons_use_current_public_url_and_bound_conversation(gateway, monkeypatch):
    tunnel = Mock()
    tunnel.snapshot.return_value = {"public_url": "https://host.example/node/node-1/"}
    server = object.__new__(WebApiServer)
    server._exposure_service = WebExposureService(
        tunnel_service=tunnel, fixed_public_forward_enabled=True,
        fixed_public_forward_url="https://host.example/node/node-1/", node_id="node-1",
    )
    gateway.chat_url = server.chat_public_url
    install_stream(monkeypatch, [done(content="x" * 6000)])
    await gateway.receive_update(update())
    assert gateway.client.markups[-2] is None
    assert button(gateway, "打开 Web")["url"] == "https://host.example/node/node-1/bots/dev/chat?conversation_id=conv-1"
    server._exposure_service = WebExposureService(tunnel_service=tunnel)
    tunnel.snapshot.return_value = {"public_url": "https://new.example"}
    await gateway.receive_update(update(2))
    assert button(gateway, "打开 Web")["url"].startswith("https://new.example/")
    tunnel.snapshot.return_value = {"public_url": ""}
    await gateway.receive_update(update(3))
    assert "callback_data" in button(gateway, "打开 Web（需配置公网地址）")


@pytest.mark.asyncio
async def test_client_sends_markup_and_acknowledges_callbacks():
    client = TelegramClient("123:secret")
    client._request = AsyncMock(side_effect=[[], {"message_id": 1}, True])
    assert await client.get_updates(2) == []
    markup = {"force_reply": True}
    await client.send_message(42, "prompt", reply_markup=markup)
    await client.answer_callback_query("callback-1")
    requests = client._request.call_args_list
    assert requests[0].args[1]["allowed_updates"] == ["message", "callback_query"]
    assert requests[1].args[1]["reply_markup"] == markup
    assert requests[2].args == ("answerCallbackQuery", {"callback_query_id": "callback-1", "text": ""})
