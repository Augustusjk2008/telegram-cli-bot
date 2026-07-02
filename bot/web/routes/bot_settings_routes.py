from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/bots/{alias}/cli-params", server.get_cli_params)
    app.router.add_patch("/api/bots/{alias}/cli-params", server.patch_cli_params)
    app.router.add_post("/api/bots/{alias}/cli-params/reset", server.post_cli_params_reset)
    app.router.add_get("/api/bots/{alias}/native-agent/models", server.get_native_agent_models)
    app.router.add_patch("/api/bots/{alias}/native-agent/model", server.patch_native_agent_model)
