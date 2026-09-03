from __future__ import annotations

from bot.web.git_commit_message import truncate_diff_text


def test_truncate_diff_text_balances_budget_across_files() -> None:
    summary = "3 files changed, 300 insertions(+), 300 deletions(-)\n"
    file_diffs = [
        (
            f"diff --git a/{name}.txt b/{name}.txt\n"
            f"index 1111111..2222222 100644\n"
            f"--- a/{name}.txt\n"
            f"+++ b/{name}.txt\n"
            "@@ -1 +1 @@\n"
            f"-{marker}-old-" + "x" * 400 + "\n"
            f"+{marker}-new-" + "y" * 400 + "\n"
        )
        for name, marker in [("alpha", "ALPHA"), ("beta", "BETA"), ("gamma", "GAMMA")]
    ]

    result, truncated = truncate_diff_text(summary + "".join(file_diffs), limit=600)

    assert truncated is True
    assert summary.strip() in result
    for name, marker in [("alpha", "ALPHA"), ("beta", "BETA"), ("gamma", "GAMMA")]:
        assert f"diff --git a/{name}.txt b/{name}.txt" in result
        assert marker in result


def test_truncate_diff_text_reuses_budget_left_by_small_files() -> None:
    small = "diff --git a/small.txt b/small.txt\n-small\n+small change\n"
    large_a = "diff --git a/large-a.txt b/large-a.txt\n" + "A" * 1_000 + "\n"
    large_b = "diff --git a/large-b.txt b/large-b.txt\n" + "B" * 1_000 + "\n"

    result, truncated = truncate_diff_text(small + large_a + large_b, limit=600)

    content = result.removesuffix("\n\n...[truncated]")
    assert truncated is True
    assert len(content) >= 580
    assert "A" * 200 in content
    assert "B" * 200 in content
