from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/plugins", server.get_plugins)
    app.router.add_get("/api/plugins/installable", server.get_installable_plugins)
    app.router.add_post("/api/plugins/install", server.post_install_plugin)
    app.router.add_patch("/api/plugins/{plugin_id}", server.patch_plugin)
    app.router.add_delete("/api/plugins/{plugin_id}", server.delete_plugin)
    app.router.add_post("/api/bots/{alias}/plugins/resolve-file-target", server.resolve_file_plugin_target)
    app.router.add_post(
        "/api/bots/{alias}/plugins/{plugin_id}/views/{view_id}/render",
        server.post_render_plugin_view,
    )
    app.router.add_post(
        "/api/bots/{alias}/plugins/{plugin_id}/views/{view_id}/open",
        server.post_open_plugin_view,
    )
    app.router.add_post(
        "/api/bots/{alias}/plugins/{plugin_id}/sessions/{session_id}/window",
        server.post_plugin_view_window,
    )
    app.router.add_delete(
        "/api/bots/{alias}/plugins/{plugin_id}/sessions/{session_id}",
        server.delete_plugin_view_session,
    )
    app.router.add_post(
        "/api/bots/{alias}/plugins/{plugin_id}/actions/invoke",
        server.post_invoke_plugin_action,
    )
    app.router.add_get(
        "/api/bots/{alias}/plugins/artifacts/{artifact_id}",
        server.download_plugin_artifact,
    )
