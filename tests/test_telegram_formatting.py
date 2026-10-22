from __future__ import annotations

from html import escape
from xml.etree import ElementTree

import pytest

from bot.telegram.formatting import (
    markdown_to_telegram_html,
    split_telegram_html,
    telegram_html_to_text,
)


def _fragment_text(fragment: str) -> str:
    # An independent strict parser catches unclosed tags and broken entities.
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    assert {node.tag for node in root.iter()} <= {
        "root", "b", "i", "u", "s", "a", "code", "pre", "blockquote",
    }
    return "".join(root.itertext())


def test_headings_inline_styles_lists_quotes_and_paragraphs():
    rendered = markdown_to_telegram_html(
        "# **标题**\n\n"
        "**粗体**、*斜体*、~~删除~~、***嵌套***。\n换行  \n硬换行\n\n"
        "- 第一项\n  - 子项\n- 第二项\n\n"
        "3. 第三项\n4. 第四项\n\n"
        "> 引用 **重点**\n>\n> > 内层引用\n\n"
        "小标题\n------\n\n末段"
    )
    assert rendered.startswith("<b>标题</b>\n\n")
    assert "<b>粗体</b>、<i>斜体</i>、<s>删除</s>、<i><b>嵌套</b></i>。" in rendered
    assert "• 第一项\n  • 子项\n• 第二项\n\n3. 第三项\n4. 第四项" in rendered
    assert "<blockquote>引用 <b>重点</b>\n\n内层引用</blockquote>" in rendered
    assert "<b>小标题</b>\n\n末段" in rendered
    assert "换行\n硬换行" in _fragment_text(rendered)


def test_raw_html_and_special_characters_remain_visible():
    source = '<b>原始</b> <script>alert("x")</script> & < > &amp; &lt;'
    rendered = markdown_to_telegram_html(source)
    assert "<b>" not in rendered
    assert "<script>" not in rendered
    assert "&lt;b&gt;原始&lt;/b&gt;" in rendered
    expected = '<b>原始</b> <script>alert("x")</script> & < > & <'
    assert _fragment_text(rendered) == expected
    assert telegram_html_to_text(rendered) == expected


@pytest.mark.parametrize("url", [
    "https://example.com/path?a=1&b=2",
    "http://example.com/path",
    "tg://user?id=123",
    "mailto:dev@example.com",
    "tel:+86123456789",
])
def test_supported_link_schemes_and_attribute_escaping(url):
    rendered = markdown_to_telegram_html(f"[**标签**]({url})")
    assert rendered == f'<a href="{escape(url, quote=True)}"><b>标签</b></a>'
    assert _fragment_text(rendered) == "标签"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/html,evil",
    "file:///C:/work/a.py",
    "C:/work/a.py",
    "/tmp/a.py",
    "../a.py",
    "//example.com/path",
    "vscode://file/a.py",
    "https:///missing-host",
    "https://example.com:bad/path",
])
def test_unsafe_links_and_local_paths_remain_visible(url):
    rendered = markdown_to_telegram_html(f"[文件]({url})")
    assert "<a " not in rendered
    assert _fragment_text(rendered) == f"[文件]({url})"


def test_reference_links_and_angle_autolinks_use_markdown_parser():
    rendered = markdown_to_telegram_html(
        "[文档][ref] 和 <https://example.com/auto>\n\n"
        '[ref]: https://example.com/ref "标题"'
    )
    assert rendered == (
        '<a href="https://example.com/ref">文档</a> 和 '
        '<a href="https://example.com/auto">https://example.com/auto</a>'
    )


def test_code_is_literal_and_does_not_overlap_other_entities():
    rendered = markdown_to_telegram_html(
        '**前 `*代码* & <x>` 后**\n\n'
        '```python\nprint("<&>") # **literal** 😀\n```\n\n'
        '> 引用 `code` 尾部\n>\n> ```text\n> **literal**\n> ```'
    )
    assert '<b>前 </b><code>*代码* &amp; &lt;x&gt;</code><b> 后</b>' in rendered
    assert '<pre><code class="language-python">print("&lt;&amp;&gt;") # **literal** 😀\n</code></pre>' in rendered
    root = ElementTree.fromstring(f"<root>{rendered}</root>")
    for node in root.iter():
        if node.tag not in {"root", "pre"}:
            assert node.find(".//code") is None
            assert node.find(".//pre") is None
    assert "**literal**\n" in _fragment_text(rendered)


def test_fence_language_is_escaped_as_one_attribute():
    rendered = markdown_to_telegram_html('```py"onclick="x\na < b\n```')
    root = ElementTree.fromstring(f"<root>{rendered}</root>")
    assert root.find("pre/code").attrib == {"class": 'language-py"onclick="x'}
    assert _fragment_text(rendered) == "a < b\n"


def test_plain_text_decodes_once_and_preserves_whitespace():
    html = '<b>A &amp;lt; &lt;x&gt; &#38; &#x1F600;</b>\n<pre><code>  x\n\n</code></pre>'
    assert telegram_html_to_text(html) == "A &lt; <x> & 😀\n  x\n\n"


def test_long_code_split_preserves_utf16_budget_entities_and_language():
    code = '😀 &<> **literal** "quoted"\n' * 500
    rendered = markdown_to_telegram_html(f"```python\n{code}```")
    parts = split_telegram_html(rendered)
    assert len(parts) > 2
    decoded = [_fragment_text(part) for part in parts]
    assert "".join(decoded) == code
    assert "".join(telegram_html_to_text(part) for part in parts) == code
    assert all(0 < len(text.encode("utf-16-le")) // 2 <= 4096 for text in decoded)
    assert all(part.startswith('<pre><code class="language-python">') for part in parts)
    assert all(part.endswith("</code></pre>") for part in parts)


@pytest.mark.parametrize("limit", [2, 3, 7, 16, 4096])
def test_nested_tags_links_and_entities_reopen_at_boundaries(limit):
    html = (
        '<b>开始&amp;😀<i>斜体&lt;结束&gt;</i></b>'
        '<a href="https://example.com/?a=1&amp;b=2"><s>链接😀尾部</s></a>'
        '<blockquote><u>引用&#x1F600;&#38;&quot;\n末尾</u></blockquote>'
    )
    parts = split_telegram_html(html, limit)
    decoded = [_fragment_text(part) for part in parts]
    assert "".join(decoded) == '开始&😀斜体<结束>链接😀尾部引用😀&"\n末尾'
    assert all(0 < len(text.encode("utf-16-le")) // 2 <= limit for text in decoded)
    for part in parts:
        root = ElementTree.fromstring(f"<root>{part}</root>")
        for anchor in root.iter("a"):
            assert anchor.attrib["href"] == "https://example.com/?a=1&b=2"


def test_default_limit_counts_emoji_as_two_units_and_ignores_markup():
    html = f'<b>{"a" * 4095}😀&amp;</b>'
    parts = split_telegram_html(html)
    assert parts == [f'<b>{"a" * 4095}</b>', '<b>😀&amp;</b>']
    assert split_telegram_html('<b>&amp;</b>' * 4096) == ['<b>' + '&amp;' * 4096 + '</b>']
    assert split_telegram_html("<b>ab</b><i>cd</i>", 2) == ["<b>ab</b>", "<i>cd</i>"]


def test_empty_input_and_impossible_limits():
    assert markdown_to_telegram_html("") == ""
    assert telegram_html_to_text("") == ""
    assert split_telegram_html("") == []
    assert split_telegram_html("<b></b>") == []
    assert split_telegram_html("&amp;&lt;&gt;", 1) == ["&amp;", "&lt;", "&gt;"]
    with pytest.raises(ValueError, match="positive"):
        split_telegram_html("text", 0)
    with pytest.raises(ValueError, match="Unicode"):
        split_telegram_html("😀", 1)
