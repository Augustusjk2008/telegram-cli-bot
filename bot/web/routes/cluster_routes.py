from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/internal/cluster/mcp/ping", server.cluster_mcp_ping)
    app.router.add_post("/api/internal/cluster/mcp/tools/{tool_name}", server.cluster_mcp_tool)
    app.router.add_get("/api/bots/{alias}/agents", server.get_agents_view)
    app.router.add_get("/api/bots/{alias}/cluster/status", server.get_cluster_status_view)
    app.router.add_get("/api/bots/{alias}/cluster/runs/{run_id}/tasks", server.get_cluster_run_tasks_view)
    app.router.add_post("/api/admin/bots/{alias}/agents", server.post_agent_view)
    app.router.add_patch("/api/admin/bots/{alias}/agents/{agent_id}", server.patch_agent_view)
    app.router.add_delete("/api/admin/bots/{alias}/agents/{agent_id}", server.delete_agent_view)
    app.router.add_post("/api/admin/bots/{alias}/cluster/setup/prepare", server.post_cluster_setup_prepare)
    app.router.add_post("/api/admin/bots/{alias}/cluster/config", server.post_cluster_config)
    app.router.add_get("/api/admin/bots/{alias}/cluster/templates", server.get_cluster_templates_view)
    app.router.add_get("/api/admin/bots/{alias}/cluster/schema", server.get_bot_cluster_schema_view)
    app.router.add_get("/api/admin/cluster/schema", server.get_cluster_schema_view)
    app.router.add_post(
        "/api/admin/bots/{alias}/cluster/templates/preview",
        server.post_cluster_template_preview,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/cluster/templates/apply",
        server.post_cluster_template_apply,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/cluster/config-bundle/preview",
        server.post_cluster_bundle_preview,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/cluster/config-bundle/apply",
        server.post_cluster_bundle_apply,
    )
