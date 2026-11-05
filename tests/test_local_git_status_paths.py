"""Local Git status parsing must keep paths with spaces and non-ASCII literal."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bot.git_shared import _format_porcelain_entries, _parse_porcelain_v1_z
from bot.web import git_service

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")

SPACE_NAME = "a b.txt"
CHINESE_NAME = "中文.txt"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    global_config = tmp_path / "gitconfig"
    global_config.write_text("[user]\n\tname = Test\n\temail = test@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for name in (SPACE_NAME, CHINESE_NAME, "old name.txt"):
        (root / name).write_text(f"original {name}\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    monkeypatch.setattr(git_service, "_get_git_working_dir", lambda _manager, _alias: str(root))
    git_service._invalidate_git_status_cache(str(root.resolve()))
    return root


def _status(repo: Path) -> str:
    return _git(repo, "status", "--porcelain=1", "--untracked-files=all")


def test_porcelain_v1_z_parser_keeps_literal_paths_and_rename_origin():
    entries = _parse_porcelain_v1_z(
        "?? 新 文件.txt\x00 M a -> b.txt\x00R  新 name.txt\x00old name.txt\x00"
    )

    assert [(item["status"], item["path"], item["original_path"], item["untracked"]) for item in entries] == [
        ("??", "新 文件.txt", "", True),
        (" M", "a -> b.txt", "", False),
        ("R ", "新 name.txt", "old name.txt", False),
    ]
    assert _format_porcelain_entries(entries).splitlines() == [
        "?? 新 文件.txt",
        " M a -> b.txt",
        "R  old name.txt -> 新 name.txt",
    ]


def test_discard_paths_handles_spaces_and_chinese_names(repo: Path):
    for name in (SPACE_NAME, CHINESE_NAME):
        (repo / name).write_text("changed\n", encoding="utf-8")
    (repo / "c d.txt").write_text("new\n", encoding="utf-8")
    (repo / "新文件.txt").write_text("new\n", encoding="utf-8")

    git_service.discard_git_paths(None, "main", 1, [SPACE_NAME, "c d.txt"])
    assert (repo / SPACE_NAME).read_text(encoding="utf-8") == f"original {SPACE_NAME}\n"
    assert not (repo / "c d.txt").exists()

    git_service.discard_git_paths(None, "main", 1, [CHINESE_NAME, "新文件.txt"])
    assert (repo / CHINESE_NAME).read_text(encoding="utf-8") == f"original {CHINESE_NAME}\n"
    assert not (repo / "新文件.txt").exists()
    assert _status(repo) == ""


def test_discard_all_restores_quoted_names_and_staged_rename(repo: Path):
    (repo / CHINESE_NAME).write_text("changed\n", encoding="utf-8")
    (repo / "新文件.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "mv", "old name.txt", "新 name.txt")

    git_service.discard_all_git_changes(None, "main", 1)

    assert (repo / CHINESE_NAME).read_text(encoding="utf-8") == f"original {CHINESE_NAME}\n"
    assert (repo / "old name.txt").read_text(encoding="utf-8") == "original old name.txt\n"
    assert not (repo / "新 name.txt").exists()
    assert not (repo / "新文件.txt").exists()
    assert _status(repo) == ""


def test_overview_tree_status_and_commit_context_use_literal_paths(repo: Path):
    (repo / CHINESE_NAME).write_text("changed\nmore\n", encoding="utf-8")
    (repo / "新文件.txt").write_text("hello preview\n", encoding="utf-8")

    overview = git_service.get_git_overview(None, "main", 1)
    changed = {item["path"]: item for item in overview["changed_files"]}
    assert changed[CHINESE_NAME]["unstaged_additions"] == 2
    assert changed["新文件.txt"]["untracked"] is True

    tree = git_service.get_git_tree_status(None, "main", 1)
    assert tree["items"][CHINESE_NAME] == "modified"
    assert tree["items"]["新文件.txt"] == "added"

    context = git_service._read_git_smart_commit_message_context(str(repo.resolve()))
    assert "?? 新文件.txt" in context["status_text"]
    assert "hello preview" in context["diff_text"]
