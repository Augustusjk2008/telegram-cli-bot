import json
import os
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlencode, urljoin

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext, WebApiError, get_session_for_alias
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_READ_FILE_CONTENT, CAP_WRITE_FILES
from bot.web.files_service import get_directory_listing
from bot.web.html_preview_service import HtmlPreviewStore, preview_resource
from bot.web.html_preview_urls import ORIGINAL_CSS_PARAM, PreviewDocument
from bot.web.routes import files_routes, html_preview_routes
from bot.web.server import WebApiServer, cors_middleware, error_middleware


@pytest.fixture
def preview_routes(tmp_path):
    root = tmp_path / "project"
    other = root / "other"
    other.mkdir(parents=True)
    (other / "index.html").write_text("other directory", encoding="utf-8")
    (root / "index.html").write_text("workspace file", encoding="utf-8")
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(root)), str(storage))
    server = object.__new__(WebApiServer)
    server.manager = manager
    server.html_preview_store = HtmlPreviewStore()
    auth = AuthContext(user_id=42, token_used=True, capabilities={CAP_READ_FILE_CONTENT})
    server._auth_context = lambda _request: auth
    server._can_operate_bot = lambda _auth, alias: alias == "main"
    session = get_session_for_alias(manager, "main", auth.user_id)
    session.browse_dir = str(other)
    app = web.Application()
    files_routes.register(app, server)
    html_preview_routes.register(app, server)

    async def request(endpoint, filename, *, anchored=True, expected_directory=None, content="", version=None):
        params = {"base": "workspace"} if anchored else {}
        if expected_directory is not None:
            params["expected_directory"] = str(expected_directory)
        post = endpoint in ("html-preview", "write")
        if not post:
            params["filename"] = filename
        url = "/api/bots/main/files/" + endpoint + "?" + urlencode(params)
        req = make_mocked_request("POST" if post else "GET", url, app=app)
        req._match_info = await app.router.resolve(req)
        if post:
            body = {"filename": filename} if endpoint == "html-preview" else {
                "path": filename, "content": content, "expected_mtime_ns": version,
            }
            req.json = AsyncMock(return_value=body)
        return await req.match_info.handler(req)

    return request, server, auth, root


@pytest.mark.asyncio
async def test_preview_reads_downloads_and_html_use_the_same_workspace_file(preview_routes):
    request, server, auth, root = preview_routes
    listing = get_directory_listing(server.manager, "main", auth.user_id)
    assert listing["working_dir"] == str(root / "other")
    assert listing["supports_workspace_file_base"] is True
    for anchored, expected in [(True, root), (False, root / "other")]:
        path = expected / "index.html"
        read = await request("read", path.name, anchored=anchored)
        assert json.loads(read.text)["data"]["content"].strip() == path.read_text(encoding="utf-8")
        download = await request("download", path.name, anchored=anchored)
        assert download._path == path
        html = await request("html-preview", path.name, anchored=anchored)
        ticket = server.html_preview_store.get(json.loads(html.text)["data"]["session_id"])
        assert Path(ticket.root) / ticket.entry_path == path


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["read", "download", "html-preview"])
async def test_workspace_relative_preview_disallows_absolute_and_escaping_paths_even_for_admin(preview_routes, endpoint):
    request, _, auth, root = preview_routes
    auth.capabilities.add(CAP_ADMIN_OPS)
    outside = root.parent / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    for filename in (str(outside), "../outside.html"):
        with pytest.raises(WebApiError) as error:
            await request(endpoint, filename)
        assert error.value.status in (400, 403)


@pytest.mark.asyncio
async def test_workspace_editor_keeps_original_file_and_revision_when_shared_directory_changes(preview_routes):
    request, server, auth, root = preview_routes
    auth.capabilities.add(CAP_WRITE_FILES)
    first = root / "first"
    first.mkdir()
    original = first / "config.json"
    other = root / "other" / "config.json"
    original.write_text("original", encoding="utf-8")
    other.write_text("other", encoding="utf-8")
    revision = original.stat().st_mtime_ns
    # Equal versions make the path binding, rather than mtime, responsible for choosing the file.
    os.utime(other, ns=(revision, revision))
    session = get_session_for_alias(server.manager, "main", auth.user_id)
    session.browse_dir = str(first)
    read = await request("read", "first/config.json")
    version = json.loads(read.text)["data"]["last_modified_ns"]
    session.browse_dir = str(other.parent)
    await request("write", "first/config.json", content="edited", version=version)
    assert original.read_text(encoding="utf-8") == "edited"
    assert other.read_text(encoding="utf-8") == "other"
    with pytest.raises(WebApiError) as conflict:
        await request("write", "first/config.json", content="stale", version=version)
    assert conflict.value.code == "file_version_conflict"


@pytest.mark.asyncio
async def test_workspace_edits_require_write_permission_and_reject_absolute_or_traversing_paths(preview_routes):
    request, _, auth, root = preview_routes
    original = root / "index.html"
    with pytest.raises(WebApiError) as denied:
        await request("write", original.name)
    assert denied.value.status == 403
    auth.capabilities.update({CAP_ADMIN_OPS, CAP_WRITE_FILES})
    for path in [str(original), "../project/index.html"]:
        with pytest.raises(WebApiError) as unsafe:
            await request("write", path)
        assert unsafe.value.code == "unsafe_write_path"
    assert original.read_text(encoding="utf-8") == "workspace file"


@pytest.mark.asyncio
async def test_workspace_edits_reject_a_link_to_another_file_inside_the_workspace(preview_routes):
    request, _, auth, root = preview_routes
    auth.capabilities.update({CAP_ADMIN_OPS, CAP_WRITE_FILES})
    original = root / "index.html"
    link = root / "alias.html"
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("filesystem does not allow symlinks")
    with pytest.raises(WebApiError) as unsafe:
        await request("write", link.name)
    assert unsafe.value.code == "unsafe_write_path"
    assert original.read_text(encoding="utf-8") == "workspace file"


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["read", "download", "html-preview", "write"])
async def test_expected_directory_cannot_redirect_operations_to_a_same_named_file(preview_routes, endpoint):
    request, server, auth, root = preview_routes
    auth.capabilities.add(CAP_WRITE_FILES)
    external = root.parent / "external"
    external.mkdir()
    original = external / "index.html"
    original.write_text("original", encoding="utf-8")
    session = get_session_for_alias(server.manager, "main", auth.user_id)
    session.browse_dir = str(external)
    if endpoint == "html-preview":
        # Existing interactive HTML permission still rejects an external entry for this account.
        with pytest.raises(WebApiError) as denied:
            await request(endpoint, original.name, anchored=False, expected_directory=external)
        assert denied.value.code == "preview_path_forbidden"
    else:
        await request(endpoint, original.name, anchored=False, expected_directory=external, content="original")
    session.browse_dir = str(root)
    with pytest.raises(WebApiError) as changed:
        await request(endpoint, original.name, anchored=False, expected_directory=external, content="wrong file")
    assert (changed.value.status, changed.value.code) == (409, "browse_directory_changed")
    assert (root / original.name).read_text(encoding="utf-8") == "workspace file"


@pytest.mark.asyncio
async def test_site_preview_uses_the_opened_page_and_serves_directory_indexes_under_public_mount(preview_routes, monkeypatch):
    _, server, _, root = preview_routes
    mount = "/gateway/node/preview"
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "/node/preview")
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "https://example.org" + mount)
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_ENABLED", False)
    site = root / "site one"
    (site / "docs").mkdir(parents=True)
    (site / "contact").mkdir()
    (site / "index.html").write_text("Home")
    (site / "docs/index.html").write_text(
        '<link href="/site.css"><a href="/contact">Contact</a>'
        '<link rel="stylesheet" integrity="sha384-example" href="theme.css?v=2#sheet">'
    )
    signed_css = b'\xef\xbb\xbf.logo {background:url(/logo.svg)}\r\n'
    (site / "docs/theme.css").write_bytes(signed_css)
    (site / "docs/site.css").write_text(".page { color: red }")
    (site / "site.css").write_text(".page { color: blue }")
    (site / "contact/index.htm").write_text('<img src="./map.svg">')
    (root / "shared.json").write_text("[]")
    routes = web.Application()
    html_preview_routes.register(routes, server)
    app = web.Application()
    app.add_subapp(mount, routes)

    async def dispatch(method, url, body=None):
        headers = {"Host": "example.org"} if body else {"Host": "example.org", "Origin": "null"}
        req = make_mocked_request(method, url, headers=headers, app=app)
        req._match_info = await app.router.resolve(req)
        if body:
            req.json = AsyncMock(return_value=body)
        return await cors_middleware(req, lambda request: error_middleware(request, req.match_info.handler))

    response = await dispatch("POST", mount + "/api/bots/main/files/html-preview?base=workspace",
                              {"filename": "site one/docs/index.html"})
    data = json.loads(response.text)["data"]
    prefix = mount + "/api/file-previews/" + data["session_id"] + "/"
    home = prefix + "site%20one/"
    assert data["entry_url"] == home + "docs/index.html"
    doc = await dispatch("GET", data["entry_url"])
    assert doc.status == 200
    assert f'href="{home}site.css"' in doc.text
    assert f'href="theme.css?v=2&amp;{ORIGINAL_CSS_PARAM}=1#sheet"' in doc.text
    original = await dispatch("GET", home + "docs/theme.css?v=2&" + ORIGINAL_CSS_PARAM + "=1")
    assert original.body == signed_css and original.headers["Content-Type"] == "text/css"
    assert (await dispatch("GET", home + "site.css")).text == ".page { color: blue }"
    # A relative link to an existing workspace resource retains its original meaning.
    assert (await dispatch("GET", urljoin(data["entry_url"], "../../shared.json"))).text == "[]"
    redirect = await dispatch("GET", home + "contact?via=docs%26chat")
    assert redirect.status == 302
    assert redirect.headers["Location"] == home + "contact/?via=docs%26chat"
    page = await dispatch("GET", redirect.headers["Location"])
    assert page.status == 200 and '<img src="./map.svg">' in page.text
    head = await dispatch("HEAD", redirect.headers["Location"])
    assert head.body == b"" and head.headers["Content-Length"] == str(len(page.body))
    assert page.headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in page.headers
    assert "allow-same-origin" not in page.headers["Content-Security-Policy"]
    assert (await dispatch("GET", home + "missing.js")).status == 404
    assert (await dispatch("GET", home + "missing/")).status == 404
    server.html_preview_store.invalidate(data["session_id"])
    assert (await dispatch("GET", home + "contact/")).status == 410


@pytest.mark.asyncio
async def test_site_discovery_stops_at_the_build_and_directory_reads_enforce_the_grant(preview_routes):
    request, server, _, root = preview_routes
    site = root / "dist"
    (site / "nested").mkdir(parents=True)
    (site / "index.html").write_text("Site home")
    (root / "only-at-workspace.css").write_text("old site")
    (site / "nested/index.html").write_text('<link href="/only-at-workspace.css">')
    response = await request("html-preview", "dist/nested/index.html")
    ticket = server.html_preview_store.get(json.loads(response.text)["data"]["session_id"])
    assert ticket.site_directory == "dist"
    for name in (".private", "credentials", "empty"):
        (site / name).mkdir()
        if name != "empty":
            (site / name / "index.html").write_text("private")
    for path, expected in [("dist/.private/", 403), ("dist/credentials/", 403), ("dist/empty/", 404),
                           ("dist/only-at-workspace.css", 404)]:
        with pytest.raises(WebApiError) as error:
            preview_resource(ticket, path, "/ticket/")
        assert error.value.status == expected

    outside = root.parent / "unrelated-site"
    outside.mkdir()
    (outside / "index.html").write_text("unrelated")
    try:
        (site / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("filesystem does not allow directory links")
    with pytest.raises(WebApiError) as error:
        preview_resource(ticket, "dist/linked/", "/ticket/")
    assert error.value.status in (400, 403)


def test_preview_relocates_url_tokens_without_changing_data_comments_or_displayed_source():
    source = """<!doctype html><html><head style="background:url(/icon.svg)"/><body>
<style>/* url(/comment) */ .a::after {content:"url(/label)"; background:url('/pic%27s.svg?v=1#x')}</style>
<img title='example src="/literal"' src='&#47;photo.svg?a=1&amp;b=2'
     srcset="data:image/png;base64,/9a 1x, /hi.png 2x">
<a href="/%2e%2e/where/../contact/?v=2#team">Go</a>
<a href="//other.example/about">External</a><a href="#local">Hash</a>
<textarea><img src="/literal"></textarea><script>const text = 'href="/literal"'</script>
</body></html>"""
    html = PreviewDocument(source, "/ticket/site/", "/ticket/").render("<script>bridge()</script>").decode()
    assert '<head style="background:url(/ticket/site/icon.svg)"><script' in html
    assert '</script></head><body>' in html
    assert '''/* url(/comment) */ .a::after {content:"url(/label)"; background:url('/ticket/site/pic%27s.svg?v=1#x')}''' in html
    assert '''title='example src="/literal"' src="/ticket/site/photo.svg?a=1&amp;b=2"''' in html
    assert 'srcset="data:image/png;base64,/9a 1x, /ticket/site/hi.png 2x"' in html
    assert 'href="/ticket/site/contact/?v=2#team"' in html
    assert 'href="//other.example/about"' in html and 'href="#local"' in html
    assert '''<textarea><img src="/literal"></textarea><script>const text = 'href="/literal"'</script>''' in html
