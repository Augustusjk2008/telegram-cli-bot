"""Produce real preview responses for Playwright without starting a server."""
from __future__ import annotations

import base64
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
    inject_bridge,
    read_resource,
    resource_prefix,
    security_headers,
)
from bot.web.api_common import WebApiError


def main() -> None:
    origin, base_path = sys.argv[1:3]
    with tempfile.TemporaryDirectory(prefix="orbit-html-preview-browser-") as temporary:
        root = Path(temporary)
        files = {
            "index.html": """<!doctype html><html><head><meta charset="utf-8">
<title>Interactive preview</title><link rel="stylesheet" href="./assets/style.css">
<script type="module" src="./assets/app.mjs"></script></head><body>
<h1>Interactive HTML</h1><button id="count">Count 0</button>
<form id="demo"><button type="submit">Submit locally</button></form><output id="form-result"></output>
<p><a href="#route">Hash route</a> <a href="./pages/details.html">Details</a> <a href="./missing.html">Missing page</a></p>
<img src="./assets/pixel.svg" alt="Preview image"><p id="module"></p><p id="json"></p><p id="font"></p>
<p id="parent"></p><p id="storage"></p><p id="api"></p></body></html>""",
            "assets/style.css": """@font-face {font-family: PreviewFont; src: url('./font.woff2') format('woff2')}
body {font-family: PreviewFont, sans-serif; margin: 12px; overflow-wrap: anywhere}
h1 {color: #123456; font-size: 24px} img {width: 30px; height: 30px}""",
            "assets/app.mjs": """import { label } from './helper.mjs';
const show = (id, text) => document.getElementById(id).textContent = text;
show('module', label);
show('json', (await (await fetch('./data.json')).json()).message);
await document.fonts.load('16px PreviewFont'); show('font', 'font ready');
let count = 0; document.getElementById('count').onclick = () => show('count', `Count ${++count}`);
document.getElementById('demo').onsubmit = event => { event.preventDefault(); show('form-result', 'form handled'); };
try { parent.document.body; show('parent', 'accessible'); } catch { show('parent', 'blocked'); }
try { localStorage.getItem('console-token'); show('storage', 'accessible'); } catch { show('storage', 'blocked'); }
try { await fetch(MANAGEMENT_URL, {credentials: 'include'}); show('api', 'accessible'); } catch { show('api', 'blocked'); }
""".replace("MANAGEMENT_URL", json.dumps(base_path + "/api/auth/me")),
            "assets/helper.mjs": "export const label = 'module ready';",
            "data.json": '{"message":"JSON ready"}',
            "assets/pixel.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#123456"/></svg>',
            "pages/details.html": '<!doctype html><html><head><meta charset="utf-8"></head><body><h1>Details version 1</h1></body></html>',
        }
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-16" if name == "assets/style.css" else "utf-8")
        font = REPO / "front/node_modules/katex/dist/fonts/KaTeX_Main-Regular.woff2"
        (root / "assets/font.woff2").write_bytes(font.read_bytes())
        session = HtmlPreviewStore().create(
            owner=("browser-test", 1), alias="main", agent_id="main", identity=("browser-test",),
            root=str(root), entry_path="index.html",
        )
        prefix = resource_prefix(base_path, session.session_id)

        def response(name: str) -> dict:
            try:
                data, mime = read_resource(str(root), name)
            except WebApiError as error:
                headers = security_headers(urlsplit(origin).netloc, prefix)
                headers.update({"Content-Type": "application/json", "Content-Security-Policy": "default-src 'none'; sandbox"})
                data = json.dumps({"ok": False, "error": {"code": error.code, "message": error.message}}).encode("utf-8")
                return {"status": error.status, "headers": headers, "body": base64.b64encode(data).decode("ascii")}
            if mime == "text/html":
                data = inject_bridge(data, session, prefix)
            headers = security_headers(urlsplit(origin).netloc, prefix)
            headers["Content-Type"] = mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/json" else "")
            return {"status": 200, "headers": headers, "body": base64.b64encode(data).decode("ascii")}

        resources = {name: response(name) for name in [*files, "assets/font.woff2", "missing.html"]}
        (root / "pages/details.html").write_text(files["pages/details.html"].replace("version 1", "version 2"), encoding="utf-8")
        print(json.dumps({
            "session": {"session_id": session.session_id, "entry_url": entry_url(session, base_path), "entry_path": session.entry_path, "expires_at": session.expires_at},
            "resources": resources, "refreshed": response("pages/details.html"),
        }))


if __name__ == "__main__":
    main()
