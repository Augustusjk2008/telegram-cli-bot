"""Relocate static site URLs inside a preview ticket, leaving authored text intact."""
from __future__ import annotations

import bisect
import json
import re
from html import escape, unescape
from html.parser import HTMLParser

_SPACE = " \t\r\n\f"
ORIGINAL_CSS_PARAM = "__orbit_original_css"
_ATTRIBUTE = re.compile(r"""(?<=\s)([^\s=/>]+)(\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
_DOT_SEGMENT = re.compile(r"/(?:\.|%2e){1,2}(?=/|[?#]|$)", re.IGNORECASE)
_QUOTED = r""""(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'"""
_CSS_TOKEN = re.compile(
    r"""/\*[\s\S]*?(?:\*/|$)|(?P<before>(?<![\w-])(?:url\(\s*|@import\s*(?=["'])))"""
    rf"(?P<url>{_QUOTED}|[^\s()'\";]+)|{_QUOTED}", re.IGNORECASE,
)
_CANDIDATE = re.compile(r"[^,\t\n\f\r ][^\t\n\f\r ]*")
_DESCRIPTOR = re.compile(r"(?:\([^)]*\)|[^,(])*(?:,|$)")


def site_url(value: str, site: str) -> str:
    url = value.strip(_SPACE).replace("\t", "").replace("\n", "").replace("\r", "")
    if not url.startswith("/") or url.startswith(("//", "/\\")) or "\\" in url:
        return value
    if not _DOT_SEGMENT.search(url):
        return site + url[1:]
    # Clamp ".." at the virtual site root. Preserve all other escapes verbatim,
    # including encoded quotes in CSS strings and the query/fragment delimiters.
    path = re.match(r"[^?#]*", url)[0]
    parts = path[1:].split("/")
    resolved = []
    for index, part in enumerate(parts):
        dots = part.lower().replace("%2e", ".")
        if dots in {".", ".."}:
            if dots == ".." and resolved:
                resolved.pop()
            if index == len(parts) - 1:
                resolved.append("")
        else:
            resolved.append(part)
    return site + "/".join(resolved) + url[len(path):]


def rewrite_css(source: str, site: str) -> str:
    def replace(match: re.Match) -> str:
        value = match["url"]
        if not value:
            return match[0]
        quote = value[0] if value[0] in "\"'" else ""
        url = value[1:-1] if quote else value
        mapped = site_url(url, site)
        return match[0] if mapped == url else match["before"] + quote + mapped + quote

    return _CSS_TOKEN.sub(replace, source) if "/" in source else source


def rewrite_srcset(value: str, site: str) -> str:
    # The URL token can contain commas (notably data URLs). Descriptors end
    # at the next comma outside parentheses.
    parts = []
    previous = position = 0
    while match := _CANDIDATE.search(value, position):
        token = match[0]
        url = token.rstrip(",")
        parts.extend((value[previous:match.start()], site_url(url, site)))
        previous = match.start() + len(url)
        position = match.end()
        if url == token:
            descriptor = _DESCRIPTOR.match(value, position)
            if descriptor:
                position = descriptor.end()
    return "".join(parts) + value[previous:]


def _script_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c")


def _import_map(source: str, site: str, defaults: dict[str, str]) -> str | None:
    try:
        mapping = json.loads(source)
    except (ValueError, RecursionError):
        return None
    if not isinstance(mapping, dict) or not isinstance(mapping.get("imports", {}), dict):
        return None

    def urls(entries):
        if not isinstance(entries, dict):
            return entries
        mapped = {}
        for key, value in entries.items():
            target = site_url(value, site) if isinstance(value, str) else value
            mapped[key] = target
            mapped[site_url(key, site)] = target
        return mapped

    mapping["imports"] = {**defaults, **urls(mapping.get("imports", {}))}
    if isinstance(mapping.get("scopes"), dict):
        mapping["scopes"] = {site_url(k, site): urls(v) for k, v in mapping["scopes"].items()}
    if isinstance(mapping.get("integrity"), dict):
        mapping["integrity"] = {site_url(k, site): v for k, v in mapping["integrity"].items()}
    return _script_json(mapping)


class PreviewDocument(HTMLParser):
    """Patch only URL-bearing attributes and styles; retain original HTML/XHTML markup."""

    CDATA_CONTENT_ELEMENTS = (*HTMLParser.CDATA_CONTENT_ELEMENTS, "textarea", "title")

    def __init__(self, source: str, site: str, prefix: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.site = site
        self.lines = [0, *(match.end() for match in re.finditer("\n", source))]
        self.edits: list[tuple[int, int, str]] = []
        self.head: int | None = None
        self.empty_head = False
        self.fallback = 0
        self.raw = ""
        # The identity mapping preserves ordinary document-relative module imports.
        self.imports = {"/": site, prefix: prefix}
        self.module_seen = False
        self.map_supplied = False

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def _attribute(self, match: re.Match, signed_style: bool) -> str:
        name = match[1].lower()
        if name not in {"src", "href", "xlink:href", "poster", "srcset", "imagesrcset", "style"}:
            return match[0]
        value = unescape(next(v for v in match.groups()[2:] if v is not None))
        if name == "style":
            mapped = rewrite_css(value, self.site)
        elif name in {"srcset", "imagesrcset"}:
            mapped = rewrite_srcset(value, self.site)
        else:
            mapped = site_url(value, self.site)
        if signed_style and name == "href":
            url = mapped.strip(_SPACE)
            if url and not re.match(r"^(?:[a-z][\w+.-]*:|//|#|\\)", url, re.IGNORECASE):
                path, fragment, anchor = url.partition("#")
                mapped = path + ("&" if "?" in path else "?") + ORIGINAL_CSS_PARAM + "=1" + fragment + anchor
        return match[0] if mapped == value else match[1] + match[2] + '"' + escape(mapped, quote=True) + '"'

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        start = self._offset()
        if tag == "head" and self.head is None:
            self.empty_head = raw.endswith("/>")
            self.head = start + len(raw) - (2 if self.empty_head else 0)
        elif tag == "html":
            self.fallback = start + len(raw)
        link = dict(attrs) if tag == "link" else {}
        rel = (link.get("rel") or "").lower().split()
        signed_style = bool(link.get("integrity")) and (
            "stylesheet" in rel or ("preload" in rel and (link.get("as") or "").lower() == "style")
        )
        if signed_style or "/" in raw or "&" in raw:
            for match in _ATTRIBUTE.finditer(raw):
                mapped = self._attribute(match, signed_style)
                if mapped != match[0]:
                    self.edits.append((start + match.start(), start + match.end(), mapped))
        self.raw = tag
        if tag == "script":
            kind = (dict(attrs).get("type") or "").strip().lower()
            if kind == "importmap":
                self.raw = kind
            elif kind == "module":
                self.module_seen = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.raw = ""

    def handle_endtag(self, tag):
        self.raw = ""

    def handle_data(self, data):
        if self.raw == "style":
            mapped = rewrite_css(data, self.site)
        elif self.raw == "importmap":
            # Merge into an author's map for browsers that accept only one.
            use_defaults = not self.module_seen and not self.map_supplied
            mapped = _import_map(data, self.site, self.imports if use_defaults else {})
            if mapped is None:
                return
            self.map_supplied |= use_defaults
        else:
            return
        if mapped != data:
            start = self._offset()
            self.edits.append((start, start + len(data), mapped))

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.fallback = self._offset() + len(decl) + 3

    def handle_pi(self, data):
        if data.startswith("xml "):
            self.fallback = self._offset() + len(data) + 3

    def render(self, bridge: str) -> bytes:
        self.feed(self.source)
        self.close()
        if not self.map_supplied:
            bridge = '<script type="importmap">' + _script_json({"imports": self.imports}) + "</script>" + bridge
        start = self.fallback if self.head is None else self.head
        insertion = (start, start, bridge)
        if self.empty_head:
            insertion = (start, start + 2, ">" + bridge + "</head>")
        bisect.insort_left(self.edits, insertion)
        pieces = []
        end = 0
        for start, next_end, replacement in self.edits:
            pieces.extend((self.source[end:start], replacement))
            end = next_end
        pieces.append(self.source[end:])
        return "".join(pieces).encode("utf-8")

