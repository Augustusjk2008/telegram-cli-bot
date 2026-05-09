from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/admin/bots/{alias}/assistant/proposals", server.admin_assistant_proposals)
    app.router.add_get(
        "/api/admin/bots/{alias}/assistant/upgrade-targets",
        server.admin_assistant_upgrade_targets,
    )
    app.router.add_get(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}",
        server.admin_assistant_proposal_detail,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/patch",
        server.admin_assistant_proposal_patch_generate,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/patch/stream",
        server.admin_assistant_proposal_patch_generate_stream,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/patch/approve",
        server.admin_assistant_proposal_patch_approve,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/approve",
        server.admin_assistant_proposal_approve,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/reject",
        server.admin_assistant_proposal_reject,
    )
    app.router.add_get(
        "/api/admin/bots/{alias}/assistant/proposals/{proposal_id}/apply-log",
        server.admin_assistant_upgrade_apply_log,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/upgrades/{proposal_id}/dry-run",
        server.admin_assistant_upgrade_dry_run,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/upgrades/{proposal_id}/apply",
        server.admin_assistant_upgrade_apply,
    )
    app.router.add_get("/api/admin/bots/{alias}/assistant/memory/search", server.admin_assistant_memory_search)
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/memory/{memory_id}/invalidate",
        server.admin_assistant_memory_invalidate,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/memory/bulk-invalidate",
        server.admin_assistant_memory_bulk_invalidate,
    )
    app.router.add_post("/api/admin/bots/{alias}/assistant/memory/reindex", server.admin_assistant_memory_reindex)
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/evals/memory/run",
        server.admin_assistant_memory_eval_run,
    )
    app.router.add_get(
        "/api/admin/bots/{alias}/assistant/evals/memory/reports",
        server.admin_assistant_memory_eval_reports,
    )
    app.router.add_get(
        "/api/admin/bots/{alias}/assistant/diagnostics/perf",
        server.admin_assistant_diagnostics,
    )
    app.router.add_get("/api/admin/bots/{alias}/assistant/cron/jobs", server.admin_assistant_cron_jobs)
    app.router.add_post("/api/admin/bots/{alias}/assistant/cron/jobs", server.admin_assistant_cron_job_create)
    app.router.add_patch(
        "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}",
        server.admin_assistant_cron_job_update,
    )
    app.router.add_delete(
        "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}",
        server.admin_assistant_cron_job_delete,
    )
    app.router.add_post(
        "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}/run",
        server.admin_assistant_cron_job_run,
    )
    app.router.add_get(
        "/api/admin/bots/{alias}/assistant/cron/jobs/{job_id}/runs",
        server.admin_assistant_cron_job_runs,
    )
    app.router.add_get("/api/admin/bots/{alias}/assistant/audit", server.admin_assistant_audit)

