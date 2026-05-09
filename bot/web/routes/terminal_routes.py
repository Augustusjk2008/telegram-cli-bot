from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_post("/api/bots/{alias}/exec", server.post_exec)
    app.router.add_get("/api/bots/{alias}/terminal-actions/config", server.get_terminal_actions_config)
    app.router.add_put("/api/bots/{alias}/terminal-actions/config", server.put_terminal_actions_config)
    app.router.add_post(
        "/api/bots/{alias}/terminal-actions/{action_id}/run",
        server.post_run_terminal_action,
    )
    app.router.add_get("/api/terminal/session", server.get_terminal_session)
    app.router.add_post("/api/terminal/session/rebuild", server.post_terminal_rebuild)
    app.router.add_post("/api/terminal/session/close", server.post_terminal_close)
    app.router.add_get("/terminal/ws", server.terminal_ws)

