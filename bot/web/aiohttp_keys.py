"""Typed aiohttp storage keys shared by the Web server and route modules."""

from __future__ import annotations

from aiohttp import web


SERVER_APP_KEY: web.AppKey[object] = web.AppKey("tcb.server", object)
AUTH_REQUEST_KEY: web.RequestKey[object] = web.RequestKey("tcb.auth", object)


__all__ = ["AUTH_REQUEST_KEY", "SERVER_APP_KEY"]
