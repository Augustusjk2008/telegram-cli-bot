from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.models import AgentProfile, BotProfile
from bot.web.api_common import AuthContext, WebApiError, get_chat_session_for_alias
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_READ_FILE_CONTENT
from bot.web import html_preview_service as service
from bot.web.routes import html_preview_routes, remote_routes
from bot.web.server import WebApiServer, cors_middleware, error_middleware


@pytest.fixture
def preview(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "index.html").write_text('<!doctype html><html><head><script type="importmap">{"imports":{}}</script></head><body>你好</body></html>', encoding="utf-8")
    server = object.__new__(WebApiServer)
    profile = BotProfile(alias="main", working_dir=str(root), agents=[AgentProfile(id="child", name="Child")])
    server.manager = SimpleNamespace(main_profile=profile, managed_profiles={})
    server.html_preview_store = service.HtmlPreviewStore()
    auth = AuthContext(user_id=42, token_used=True, account_id="alice", capabilities={CAP_READ_FILE_CONTENT})
    monkeypatch.setattr(server, "_auth_context", lambda request: auth)
    monkeypatch.setattr(server, "_can_operate_bot", lambda context, alias: alias == "main")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    return SimpleNamespace(root=root, server=server, auth=auth, profile=profile)


async def dispatch(preview, method, path, *, body=None, origin=None):
    """Resolve real routes and middlewares without a socket or TestServer."""
    server = preview.server
    app = web.Application()
    server._register_app_routes(app)
    base = server._web_base_path()
    if base:
        child = web.Application()
        server._register_app_routes(child)
        app.add_subapp(base, child)
    app.freeze()
    headers = {"Host": "localhost:8765"}
    if origin is not None:
        headers["Origin"] = origin
    request = make_mocked_request(method, path, headers=headers, app=app)
    request._match_info = await app.router.resolve(request)
    request.json = AsyncMock(return_value=body or {})
    remote = remote_routes.middleware(server)

    async def handle(req):
        return await error_middleware(req, lambda inner: remote(inner, inner.match_info.handler))

    return await cors_middleware(request, handle)


async def create(preview, filename="index.html", *, agent="main", base=""):
    response = await dispatch(preview, "POST", f"{base}/api/bots/main/files/html-preview?agent_id={agent}", body={"filename": filename})
    assert response.status == 200, response.text
    return json.loads(response.text)["data"]


@pytest.mark.asyncio
async def test_create_requires_capability_bot_access_and_local_workspace_first(preview, monkeypatch):
    preview.auth.capabilities.clear()
    denied = await dispatch(preview, "POST", "/api/bots/main/files/html-preview", body={"filename": "index.html"})
    assert denied.status == 403
    preview.auth.capabilities.add(CAP_READ_FILE_CONTENT)
    monkeypatch.setattr(preview.server, "_can_operate_bot", lambda auth, alias: False)
    denied = await dispatch(preview, "POST", "/api/bots/main/files/html-preview", body={"filename": "index.html"})
    assert json.loads(denied.text)["error"]["code"] == "bot_forbidden"
    preview.profile.remote_workspace = {"root": "/remote"}
    monkeypatch.setattr(preview.server, "_with_capability", AsyncMock(side_effect=AssertionError("capability checked before remote")))
    monkeypatch.setattr(html_preview_routes, "_scope", Mock(side_effect=AssertionError("host accessed")))
    remote = await dispatch(preview, "POST", "/api/bots/main/files/html-preview", body={"filename": "index.html"})
    assert remote.status == 409
    assert json.loads(remote.text)["error"]["code"] == "remote_html_preview_unavailable"


@pytest.mark.asyncio
async def test_ticket_owner_agent_revoke_and_expiration(preview, monkeypatch):
    data = await create(preview, agent="child")
    record = preview.server.html_preview_store.get(data["session_id"])
    assert record.owner == ("alice", 42)
    assert record.agent_id == "child"
    assert len(record.session_id) >= 40
    assert data["expires_at"].endswith("Z")
    close_path = f'/api/bots/main/files/html-preview/{record.session_id}?agent_id=child'
    preview.auth.account_id = "bob"
    assert (await dispatch(preview, "DELETE", close_path)).status == 403
    preview.auth.account_id = "alice"
    preview.auth.user_id = 43
    assert (await dispatch(preview, "DELETE", close_path)).status == 403
    preview.auth.user_id = 42
    assert (await dispatch(preview, "DELETE", close_path.replace("child", "main"))).status == 403
    for _ in range(2):
        assert (await dispatch(preview, "DELETE", close_path)).status == 200
    assert (await dispatch(preview, "GET", data["entry_url"])).status == 410
    data = await create(preview)
    monkeypatch.setattr(service.time, "monotonic", lambda: record.deadline + 100)
    expired = await dispatch(preview, "HEAD", data["entry_url"], origin="null")
    assert expired.status == 410
    assert expired.headers["Access-Control-Allow-Origin"] == "*"


def test_capacity_rejection_and_lazy_expiry(tmp_path):
    store = service.HtmlPreviewStore(max_sessions=2, per_user=1)
    kwargs = dict(alias="main", agent_id="main", identity=(), root=str(tmp_path), entry_path="index.html")
    first = store.create(owner=("alice", 42), **kwargs)
    with pytest.raises(WebApiError, match="预览会话过多") as limit:
        store.create(owner=("alice", 42), **kwargs)
    assert limit.value.status == 429
    store.create(owner=("bob", 43), **kwargs)
    with pytest.raises(WebApiError) as limit:
        store.create(owner=("charlie", 44), **kwargs)
    assert limit.value.status == 429
    store._sessions[first.session_id] = replace(first, deadline=0)
    assert store.create(owner=("charlie", 44), **kwargs)


@pytest.mark.asyncio
async def test_workspace_root_is_fixed_across_browsing_and_entry_directory(preview, tmp_path):
    nested = preview.root / "pages"
    nested.mkdir()
    (nested / "entry.html").write_text('<script src="../app.js"></script>', encoding="utf-8")
    (preview.root / "app.js").write_text("workspace", encoding="utf-8")
    _, _, session = get_chat_session_for_alias(preview.server.manager, "main", 42)
    session.browse_dir = str(nested)
    data = await create(preview, "entry.html")
    assert data["entry_path"] == "pages/entry.html"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "app.js").write_text("wrong", encoding="utf-8")
    session.browse_dir = str(outside)
    response = await dispatch(preview, "GET", data["entry_url"].replace("pages/entry.html", "app.js"))
    assert response.body == b"workspace"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["workdir", "profile_workdir", "bot", "agent", "remote"])
async def test_identity_changes_revoke_ticket(preview, tmp_path, change):
    data = await create(preview, agent="child")
    _, _, session = get_chat_session_for_alias(preview.server.manager, "main", 42, "child")
    if change == "workdir":
        session.working_dir = str(tmp_path)
    elif change == "profile_workdir":
        preview.profile.working_dir = str(tmp_path)
    elif change == "bot":
        preview.server.manager.main_profile = replace(preview.profile)
    elif change == "agent":
        preview.profile.agents = [AgentProfile(id="child", name="Replacement")]
    else:
        preview.profile.remote_workspace = {"root": "/remote"}
    response = await dispatch(preview, "GET", data["entry_url"])
    assert response.status == 410
    assert data["session_id"] not in preview.server.html_preview_store._sessions
    if change == "remote":
        assert (await dispatch(preview, "DELETE", f'/api/bots/main/files/html-preview/{data["session_id"]}?agent_id=child')).status == 200


@pytest.mark.asyncio
async def test_admin_external_entry_and_non_admin_restriction(preview, tmp_path):
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    denied = await dispatch(preview, "POST", "/api/bots/main/files/html-preview", body={"filename": str(outside)})
    assert denied.status == 400
    preview.auth.capabilities.add(CAP_ADMIN_OPS)
    data = await create(preview, str(outside))
    assert preview.server.html_preview_store.get(data["session_id"]).root == str(tmp_path)
    assert (await dispatch(preview, "GET", data["entry_url"])).status == 200
    preview.auth.capabilities.remove(CAP_ADMIN_OPS)
    _, _, session = get_chat_session_for_alias(preview.server.manager, "main", 42)
    session.browse_dir = str(tmp_path)
    denied = await dispatch(preview, "POST", "/api/bots/main/files/html-preview", body={"filename": "outside.html"})
    assert denied.status == 403


@pytest.mark.asyncio
async def test_replacing_external_preview_root_revokes_ticket(preview, tmp_path):
    root = tmp_path / "external"
    root.mkdir()
    (root / "index.html").write_text("original", encoding="utf-8")
    preview.auth.capabilities.add(CAP_ADMIN_OPS)
    data = await create(preview, str(root / "index.html"))
    root.rename(tmp_path / "previous")
    root.mkdir()
    (root / "index.html").write_text("replacement", encoding="utf-8")
    response = await dispatch(preview, "GET", data["entry_url"])
    assert response.status == 410
    assert data["session_id"] not in preview.server.html_preview_store._sessions


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "../outside.html", "%2e%2e/outside.html", "%252e%252e/outside.html", "C:/outside.html",
    "index.html:secret", "a%5c..%5cindex.html", "//server/share/index.html",
    "COM¹.html",
    "credentials.json", "managed_bots.json", "vite.config.js", "index.html.", "NUL.html",
    "source.py", "folder/", "missing.js",
])
async def test_unsafe_missing_and_disallowed_resources_are_not_spa(preview, path):
    data = await create(preview)
    url = data["entry_url"].removesuffix("index.html") + path
    response = await dispatch(preview, "GET", url, origin="null")
    assert response.status in {400, 403, 404, 415}
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_symlink_escape(preview, tmp_path):
    outside = tmp_path / "outside.html"
    outside.write_text("private", encoding="utf-8")
    link = preview.root / "link.html"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(WebApiError):
        service.read_resource(str(preview.root), "link.html")


def test_symlink_swap_during_open_cannot_escape(preview, tmp_path, monkeypatch):
    outside = tmp_path / "outside.html"
    outside.write_text("private", encoding="utf-8")
    target = preview.root / "swapped.html"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    target.unlink()
    target.write_text("public", encoding="utf-8")
    real_open = service.os.open

    def swap_and_open(path, flags):
        if Path(path) == target:
            target.unlink()
            target.symlink_to(outside)
        return real_open(path, flags)

    monkeypatch.setattr(service.os, "open", swap_and_open)
    with pytest.raises(WebApiError):
        service.read_resource(str(preview.root), "swapped.html")


@pytest.mark.asyncio
async def test_sizes_include_actual_read_and_head(preview, monkeypatch):
    (preview.root / "large.html").write_bytes(b"x" * (service.HTML_LIMIT + 1))
    response = await dispatch(preview, "POST", "/api/bots/main/files/html-preview", body={"filename": "large.html"})
    assert response.status == 413
    data = await create(preview)
    with (preview.root / "large.js").open("wb") as stream:
        stream.truncate(service.RESOURCE_LIMIT + 1)
    url = data["entry_url"].replace("index.html", "large.js")
    for method in ("GET", "HEAD"):
        assert (await dispatch(preview, method, url)).status == 413
    real_stat = service.os.fstat
    monkeypatch.setattr(service.os, "fstat", lambda fd: SimpleNamespace(st_mode=real_stat(fd).st_mode, st_size=0))
    with pytest.raises(WebApiError) as grown:
        service.read_resource(str(preview.root), "large.js")
    assert grown.value.status == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["", "/node/test-node"])
async def test_mime_bridge_csp_cors_head_and_prefix(preview, monkeypatch, base):
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", base)
    monkeypatch.setattr("bot.web.server.WEB_ALLOWED_ORIGINS", ["*"])
    data = await create(preview, base=base)
    assert data["entry_url"].startswith(base + "/api/file-previews/")
    get = await dispatch(preview, "GET", data["entry_url"], origin="null")
    head = await dispatch(preview, "HEAD", data["entry_url"], origin="null")
    assert get.status == head.status == 200
    assert head.body == b"" and head.content_length == len(get.body)
    assert get.body.startswith(b"<!doctype html><html><head><script>")
    assert '<script type="importmap">{"imports":{}}</script>' in get.text
    assert "event.source === parent" in get.text and "data.sessionId === sessionId" in get.text
    assert "你好" in get.text
    csp = get.headers["Content-Security-Policy"]
    assert f'connect-src localhost:8765{base}/api/file-previews/{data["session_id"]}/' in csp
    assert "sandbox allow-scripts allow-forms allow-downloads" in csp
    assert "allow-same-origin" not in csp and "'self'" not in csp
    for directive in ("form-action", "object-src", "frame-src", "worker-src", "base-uri"):
        assert f"{directive} 'none'" in csp
    assert get.headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in get.headers
    assert get.headers["Referrer-Policy"] == "no-referrer"
    assert get.headers["X-Content-Type-Options"] == "nosniff"
    assert get.headers["Cache-Control"] == "no-store"
    for suffix, mime in {"css": "text/css", "mjs": "text/javascript", "json": "application/json", "svg": "image/svg+xml", "woff2": "font/woff2", "png": "image/png"}.items():
        (preview.root / f"asset.{suffix}").write_bytes(b"{}")
        response = await dispatch(preview, "GET", data["entry_url"].replace("index.html", f"asset.{suffix}"), origin="null")
        assert response.status == 200 and response.content_type == mime
        if suffix == "svg":
            assert response.headers["Content-Security-Policy"] == csp
    options = await dispatch(preview, "OPTIONS", data["entry_url"], origin="null")
    assert options.status == 204 and options.headers["Access-Control-Allow-Origin"] == "*"
    unsupported = await dispatch(preview, "POST", data["entry_url"], origin="null")
    assert unsupported.status == 405 and unsupported.headers["Access-Control-Allow-Origin"] == "*"
    missing = await dispatch(preview, "GET", base + "/api/file-previews/unknown/missing.js", origin="null")
    assert missing.status == 410 and missing.headers["Access-Control-Allow-Origin"] == "*"
    for method in ("POST", "GET", "OPTIONS"):
        denied = await dispatch(preview, method, base + "/api/bots/main/files/html-preview", origin="null")
        assert denied.status == 403
        assert "Access-Control-Allow-Credentials" not in denied.headers
        assert "Access-Control-Allow-Origin" not in denied.headers
    allowed = await dispatch(preview, "POST", base + "/api/bots/main/files/html-preview", body={"filename": "index.html"}, origin="http://localhost:8765")
    assert allowed.status == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:8765"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"


@pytest.mark.asyncio
async def test_utf16_xhtml_keeps_xml_valid_and_refresh_reads_changes(preview):
    import xml.etree.ElementTree as ET

    file = preview.root / "page.xhtml"
    file.write_text('<?xml version="1.0" encoding="utf-16"?><html xmlns="http://www.w3.org/1999/xhtml"><head/><body>你好</body></html>', encoding="utf-16")
    data = await create(preview, "page.xhtml")
    response = await dispatch(preview, "GET", data["entry_url"])
    assert response.content_type == "application/xhtml+xml"
    assert "你好" in response.text
    ET.fromstring(response.body)
    file.write_text('<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body>Changed</body></html>', encoding="utf-8")
    assert "Changed" in (await dispatch(preview, "GET", data["entry_url"])).text


@pytest.mark.asyncio
async def test_unicode_path_and_revoke_during_read(preview, monkeypatch):
    name = "测试 page.html"
    (preview.root / name).write_text("你好", encoding="gb18030")
    data = await create(preview, name)
    response = await dispatch(preview, "GET", data["entry_url"] + "?view=1")
    assert response.status == 200 and "你好" in response.text
    real_read = html_preview_routes.read_resource

    def revoke_during_read(*args):
        result = real_read(*args)
        preview.server.html_preview_store.invalidate(data["session_id"])
        return result

    monkeypatch.setattr(html_preview_routes, "read_resource", revoke_during_read)
    response = await dispatch(preview, "GET", data["entry_url"])
    assert response.status == 410
