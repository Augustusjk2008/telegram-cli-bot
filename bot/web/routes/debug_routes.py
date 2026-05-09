from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/bots/{alias}/debug/profile", server.get_debug_profile)
    app.router.add_patch("/api/bots/{alias}/debug/profile", server.patch_debug_profile_overrides)
    app.router.add_patch("/api/bots/{alias}/debug/profile-overrides", server.patch_debug_profile_overrides)
    app.router.add_get("/api/bots/{alias}/debug/state", server.get_debug_state)
    app.router.add_post("/api/bots/{alias}/debug/launch", server.post_debug_launch)
    app.router.add_post("/api/bots/{alias}/debug/stop", server.post_debug_stop)
    app.router.add_post("/api/bots/{alias}/debug/command", server.post_debug_command)
    app.router.add_post("/api/bots/{alias}/debug/control", server.post_debug_command)
    app.router.add_post("/api/bots/{alias}/debug/breakpoints", server.post_debug_breakpoints)
    app.router.add_post("/api/bots/{alias}/debug/evaluate", server.post_debug_evaluate)
    app.router.add_get("/debug/ws", server.debug_ws)

