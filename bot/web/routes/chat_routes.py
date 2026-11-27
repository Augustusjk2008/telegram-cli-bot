from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    bot = "/api/bots/{alias}"
    sessions = bot + "/sessions"
    app.router.add_get("/api/bots", server.get_bots)
    app.router.add_get(sessions, server.get_chat_sessions_view)
    app.router.add_post(sessions, server.post_chat_session_view)
    app.router.add_get(sessions + "/{session_id}/cli-params", server.get_cli_params)
    app.router.add_patch(sessions + "/{session_id}/cli-params", server.patch_cli_params)

    for base in (bot, sessions + "/{session_id}"):
        app.router.add_get(base, server.get_bot_overview)
        app.router.add_post(base + "/chat", server.post_chat)
        app.router.add_post(base + "/chat/steer", server.post_chat_steer)
        app.router.add_post(base + "/chat/stream", server.post_chat_stream)
        app.router.add_get(base + "/history", server.get_history_view)
        app.router.add_get(base + "/history/delta", server.get_history_delta_view)
        app.router.add_get(base + "/history/{message_id}/trace", server.get_history_trace_view)
        app.router.add_get(base + "/history/{message_id}/trace/event", server.get_history_trace_event_view)
        app.router.add_get(base + "/favorites", server.get_favorites_view)
        app.router.add_post(base + "/favorites", server.post_favorite_view)
        app.router.add_delete(base + "/favorites/{favorite_id}", server.delete_favorite_view)
        app.router.add_get(base + "/conversations", server.get_conversations_view)
        app.router.add_post(base + "/conversations", server.post_conversation_view)
        app.router.add_delete(base + "/conversations", server.delete_conversations_view)
        app.router.add_post(base + "/conversations/{conversation_id}/select", server.post_conversation_select_view)
        app.router.add_post(base + "/conversations/{conversation_id}/archive", server.post_conversation_archive_view)
        app.router.add_delete(base + "/conversations/{conversation_id}", server.delete_conversation_view)
        app.router.add_post(base + "/plans/execute", server.post_plan_execute_view)
        app.router.add_post(base + "/kill", server.post_kill)

    app.router.add_get(bot + "/chat/voice", server.chat_voice_ws)
    app.router.add_post(bot + "/reset", server.post_reset)
