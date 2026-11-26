import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.streams import EMPTY_PAYLOAD, StreamReader
from aiohttp.test_utils import make_mocked_request

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web import api_common, api_service, chat_targets, server as server_module
from bot.web.auth_store import (
    CAP_CHAT_SEND, CAP_VIEW_BOT_STATUS, CAP_VIEW_CHAT_HISTORY, CAP_VIEW_CHAT_TRACE,
    WebAccount, WebAuthSession,
)
from bot.web.chat_store import ChatStore
from bot.web.translation_config import TranslationConfig
from bot.web.routes import chat_routes, translation_routes
from bot.web.server import WebApiServer, error_middleware


BOT = "/api/bots/main"
SESSIONS = BOT + "/sessions"


@pytest.fixture
def api(tmp_path, monkeypatch):
    server = object.__new__(WebApiServer)
    server._chat_stream_tasks = set()
    server.manager = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(tmp_path / "bots.json"))
    capabilities = (CAP_VIEW_BOT_STATUS, CAP_VIEW_CHAT_HISTORY, CAP_VIEW_CHAT_TRACE, CAP_CHAT_SEND)
    members = {
        name: WebAuthSession(
            token=name, account=WebAccount(account_id=name, username=name, role="member", session_user_id=index),
            created_at="", capabilities=grants,
        )
        for index, (name, grants) in enumerate((
            ("sender", capabilities), ("reader", (CAP_VIEW_BOT_STATUS, CAP_VIEW_CHAT_HISTORY)),
            ("outsider", capabilities),
        ), start=101)
    }
    monkeypatch.setattr(server_module, "_WEB_AUTH_STORE", SimpleNamespace(
        get_session=members.get, can_bootstrap_without_auth=lambda: False,
    ))
    monkeypatch.setattr(server_module, "_is_loopback_auto_auth_allowed", lambda _: False)
    monkeypatch.setattr(server_module, "_BOT_PERMISSION_STORE", SimpleNamespace(
        can_operate_bot=lambda account, alias: account != "outsider" and alias == "main",
        allowed_bots_for_account=lambda _: {"main"}, owned_bot_aliases=lambda _: set(), bot_owner=lambda _: "",
    ))
    app = web.Application()
    chat_routes.register(app, server)
    translator = Mock()
    translator.config_store.get_config.return_value = TranslationConfig(
        translate_assistant_enabled=True, method="cli", cli_type="codex", cli_path="codex",
    )
    translation_routes.register(app, server, service=translator)
    return SimpleNamespace(app=app, server=server, translator=translator)


async def dispatch(api, method, path, *, body=None, token="sender", chunked=False):
    headers = {"Host": "example.test"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = EMPTY_PAYLOAD
    if body is not None:
        encoded = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        if chunked:
            headers["Transfer-Encoding"] = "chunked"
        else:
            headers["Content-Length"] = str(len(encoded))
        payload = StreamReader(Mock(), limit=65536)
        payload.feed_data(encoded)
        payload.feed_eof()
    request = make_mocked_request(method, path, headers=headers, app=api.app, payload=payload)
    request._match_info = await api.app.router.resolve(request)
    request._match_info.add_app(api.app)
    return await error_middleware(request, request.match_info.handler)


async def data(api, method, path, **options):
    response = await dispatch(api, method, path, **options)
    assert response.status == 200, response.text
    return json.loads(response.text)["data"]


@pytest.mark.asyncio
async def test_authorization_precedes_session_lookup(api, monkeypatch):
    lookup = Mock(side_effect=AssertionError("unauthorized session lookup"))
    monkeypatch.setattr(chat_targets, "resolve_named_chat_target", lookup)
    monkeypatch.setattr(chat_targets, "create_chat_session", lookup)
    monkeypatch.setattr(chat_targets, "list_chat_sessions", lookup)
    for method, path, token, expected in (
        ("GET", SESSIONS, "", 401),
        ("GET", SESSIONS, "outsider", 403),
        ("GET", SESSIONS + "/unknown/history", "outsider", 403),
        ("POST", SESSIONS, "reader", 403),
        ("POST", SESSIONS + "/unknown/kill", "reader", 403),
        ("POST", SESSIONS + "/unknown/history/msg/translation/retry", "reader", 403),
        ("GET", SESSIONS + "/unknown/history/msg/trace", "reader", 403),
    ):
        response = await dispatch(api, method, path, body={"title": "one"} if method == "POST" else None, token=token)
        assert response.status == expected
    lookup.assert_not_called()


@pytest.mark.asyncio
async def test_catalog_validates_body_and_refuses_unknown_sessions(api):
    for body in ([], {}, {"title": 5}, {"title": "  "}, {"title": "x", "working_dir": "/elsewhere"},
                 {"title": "x", "cli_type": "claude"}, {"title": "x", "id": "picked"}):
        assert (await dispatch(api, "POST", SESSIONS, body=body)).status == 400
    listed = await data(api, "GET", SESSIONS, token="reader")
    assert listed["enabled"] and [item["id"] for item in listed["items"]] == ["main"]
    assert await data(api, "GET", SESSIONS + "/main/history") == await data(api, "GET", BOT + "/history")
    for session_id in ("cluster-slot-1", "ses_" + "0" * 32):
        response = await dispatch(api, "GET", f"{SESSIONS}/{session_id}/history")
        assert (response.status, json.loads(response.text)["error"]["code"]) == (404, "session_not_found")


@pytest.mark.asyncio
async def test_path_selects_session_for_mutation_and_subsequent_reads(api):
    first = await data(api, "POST", SESSIONS, body={"title": "First"})
    second = await data(api, "POST", SESSIONS, body={"title": "Second"})
    assert first.keys() == second.keys() == {"id", "title"}
    listed = await data(api, "GET", SESSIONS, token="reader")
    assert first in listed["items"] and second in listed["items"]

    base = f"{SESSIONS}/{first['id']}"
    sibling = f"{SESSIONS}/{second['id']}"
    created = await data(api, "POST", base + "/conversations", body={"title": "In first", "session_id": first["id"]})
    conversation_id = created["conversation"]["id"]
    for path, expected in ((base, True), (sibling, False), (BOT, False)):
        result = await data(api, "GET", path + "/conversations", token="reader")
        assert (conversation_id in [row["id"] for row in result["items"]]) == expected
    attempt = await dispatch(api, "POST", sibling + f"/conversations/{conversation_id}/select", body={})
    assert attempt.status == 404


@pytest.mark.asyncio
async def test_conflicting_selectors_preserve_conversations_on_default_and_named_routes(api):
    named = await data(api, "POST", SESSIONS, body={"title": "Named"})
    named_path = f"{SESSIONS}/{named['id']}/conversations"
    default_path = BOT + "/conversations"
    explicit_default = SESSIONS + "/main/conversations"
    default_created = await data(api, "POST", explicit_default, body={"title": "Default", "sessionId": "main"})
    default_id = default_created["conversation"]["id"]
    named_created = await data(api, "POST", named_path, body={"title": "Named"})
    named_id = named_created["conversation"]["id"]

    for path, conflicting_body in (
        (f"{default_path}/{default_id}", {"session_id": named["id"]}),
        (f"{explicit_default}/{default_id}?session_id=main", {"sessionId": named["id"]}),
        (f"{named_path}/{named_id}?sessionId={named['id']}", {"session_id": "main"}),
        (f"{named_path}/{named_id}?session_id={named['id']}&session_id=main", {}),
    ):
        response = await dispatch(api, "DELETE", path, body=conflicting_body, chunked=True)
        assert (response.status, json.loads(response.text)["error"]["code"]) == (400, "session_scope_mismatch")

    for path, expected_id in ((default_path, default_id), (named_path, named_id)):
        result = await data(api, "GET", path)
        assert expected_id in [row["id"] for row in result["items"]]

    await data(api, "DELETE", f"{named_path}/{named_id}", body={"sessionId": named["id"]})
    result = await data(api, "GET", named_path)
    assert named_id not in [row["id"] for row in result["items"]]
    result = await data(api, "GET", explicit_default)
    assert default_id in [row["id"] for row in result["items"]]


@pytest.mark.asyncio
async def test_named_send_uses_configured_cli_and_never_notifies_default_chat(api, monkeypatch):
    item = await data(api, "POST", SESSIONS, body={"title": "Named"})
    base = f"{SESSIONS}/{item['id']}"
    resolver = Mock(wraps=chat_targets.resolve_named_chat_target)
    monkeypatch.setattr(chat_targets, "resolve_named_chat_target", resolver)
    run = AsyncMock(return_value={"output": "ok"})
    monkeypatch.setattr(server_module, "run_chat", run)
    notify = Mock()
    monkeypatch.setattr(api.server, "_schedule_chat_terminal_event", notify)
    # Even a conflicting body and query must not address a physical cluster role.
    invalid = await dispatch(api, "POST", base + "/chat?agent_id=main", body={"message": "x", "agentId": "cluster-slot-1"})
    assert invalid.status == 400
    run.assert_not_called()

    await data(api, "POST", base + "/chat", body={"message": "hello", "working_dir": "/outside", "cli_type": "alternate"})
    resolver.assert_called_once()
    target = run.await_args.kwargs["target"]
    assert target.session.web_session_id == item["id"]
    assert target.session.working_dir == api.server.manager.main_profile.working_dir
    assert target.profile.cli_type == api.server.manager.main_profile.cli_type
    run.side_effect = api_common.WebApiError(409, "session_busy", "busy")
    assert (await dispatch(api, "POST", base + "/chat", body={"message": "again"})).status == 409
    notify.assert_not_called()

    run.side_effect = None
    # A stale client must not send the selected session's prompt into the default chat.
    before = run.await_count
    assert (await dispatch(api, "POST", BOT + "/chat?session_id=" + item["id"], body={"message": "wrong"})).status == 400
    assert (await dispatch(api, "POST", base + "/chat", body={"message": "wrong", "session_id": "main"})).status == 400
    assert run.await_count == before
    await data(api, "POST", BOT + "/chat", body={"message": "default"})
    assert "target" not in run.await_args.kwargs
    notify.assert_called_once()


@pytest.mark.asyncio
async def test_named_stream_resolves_before_sse_headers_and_skips_terminal_notifications(api, monkeypatch):
    item = await data(api, "POST", SESSIONS, body={"title": "Stream"})
    resolver = Mock(wraps=chat_targets.resolve_named_chat_target)
    monkeypatch.setattr(chat_targets, "resolve_named_chat_target", resolver)
    notify = Mock()
    monkeypatch.setattr(api.server, "_schedule_chat_terminal_event", notify)

    async def events():
        yield {"type": "meta", "turn_id": "turn-1", "assistant_message_id": "reply-1"}
        yield {"type": "done", "output": "ok", "turn_id": "turn-1", "assistant_message_id": "reply-1"}

    stream = Mock(side_effect=lambda *args, **kwargs: events())
    monkeypatch.setattr(server_module, "stream_chat", stream)
    response = await dispatch(api, "POST", SESSIONS + "/missing/chat/stream", body={"message": "hello"})
    assert response.status == 404 and response.content_type == "application/json"
    stream.assert_not_called()
    resolver.reset_mock()
    response = await dispatch(api, "POST", f"{SESSIONS}/{item['id']}/chat/stream", body={"message": "hello"})
    assert response.status == 200 and response.content_type == "text/event-stream"
    resolver.assert_called_once()
    assert stream.call_args.kwargs["target"].session.web_session_id == item["id"]
    notify.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", ["prepare_reset", "ready_broken_pipe", "cancel_ready", "cancel_waiting"])
async def test_named_turn_outlives_sse_disconnect_before_first_event(api, monkeypatch, disconnect):
    item = await data(api, "POST", SESSIONS, body={"title": "Background"})
    base = f"{SESSIONS}/{item['id']}"
    started, ready, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    completions = []

    async def cli_events(*args, target, **kwargs):
        started.set()
        if disconnect != "cancel_waiting":
            yield {"type": "meta"}
        await release.wait()
        completions.append((target.session.web_session_id, target.session.stop_requested))
        yield {"type": "done", "output": "finished"}

    cli = Mock(side_effect=cli_events)
    gateway_notification = AsyncMock()
    terminal_notification = Mock()
    monkeypatch.setattr(api_service, "_stream_cli_chat", cli)
    monkeypatch.setattr(api_service, "_notify_telegram_completion", gateway_notification)
    monkeypatch.setattr(api.server, "_schedule_chat_terminal_event", terminal_notification)

    async def prepare(response, request):
        if disconnect == "prepare_reset":
            raise ConnectionResetError()

    async def write(response, chunk):
        assert chunk == b": ready\n\n"
        ready.set()
        if disconnect == "ready_broken_pipe":
            raise BrokenPipeError()
        if disconnect == "cancel_ready":
            await asyncio.Future()

    monkeypatch.setattr(web.StreamResponse, "prepare", prepare)
    monkeypatch.setattr(web.StreamResponse, "write", write)
    handler = asyncio.create_task(dispatch(api, "POST", base + "/chat/stream", body={"message": "hello"}))
    try:
        if disconnect.startswith("cancel"):
            await asyncio.wait_for(ready.wait(), 2)
            await asyncio.wait_for(started.wait(), 2)
            handler.cancel()
            with pytest.raises(asyncio.CancelledError):
                await handler
        else:
            await asyncio.wait_for(handler, 2)
        await asyncio.wait_for(started.wait(), 2)
        assert not completions
        if disconnect == "cancel_waiting":
            assert (await data(api, "POST", base + "/kill"))["killed"]
    finally:
        release.set()
        if not handler.done():
            handler.cancel()
            await asyncio.gather(handler, return_exceptions=True)
        await asyncio.wait_for(asyncio.gather(*api.server._chat_stream_tasks), 2)
    cli.assert_called_once()
    assert completions == [(item["id"], disconnect == "cancel_waiting")]
    gateway_notification.assert_not_awaited()
    terminal_notification.assert_not_called()


@pytest.mark.asyncio
async def test_retry_translation_and_trace_require_message_in_selected_session(api):
    item = await data(api, "POST", SESSIONS, body={"title": "Owner"})
    sibling = await data(api, "POST", SESSIONS, body={"title": "Sibling"})
    base = f"{SESSIONS}/{item['id']}"
    await data(api, "POST", base + "/conversations", body={"title": "Test turn"})
    profile, _, session = chat_targets.resolve_named_chat_target(api.server.manager, "main", 101, item["id"])
    store = ChatStore(session.working_dir)
    turn = store.begin_turn(
        bot_id=session.bot_id, bot_alias="main", user_id=session.user_id, agent_id=session.storage_scope,
        cli_type=profile.cli_type, working_dir=session.working_dir, session_epoch=session.session_epoch,
        user_text="Question", native_provider="codex", conversation_id=session.active_conversation_id,
    )
    reply = "Answer"
    store.complete_turn(turn, content=reply, completion_state="completed")
    digest = hashlib.sha256(reply.encode()).hexdigest()
    assert store.update_message_translation(
        turn.assistant_message_id, source_digest=digest,
        translation={"source_digest": digest, "status": "failed", "target_language": "en"},
    )
    message = "/history/" + turn.assistant_message_id
    for other in (BOT, f"{SESSIONS}/{sibling['id']}"):
        for method, suffix in (("GET", "/trace"), ("POST", "/translation/retry")):
            response = await dispatch(api, method, other + message + suffix)
            assert response.status == 404
    for method, suffix in (("GET", "/trace"), ("POST", "/translation/retry")):
        response = await dispatch(api, method, base + message + suffix, body={"sessionId": sibling["id"]})
        assert (response.status, json.loads(response.text)["error"]["code"]) == (400, "session_scope_mismatch")
    api.translator.submit_answer.assert_not_called()
    assert (await dispatch(api, "GET", base + message + "/trace")).status == 200
    retry = await data(api, "POST", base + message + "/translation/retry")
    assert retry["status"] == "pending"
    assert api.translator.submit_answer.call_args.kwargs["text"] == reply
