from pathlib import Path

from bot.web.inline_completion_config import InlineCompletionConfig
from bot.web.inline_completion_context import build_inline_completion_context


def test_inline_completion_context_trims_current_file_window(tmp_path: Path) -> None:
    config = InlineCompletionConfig(max_prefix_chars=10, max_suffix_chars=6)

    context = build_inline_completion_context(
        workspace_root=tmp_path,
        relative_path="app.py",
        prefix="0123456789abcdef",
        suffix="ghijklmnop",
        language_id="python",
        config=config,
    )

    assert context.prefix == "6789abcdef"
    assert context.suffix == "ghijkl"
    assert context.truncated is True


def test_inline_completion_context_collects_local_imports_and_respects_denylist(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    config = InlineCompletionConfig(max_related_files=4, max_related_file_bytes=128)

    context = build_inline_completion_context(
        workspace_root=tmp_path,
        relative_path="app.py",
        prefix="from pkg import helper\nimport os\n",
        suffix="",
        language_id="python",
        config=config,
    )

    assert [item.path for item in context.related_files] == ["pkg/helper.py"]
    assert "return 1" in context.related_files[0].content
    assert all(item.path != ".env" for item in context.related_files)


def test_inline_completion_context_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    config = InlineCompletionConfig()

    context = build_inline_completion_context(
        workspace_root=tmp_path,
        relative_path="../outside.py",
        prefix="",
        suffix="",
        language_id="python",
        config=config,
    )

    assert context.denied is True
    assert context.related_files == []
