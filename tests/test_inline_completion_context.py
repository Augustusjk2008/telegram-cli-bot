from pathlib import Path

from bot.web.inline_completion_config import InlineCompletionConfig

from bot.web.inline_completion_context import build_inline_completion_context

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
