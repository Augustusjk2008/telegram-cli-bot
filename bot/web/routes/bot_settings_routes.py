from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/bots/{alias}/cli-params", server.get_cli_params)
    app.router.add_patch("/api/bots/{alias}/cli-params", server.patch_cli_params)
    app.router.add_patch("/api/bots/{alias}/deepseek-selection", server.patch_deepseek_selection)
    app.router.add_patch("/api/bots/{alias}/cli-params/deepseek-selection", server.patch_deepseek_selection)
    app.router.add_post("/api/bots/{alias}/cli-params/reset", server.post_cli_params_reset)
