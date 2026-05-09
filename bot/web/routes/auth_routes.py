from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/health", server.health)
    app.router.add_get("/api/auth/me", server.auth_me)
    app.router.add_post("/api/auth/login", server.auth_login)
    app.router.add_post("/api/auth/register", server.auth_register)
    app.router.add_post("/api/auth/guest", server.auth_guest)
    app.router.add_post("/api/auth/logout", server.auth_logout)
    app.router.add_get("/api/admin/register-codes", server.admin_register_codes)
    app.router.add_post("/api/admin/register-codes", server.admin_register_code_create)
    app.router.add_patch("/api/admin/register-codes/{code_id}", server.admin_register_code_patch)
    app.router.add_delete("/api/admin/register-codes/{code_id}", server.admin_register_code_delete)

