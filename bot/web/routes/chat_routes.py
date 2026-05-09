from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/bots", server.get_bots)
    app.router.add_get("/api/bots/{alias}", server.get_bot_overview)
    app.router.add_post("/api/bots/{alias}/chat", server.post_chat)
    app.router.add_post("/api/bots/{alias}/chat/stream", server.post_chat_stream)
    app.router.add_get("/api/bots/{alias}/history", server.get_history_view)
    app.router.add_get("/api/bots/{alias}/history/delta", server.get_history_delta_view)
    app.router.add_get("/api/bots/{alias}/history/{message_id}/trace", server.get_history_trace_view)
    app.router.add_get("/api/bots/{alias}/conversations", server.get_conversations_view)
    app.router.add_post("/api/bots/{alias}/conversations", server.post_conversation_view)
    app.router.add_post(
        "/api/bots/{alias}/conversations/{conversation_id}/select",
        server.post_conversation_select_view,
    )
    app.router.add_post("/api/bots/{alias}/reset", server.post_reset)
    app.router.add_post("/api/bots/{alias}/kill", server.post_kill)

