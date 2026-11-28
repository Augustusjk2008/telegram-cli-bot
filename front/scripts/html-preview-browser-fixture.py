"""Produce real preview responses for Playwright without starting a server."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from bot.web.html_preview_service import (  # noqa: E402
    HtmlPreviewStore,
    entry_url,
    find_site_directory,
    preview_resource,
    resource_prefix,
    security_headers,
)
from bot.web.api_common import WebApiError
from bot.web.html_preview_urls import ORIGINAL_CSS_PARAM


def main() -> None:
    origin, base_path = sys.argv[1:3]
    with tempfile.TemporaryDirectory(prefix="orbit-html-preview-browser-") as temporary:
        root = Path(temporary)
        site = root / "demo site" / "dist"
        entry = "demo site/dist/pages/start.html"
        signed_css = '#signed {padding-left:13px;background-image:url("/assets/pixel.svg")}'
        digest = base64.b64encode(hashlib.sha384(signed_css.encode()).digest()).decode()
        files = {
            "index.html": "<!doctype html><title>Site home</title>",
            "pages/start.html": """<!doctype html><html><head><meta charset="utf-8">
<title>Interactive preview</title><link rel="stylesheet" href="/assets/style.css?v=2">
<link rel="stylesheet" crossorigin="anonymous" integrity="sha384-SIGNED_DIGEST" href="/assets/signed.css">
<script type="importmap">{"imports":{"fixture-label":"/assets/label.mjs"}}</script>
<script type="module" src="/assets/app.mjs"></script></head><body>
<h1>Interactive HTML</h1><button id="count">Count 0</button>
<form id="demo"><button type="submit">Submit locally</button></form><output id="form-result"></output>
<p><a href="#route">Hash route</a> <a href="./details.html">Details</a> <a href="/contact/?via=preview#address">Contact</a></p>
<img src="../assets/pixel.svg" srcset="/assets/pixel.svg 1x" alt="Preview image"><div id="logos"></div>
<p id="module"></p><p id="json"></p><p id="font"></p><div id="signed">Signed stylesheet</div>
<p id="parent"></p><p id="storage"></p><p id="api"></p></body></html>""".replace("SIGNED_DIGEST", digest),
            "assets/style.css": """@import url("/assets/colors.css");
@font-face {font-family: PreviewFont; src: url('/assets/font.woff2') format('woff2')}
body {font-family: PreviewFont, sans-serif; margin: 12px; overflow-wrap: anywhere}
h1 {font-size: 24px} img {width: 30px; height: 30px}""",
            "assets/colors.css": "h1 {color: #123456}",
            "assets/signed.css": signed_css,
            "assets/app.mjs": """import { label } from '/assets/helper.mjs';
const show = (id, text) => document.getElementById(id).textContent = text;
show('module', label);
const filename = 'data.json';
show('json', (await (await fetch('/' + filename)).json()).message);
document.querySelector('#logos').innerHTML = '<img src="/assets/pixel.svg" alt="Bundle logo">';
await document.fonts.load('16px PreviewFont'); show('font', 'font ready');
let count = 0; document.getElementById('count').onclick = () => show('count', `Count ${++count}`);
document.getElementById('demo').onsubmit = event => { event.preventDefault(); show('form-result', 'form handled'); };
try { parent.document.body; show('parent', 'accessible'); } catch { show('parent', 'blocked'); }
try { localStorage.getItem('console-token'); show('storage', 'accessible'); } catch { show('storage', 'blocked'); }
try { const r = await fetch(MANAGEMENT_URL, {credentials: 'include'}); show('api', r.ok ? 'accessible' : 'blocked'); } catch { show('api', 'blocked'); }
""".replace("MANAGEMENT_URL", json.dumps(base_path + "/api/auth/me")),
            "assets/helper.mjs": "export {label} from 'fixture-label';",
            "assets/label.mjs": "export {label} from './relative.mjs';",
            "assets/relative.mjs": "export const label = 'module ready';",
            "data.json": '{"message":"JSON ready"}',
            "assets/pixel.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#123456"/></svg>',
            "pages/details.html": '<!doctype html><html><head><meta charset="utf-8"></head><body><h1>Details version 1</h1></body></html>',
            "contact/index.html": '<!doctype html><base href="/contact/maps/"><h1 id="address">Contact</h1><img src="./map.svg" alt="Map">',
            "contact/maps/map.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>',
        }
        for name, content in files.items():
            target = site / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-16" if name == "assets/style.css" else "utf-8")
        font = REPO / "front/node_modules/katex/dist/fonts/KaTeX_Main-Regular.woff2"
        (site / "assets/font.woff2").write_bytes(font.read_bytes())
        session = HtmlPreviewStore().create(
            owner=("browser-test", 1), alias="main", agent_id="main", identity=("browser-test",),
            root=str(root), entry_path=entry, site_directory=find_site_directory(str(root), entry),
        )
        prefix = resource_prefix(base_path, session.session_id)

        def response(name: str, *, original_css: bool = False) -> dict:
            try:
                data, mime, redirect = preview_resource(session, name, prefix, original_css=original_css)
            except WebApiError as error:
                headers = security_headers(urlsplit(origin).netloc, prefix)
                headers.update({"Content-Type": "application/json", "Content-Security-Policy": "default-src 'none'; sandbox"})
                data = json.dumps({"ok": False, "error": {"code": error.code, "message": error.message}}).encode("utf-8")
                return {"status": error.status, "headers": headers, "body": base64.b64encode(data).decode("ascii")}
            headers = security_headers(urlsplit(origin).netloc, prefix)
            assert not redirect
            headers["Content-Type"] = mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/json" else "")
            return {"status": 200, "headers": headers, "body": base64.b64encode(data).decode("ascii")}

        paths = [f"demo site/dist/{name}" for name in [*files, "assets/font.woff2", "contact/"]]
        resources = {path: response(path) for path in paths}
        signed_path = "demo site/dist/assets/signed.css"
        resources[signed_path + "?" + ORIGINAL_CSS_PARAM + "=1"] = response(signed_path, original_css=True)
        (site / "pages/details.html").write_text(files["pages/details.html"].replace("version 1", "version 2"), encoding="utf-8")
        print(json.dumps({
            "session": {"session_id": session.session_id, "entry_url": entry_url(session, base_path), "entry_path": session.entry_path, "expires_at": session.expires_at},
            "resources": resources, "refreshed": response("demo site/dist/pages/details.html"),
        }))


if __name__ == "__main__":
    main()
