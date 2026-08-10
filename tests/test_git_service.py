from __future__ import annotations

import pytest

from bot.web import git_service


def test_changed_file_stats_fall_back_when_numstat_exceeds_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_budget_error(*_args: object, **_kwargs: object) -> None:
        raise git_service.GitCommandError("Git 命令超过资源预算: timeout")

    monkeypatch.setattr(git_service, "_run_git", raise_budget_error)

    changed_file = {
        "path": "tracked.txt",
        "status": " M",
        "staged": False,
        "unstaged": True,
        "untracked": False,
    }

    assert git_service._merge_changed_file_stats("C:/repo", [changed_file]) == [
        {
            **changed_file,
            "additions": 0,
            "deletions": 0,
            "staged_additions": 0,
            "staged_deletions": 0,
            "unstaged_additions": 0,
            "unstaged_deletions": 0,
        }
    ]
