"""Short-lived, read-only capabilities for local web documents."""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bot.web.api_common import WebApiError
from bot.web.files_service import resolve_safe_path
from bot.web.html_preview_urls import ORIGINAL_CSS_PARAM, PreviewDocument, rewrite_css
from bot.web.text_encoding import UnsupportedTextEncoding, decode_text_bytes


HTML_LIMIT = 1024 * 1024
RESOURCE_LIMIT = 16 * 1024 * 1024
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
INDEX_FILES = ("index.html", "index.htm", "index.xhtml")
MIME_TYPES = {
    ".html": "text/html", ".htm": "text/html", ".xhtml": "application/xhtml+xml",
    ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".avif": "image/avif", ".ico": "image/x-icon", ".bmp": "image/bmp",
    ".svg": "image/svg+xml", ".woff": "font/woff", ".woff2": "font/woff2",
    ".ttf": "font/ttf", ".otf": "font/otf",
}
_SENSITIVE = re.compile(
    r"^(?:managed_bots|package(?:-lock)?|tsconfig(?:\..*)?|jsconfig|"
    r"credentials?|secrets?|config|settings|appsettings)(?:[.-].*)?$|\.config\.", re.I,
)
_DEVICE = re.compile(r"^(?:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(?:\.|$)", re.I)


def validate_relative_path(value: str, *, allow_hidden: bool = False) -> str:
    # aiohttp already decodes route parameters once. Reject residual escapes,
    # Windows aliases/ADS and ambiguous separators instead of decoding again.
    if not value or any(c in value for c in "\\:%?#") or any(ord(c) < 32 for c in value):
        raise WebApiError(400, "unsafe_preview_path", "预览资源路径不安全")
    for part in value.split("/"):
        if (not part or (not allow_hidden and part.startswith(".")) or part.endswith((".", " "))
                or _DEVICE.match(part) or _SENSITIVE.search(part)):
            raise WebApiError(403, "preview_path_forbidden", "预览不允许访问此路径")
    return value


def resource_path(root: str, relative: str) -> str:
    if root.startswith(("\\\\", "//")):
        raise WebApiError(400, "unsafe_preview_path", "不允许 UNC 路径")
    if os.path.normcase(os.path.realpath(root)) != os.path.normcase(os.path.abspath(root)):
        raise WebApiError(403, "preview_path_forbidden", "预览资源根目录已改变")
    validate_relative_path(relative)
    target = resolve_safe_path(root, relative)
    validate_relative_path(Path(os.path.relpath(target, root)).as_posix())
    if Path(target).suffix.lower() not in MIME_TYPES:
        raise WebApiError(415, "preview_type_forbidden", "预览不支持此文件类型")
    return target


def _opened_path(handle, target: str) -> str:
    """Validate the opened object, including a symlink swap during open()."""
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        final_path = kernel.GetFinalPathNameByHandleW
        final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        final_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = final_path(msvcrt.get_osfhandle(handle.fileno()), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise OSError("Cannot resolve preview file handle")
        return os.path.normpath(buffer.value.removeprefix("\\\\?\\"))
    fd_path = f"/proc/self/fd/{handle.fileno()}"
    return os.path.realpath(fd_path if os.path.exists(fd_path) else target)


def read_resource(root: str, relative: str, *, original_css: bool = False) -> tuple[bytes, str]:
    target = resource_path(root, relative)
    suffix = Path(target).suffix.lower()
    limit = HTML_LIMIT if suffix in HTML_EXTENSIONS else RESOURCE_LIMIT
    try:
        # O_NONBLOCK prevents a local FIFO masquerading as a web resource from
        # blocking a worker; only regular files are accepted after opening.
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            opened = _opened_path(handle, target)
            if resource_path(root, Path(os.path.relpath(opened, root)).as_posix()) != target:
                raise WebApiError(403, "preview_path_forbidden", "预览资源路径已改变")
            if not stat.S_ISREG(info.st_mode):
                raise WebApiError(404, "preview_file_not_found", "预览资源不存在")
            if info.st_size > limit:
                raise WebApiError(413, "preview_file_too_large", "预览资源超过大小限制")
            data = handle.read(limit + 1)
            if len(data) > limit:
                raise WebApiError(413, "preview_file_too_large", "预览资源超过大小限制")
    except (OSError, ValueError) as exc:
        raise WebApiError(404, "preview_file_not_found", "预览资源不存在或不可读取") from exc
    mime = MIME_TYPES[suffix]
    if suffix in {".js", ".mjs", ".json"} or (suffix == ".css" and not original_css):
        try:
            data = decode_text_bytes(data).text.encode("utf-8")
        except UnsupportedTextEncoding as exc:
            raise WebApiError(415, "preview_encoding", "资源文本编码不受支持") from exc
    return data, mime


def _requested_file(root: str, path: str) -> str:
    directory = path.removesuffix("/")
    if path:
        validate_relative_path(directory)
        if not os.path.isdir(resolve_safe_path(root, directory)):
            if path.endswith("/") or not Path(path).suffix:
                raise WebApiError(404, "preview_file_not_found", "预览资源不存在")
            return path
    for index in INDEX_FILES:
        relative = f"{directory}/{index}" if directory else index
        if os.path.isfile(resource_path(root, relative)):
            return relative
    raise WebApiError(404, "preview_file_not_found", "预览目录没有首页")


class _RootReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if (len(self.paths) >= 8 or name not in {"src", "href", "poster"} or not value
                    or not value.startswith("/") or value.startswith(("//", "/\\"))):
                continue
            path = unquote(urlsplit(value).path[1:])
            if path and path not in self.paths:
                self.paths.append(path)


def find_site_directory(root: str, entry: str) -> str:
    data, _ = read_resource(root, entry)
    # Plain HTML exports often have an index at both the site root and each
    # page. Use the opening page's own URLs to disambiguate those ancestors.
    hints = _RootReferences()
    try:
        hints.feed(decode_text_bytes(data).text[:65536])
    except UnsupportedTextEncoding:
        pass  # The document renderer reports unsupported encodings.
    boundary = Path(root)
    directory = (boundary / entry).parent
    best = directory
    best_rank = (-1, False, False)
    while True:
        indexed = any((directory / name).is_file() for name in INDEX_FILES)
        output = indexed and directory.name.lower() in {"dist", "build", "out", "public", "_site"}
        matches = 0
        for path in hints.paths:
            try:
                relative = _requested_file(str(directory), path)
                matches += os.path.isfile(resource_path(str(directory), relative))
            except WebApiError:
                continue
        rank = (matches, output, indexed)
        if rank > best_rank:
            best, best_rank = directory, rank
        if directory == boundary or output or (directory / "package.json").is_file():
            break
        directory = directory.parent
    return "" if best == boundary else best.relative_to(boundary).as_posix()


@dataclass(frozen=True)
class PreviewSession:
    session_id: str
    owner: tuple[str, int]
    alias: str
    agent_id: str
    identity: tuple
    root: str
    root_identity: tuple[str, int, int]
    entry_path: str
    site_directory: str
    deadline: float
    expires_at: str


def directory_identity(root: str) -> tuple[str, int, int]:
    try:
        info = os.stat(root)
    except OSError as exc:
        raise WebApiError(410, "preview_scope_changed", "预览资源根目录已不可用") from exc
    return os.path.realpath(root), info.st_dev, info.st_ino


class HtmlPreviewStore:
    def __init__(self, *, ttl: float = 900, max_sessions: int = 128, per_user: int = 16):
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.per_user = per_user
        self._sessions: dict[str, PreviewSession] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for key, session in list(self._sessions.items()):
            if session.deadline <= now:
                del self._sessions[key]

    def create(self, *, owner: tuple[str, int], alias: str, agent_id: str,
               identity: tuple, root: str, entry_path: str, site_directory: str = "") -> PreviewSession:
        self._prune()
        root = os.path.realpath(root)
        if (len(self._sessions) >= self.max_sessions
                or sum(item.owner == owner for item in self._sessions.values()) >= self.per_user):
            raise WebApiError(429, "preview_capacity", "预览会话过多，请关闭其他预览后重试")
        session = PreviewSession(
            secrets.token_urlsafe(32), owner, alias, agent_id, identity, root, directory_identity(root), entry_path, site_directory,
            time.monotonic() + self.ttl,
            datetime.fromtimestamp(time.time() + self.ttl, timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> PreviewSession:
        self._prune()
        session = self._sessions.get(session_id)
        if session is None:
            raise WebApiError(410, "preview_expired", "预览已关闭或过期，请重新打开")
        return session

    def revoke(self, session_id: str, *, owner: tuple[str, int], alias: str, agent_id: str) -> None:
        self._prune()
        session = self._sessions.get(session_id)
        if session is not None:
            if (session.owner, session.alias, session.agent_id) != (owner, alias, agent_id):
                raise WebApiError(403, "preview_owner_mismatch", "无权关闭此预览")
            self._sessions.pop(session_id, None)

    def invalidate(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


def resource_prefix(base_path: str, session_id: str) -> str:
    return f"{base_path}/api/file-previews/{session_id}/"


def entry_url(session: PreviewSession, base_path: str) -> str:
    return resource_prefix(base_path, session.session_id) + quote(session.entry_path, safe="/")


_BRIDGE = Path(__file__).with_name("html_preview_bridge.js").read_text(encoding="utf-8")


def site_prefix(session: PreviewSession, prefix: str) -> str:
    return prefix + (quote(session.site_directory, safe="/") + "/" if session.site_directory else "")


def inject_bridge(data: bytes, session: PreviewSession, prefix: str, *, xhtml: bool = False) -> bytes:
    try:
        source = decode_text_bytes(data).text
    except UnsupportedTextEncoding as exc:
        raise WebApiError(415, "preview_encoding", "HTML 文本编码不受支持") from exc
    if xhtml:
        source = re.sub(r'(<\?xml\b[^>]*\bencoding\s*=\s*)["\'][^"\']+["\']', r'\1"utf-8"', source, count=1)
    site = site_prefix(session, prefix)
    options = json.dumps([session.session_id, prefix, site, ORIGINAL_CSS_PARAM]).replace("<", "\\u003c")
    script = _BRIDGE.replace("PREVIEW_OPTIONS", options, 1)
    bridge = "<script>" + ("<![CDATA[" + script + "]]>" if xhtml else script) + "</script>"
    return PreviewDocument(source, site, prefix).render(bridge)


def preview_resource(session: PreviewSession, path: str, prefix: str, *, original_css: bool = False) -> tuple[bytes, str, bool]:
    """Return a rendered resource and whether its directory URL needs a trailing slash."""
    relative = _requested_file(session.root, path)
    if relative != path and path and not path.endswith("/"):
        return b"", MIME_TYPES[Path(relative).suffix], True
    data, mime = read_resource(session.root, relative, original_css=original_css)
    if mime in {"text/html", "application/xhtml+xml"}:
        data = inject_bridge(data, session, prefix, xhtml=mime == "application/xhtml+xml")
    elif mime == "text/css" and not original_css:
        data = rewrite_css(data.decode("utf-8"), site_prefix(session, prefix)).encode("utf-8")
    return data, mime, False


def security_headers(host: str, prefix: str) -> dict[str, str]:
    # Scheme-less host sources inherit the browser's scheme behind TLS proxies.
    if not re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", host):
        raise WebApiError(400, "preview_invalid_host", "预览请求主机无效")
    source = host + quote(prefix, safe="/")
    return {
        "Content-Security-Policy": "; ".join([
            "default-src 'none'", "sandbox allow-scripts allow-forms allow-downloads",
            f"script-src {source} 'unsafe-inline'", f"style-src {source} 'unsafe-inline'",
            f"img-src {source} data:", f"font-src {source}", f"connect-src {source}",
            "form-action 'none'", "object-src 'none'", "frame-src 'none'", "worker-src 'none'", f"base-uri {source}",
        ]),
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*",
    }
