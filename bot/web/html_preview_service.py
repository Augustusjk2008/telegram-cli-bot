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
from urllib.parse import quote

from bot.web.api_common import WebApiError
from bot.web.files_service import resolve_safe_path
from bot.web.text_encoding import UnsupportedTextEncoding, decode_text_bytes


HTML_LIMIT = 1024 * 1024
RESOURCE_LIMIT = 16 * 1024 * 1024
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
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


def validate_relative_path(value: str) -> str:
    # aiohttp already decodes route parameters once. Reject residual escapes,
    # Windows aliases/ADS and ambiguous separators instead of decoding again.
    if not value or any(c in value for c in "\\:%?#") or any(ord(c) < 32 for c in value):
        raise WebApiError(400, "unsafe_preview_path", "预览资源路径不安全")
    for part in value.split("/"):
        if (not part or part.startswith(".") or part.endswith((".", " "))
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


def read_resource(root: str, relative: str) -> tuple[bytes, str]:
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
    if suffix in {".css", ".js", ".mjs", ".json"}:
        try:
            data = decode_text_bytes(data).text.encode("utf-8")
        except UnsupportedTextEncoding as exc:
            raise WebApiError(415, "preview_encoding", "资源文本编码不受支持") from exc
    return data, mime


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
               identity: tuple, root: str, entry_path: str) -> PreviewSession:
        self._prune()
        root = os.path.realpath(root)
        if (len(self._sessions) >= self.max_sessions
                or sum(item.owner == owner for item in self._sessions.values()) >= self.per_user):
            raise WebApiError(429, "preview_capacity", "预览会话过多，请关闭其他预览后重试")
        session = PreviewSession(
            secrets.token_urlsafe(32), owner, alias, agent_id, identity, root, directory_identity(root), entry_path,
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


class _HeadInsertion(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", source))]
        self.head: int | None = None
        self.empty_head: tuple[int, str] | None = None
        self.fallback = 0

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "head" and self.head is None:
            self.head = self._offset() + len(self.get_starttag_text())
        elif tag == "html":
            self.fallback = self._offset() + len(self.get_starttag_text())

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.fallback = self._offset() + len(decl) + 3

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "head" and self.head is None:
            self.empty_head = (self._offset(), self.get_starttag_text())

    def handle_pi(self, data: str) -> None:
        if data.startswith("xml "):
            self.fallback = self._offset() + len(data) + 3


def inject_bridge(data: bytes, session: PreviewSession, prefix: str, *, xhtml: bool = False) -> bytes:
    try:
        source = decode_text_bytes(data).text
    except UnsupportedTextEncoding as exc:
        raise WebApiError(415, "preview_encoding", "HTML 文本编码不受支持") from exc
    if xhtml:
        source = re.sub(r'(<\?xml\b[^>]*\bencoding\s*=\s*)["\'][^"\']+["\']', r'\1"utf-8"', source, count=1)
    script = r"""(() => {
const sessionId = SESSION_ID, prefix = RESOURCE_PREFIX;
const path = () => location.pathname.slice(prefix.length) + location.search + location.hash;
let failure = "";
const send = (event, message) => {
  if (event === "error") failure = message;
  parent.postMessage({type: "orbit-html-preview", sessionId, event: failure ? "error" : event, path: path(), ...(failure ? {message: failure} : {})}, "*");
};
addEventListener("message", event => {
  const data = event.data;
  if (event.source === parent && data && data.type === "orbit-html-preview" && data.sessionId === sessionId && data.command === "refresh") location.reload();
});
addEventListener("hashchange", () => send("path"));
addEventListener("popstate", () => send("path"));
for (const name of ["pushState", "replaceState"]) {
  const original = history[name];
  history[name] = function(...args) { const result = original.apply(this, args); send("path"); return result; };
}
addEventListener("error", event => send("error", event.message || "资源加载失败"), true);
addEventListener("unhandledrejection", event => send("error", String(event.reason || "页面脚本失败")));
addEventListener("DOMContentLoaded", () => send("ready"), {once: true});
})();""".replace("SESSION_ID", json.dumps(session.session_id)).replace("RESOURCE_PREFIX", json.dumps(prefix))
    script = "<script>" + ("<![CDATA[" + script + "]]>" if xhtml else script) + "</script>"
    parser = _HeadInsertion(source)
    parser.feed(source)
    if parser.empty_head is not None and parser.head is None:
        offset, tag = parser.empty_head
        return (source[:offset] + tag[:-2] + ">" + script + "</head>" + source[offset + len(tag):]).encode("utf-8")
    offset = parser.head if parser.head is not None else parser.fallback
    return (source[:offset] + script + source[offset:]).encode("utf-8")


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
            "form-action 'none'", "object-src 'none'", "frame-src 'none'", "worker-src 'none'", "base-uri 'none'",
        ]),
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*",
    }
