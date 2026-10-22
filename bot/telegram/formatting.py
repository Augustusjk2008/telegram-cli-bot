"""Render Markdown and split Telegram HTML without losing displayed text."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token


_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("strikethrough")
_LINK_SCHEMES = {"http", "https", "tg", "mailto", "tel"}


@dataclass(frozen=True)
class _Tag:
    name: str
    opening: str


class _HTMLWriter:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.tags: tuple[_Tag, ...] = ()

    def write(self, text: str, tags: tuple[_Tag, ...]) -> None:
        if not text:
            return
        common = 0
        while common < min(len(self.tags), len(tags)) and self.tags[common] == tags[common]:
            common += 1
        self.parts.extend(f"</{tag.name}>" for tag in reversed(self.tags[common:]))
        self.parts.extend(tag.opening for tag in tags[common:])
        self.parts.append(escape(text, quote=False))
        self.tags = tags

    def finish(self) -> str:
        return "".join(self.parts) + "".join(f"</{tag.name}>" for tag in reversed(self.tags))


def _safe_link(url: str) -> bool:
    if any(char.isspace() or ord(char) < 32 or char == "\\" for char in url):
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in _LINK_SCHEMES:
            return False
        if parsed.scheme in {"http", "https", "tg"}:
            # Accessing port also rejects malformed ports and IPv6 addresses.
            _ = parsed.port
            return bool(parsed.hostname)
        return bool(parsed.path)
    except ValueError:
        return False


class _MarkdownRenderer:
    def __init__(self) -> None:
        self.writer = _HTMLWriter()
        self.tags: list[_Tag] = []
        self.pending_breaks = 0
        self.break_tags: tuple[_Tag, ...] = ()
        self.trailing_breaks = 0

    def separate(self, count: int) -> None:
        self.pending_breaks = max(self.pending_breaks, count)
        self.break_tags = tuple(self.tags)

    def write(self, text: str, tags: list[_Tag] | None = None) -> None:
        if not text:
            return
        if self.writer.parts and self.pending_breaks:
            padding = "\n" * max(0, self.pending_breaks - self.trailing_breaks)
            self.writer.write(padding, self.break_tags)
            self.trailing_breaks += len(padding)
        self.pending_breaks = 0
        active = self.tags if tags is None else tags
        # Telegram forbids nested blockquotes and links inside other non-style
        # entities. Repeated Markdown emphasis needs only one Telegram entity.
        unique: list[_Tag] = []
        for tag in active:
            if tag.name == "blockquote" and any(item.name == "a" for item in active):
                continue
            if tag not in unique:
                unique.append(tag)
        self.writer.write(text, tuple(unique))
        if text.strip("\n"):
            self.trailing_breaks = len(text) - len(text.rstrip("\n"))
        else:
            self.trailing_breaks += len(text)

    def inline(self, tokens: list[Token]) -> None:
        tags = self.tags.copy()
        links: list[tuple[str, bool]] = []
        styles = {"strong": "b", "em": "i", "s": "s"}
        for token in tokens:
            kind = token.type
            style, _, direction = kind.rpartition("_")
            if style in styles and direction == "open":
                name = styles[style]
                tags.append(_Tag(name, f"<{name}>"))
            elif style in styles and direction == "close":
                tags.pop()
            elif kind == "link_open":
                url = token.attrGet("href") or ""
                safe = _safe_link(url)
                links.append((url, safe))
                if safe:
                    tags.append(_Tag("a", f'<a href="{escape(url, quote=True)}">'))
                else:
                    self.write("[", tags)
            elif kind == "link_close":
                url, safe = links.pop()
                if safe:
                    tags.pop()
                else:
                    self.write(f"]({url})", tags)
            elif kind == "code_inline":
                # Code entities cannot overlap bold, links, or blockquotes.
                self.write(token.content, [_Tag("code", "<code>")])
            elif kind in {"softbreak", "hardbreak"}:
                self.write("\n", tags)
            elif kind == "image":
                self.write(f'{token.content} ({token.attrGet("src") or ""})', tags)
            else:
                self.write(token.content, tags)

    def render(self, tokens: list[Token]) -> str:
        lists: list[int | None] = []
        quote_depth = 0
        for token in tokens:
            kind = token.type
            if kind == "inline":
                self.inline(token.children or [])
            elif kind == "heading_open":
                self.tags.append(_Tag("b", "<b>"))
            elif kind == "heading_close":
                self.tags.pop()
                self.separate(2)
            elif kind == "paragraph_close":
                self.separate(1 if token.hidden else 2)
            elif kind in {"fence", "code_block"}:
                language = token.info.split()[0] if token.info.strip() else ""
                opening = f'<code class="language-{escape(language, quote=True)}">' if language else "<code>"
                self.write(token.content, [_Tag("pre", "<pre>"), _Tag("code", opening)])
                self.separate(2)
            elif kind == "blockquote_open":
                if quote_depth == 0:
                    self.tags.append(_Tag("blockquote", "<blockquote>"))
                quote_depth += 1
            elif kind == "blockquote_close":
                quote_depth -= 1
                if quote_depth == 0:
                    self.tags.pop()
                self.separate(2)
            elif kind in {"bullet_list_open", "ordered_list_open"}:
                lists.append(int(token.attrGet("start") or 1) if kind == "ordered_list_open" else None)
            elif kind == "list_item_open":
                number = lists[-1]
                marker = "• " if number is None else f"{number}. "
                self.write("  " * (len(lists) - 1) + marker)
                if number is not None:
                    lists[-1] = number + 1
            elif kind == "list_item_close":
                self.separate(1)
            elif kind in {"bullet_list_close", "ordered_list_close"}:
                lists.pop()
                self.separate(1 if lists else 2)
            elif kind == "hr":
                self.write("────────")
                self.separate(2)
        return self.writer.finish()


def markdown_to_telegram_html(text: str) -> str:
    """Render CommonMark plus strikethrough for ``parse_mode=HTML``.

    Headings become bold, lists retain visible markers, and raw HTML is escaped.
    Only absolute http/https/tg/mailto/tel destinations become clickable links;
    other destinations stay visible. Code keeps its literal contents.
    """
    return _MarkdownRenderer().render(_MARKDOWN.parse(text))


class _TelegramHTMLParser(HTMLParser):
    """Read entity-decoded text with its current Telegram HTML tag stack."""

    def __init__(self, on_text: Callable[[str, tuple[_Tag, ...]], None]) -> None:
        super().__init__(convert_charrefs=True)
        self.on_text = on_text
        self.tags: list[_Tag] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(_Tag(tag, self.get_starttag_text()))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.tags) - 1, -1, -1):
            if self.tags[index].name == tag:
                del self.tags[index:]
                break

    def handle_data(self, data: str) -> None:
        self.on_text(data, tuple(self.tags))


def telegram_html_to_text(html: str) -> str:
    """Extract displayed text from Telegram HTML, decoding entities once."""
    parts: list[str] = []
    parser = _TelegramHTMLParser(lambda text, tags: parts.append(text))
    parser.feed(html)
    parser.close()
    return "".join(parts)


def split_telegram_html(html: str, limit: int = 4096) -> list[str]:
    """Split Telegram HTML into closed fragments of at most ``limit`` UTF-16 units.

    Input is Telegram-compatible HTML, e.g. ``markdown_to_telegram_html`` output.
    Formatting and link/code attributes reopen on each page. Entity spelling may
    be normalized, but concatenating decoded fragments preserves all text.
    Empty displayed text returns no fragments. Raise ValueError if the limit is
    nonpositive or a single Unicode character cannot fit (e.g. emoji at limit 1).
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    parts: list[str] = []
    writer = _HTMLWriter()
    units = 0

    def on_text(text: str, tags: tuple[_Tag, ...]) -> None:
        nonlocal writer, units
        start = 0
        for index, char in enumerate(text):
            width = 2 if ord(char) > 0xFFFF else 1
            if width > limit:
                raise ValueError("limit cannot fit a Unicode character")
            if units + width > limit:
                writer.write(text[start:index], tags)
                parts.append(writer.finish())
                writer = _HTMLWriter()
                units = 0
                start = index
            units += width
        writer.write(text[start:], tags)

    parser = _TelegramHTMLParser(on_text)
    parser.feed(html)
    parser.close()
    if units:
        parts.append(writer.finish())
    return parts
