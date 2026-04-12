from pathlib import Path

from bot.assistant_docs import (
    compute_managed_prompt_hash,
    read_current_managed_prompt_hash,
    sync_managed_prompt_files,
)
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_compaction import save_compaction_state


def test_sync_managed_prompt_files_creates_agents_and_claude_with_memory_block(tmp_path: Path):
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    (repo_root / "AGENTS.md").write_text("agent template", encoding="utf-8")
    (repo_root / "CLAUDE.md").write_text("claude template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "# Goal\n- Finish task 2 sync\n",
        encoding="utf-8",
    )

    result = sync_managed_prompt_files(home, repo_root=repo_root)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    claude_text = home.claude_path.read_text(encoding="utf-8")

    assert result.agents_changed is True
    assert result.claude_changed is True
    assert result.managed_prompt_hash
    assert agents_text.startswith(
        "agent template\n\n"
        "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->\n"
        "current_goal:\n"
        "- Finish task 2 sync\n"
    )
    assert "compaction_maintenance" not in agents_text
    assert agents_text.endswith("<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n")
    assert claude_text.startswith(
        "claude template\n\n"
        "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->\n"
        "current_goal:\n"
        "- Finish task 2 sync\n"
    )
    assert "compaction_maintenance" not in claude_text
    assert claude_text.endswith("<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n")


def test_sync_managed_prompt_files_includes_compaction_tail_when_pending(tmp_path: Path):
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    (repo_root / "AGENTS.md").write_text("agent template", encoding="utf-8")
    (repo_root / "CLAUDE.md").write_text("claude template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    save_compaction_state(
        home,
        {
            "pending": True,
            "pending_reason": "capture_threshold",
            "pending_capture_count": 6,
            "cursor_capture_id": "cap_000001",
            "last_compacted_at": None,
        },
    )

    sync_managed_prompt_files(home, repo_root=repo_root)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert "后台维护" in agents_text
    assert ".assistant/proposals" in agents_text


def test_sync_managed_prompt_files_overwrites_drifted_copy(tmp_path: Path):
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    (repo_root / "AGENTS.md").write_text("fresh agents", encoding="utf-8")
    (repo_root / "CLAUDE.md").write_text("fresh claude", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "- Correct drifted prompts\n",
        encoding="utf-8",
    )
    home.agents_path.write_text("drifted agents", encoding="utf-8")
    home.claude_path.write_text("drifted claude", encoding="utf-8")

    first = sync_managed_prompt_files(home, repo_root=repo_root)
    second = sync_managed_prompt_files(home, repo_root=repo_root)

    assert first.agents_changed is True
    assert first.claude_changed is True
    assert second.agents_changed is False
    assert second.claude_changed is False
    assert second.managed_prompt_hash == first.managed_prompt_hash
    assert home.agents_path.read_text(encoding="utf-8").startswith("fresh agents\n\n")
    assert home.claude_path.read_text(encoding="utf-8").startswith("fresh claude\n\n")


def test_sync_managed_prompt_files_rebuilds_memory_tail_after_working_memory_change(tmp_path: Path):
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    (repo_root / "AGENTS.md").write_text("agent template", encoding="utf-8")
    (repo_root / "CLAUDE.md").write_text("claude template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    working_dir = home.root / "memory" / "working"
    (working_dir / "current_goal.md").write_text("- First goal\n", encoding="utf-8")

    first = sync_managed_prompt_files(home, repo_root=repo_root)

    (working_dir / "current_goal.md").write_text("- Second goal\n", encoding="utf-8")
    second = sync_managed_prompt_files(home, repo_root=repo_root)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert first.managed_prompt_hash != second.managed_prompt_hash
    assert second.agents_changed is True
    assert "- Second goal" in agents_text
    assert "- First goal" not in agents_text


def test_read_current_managed_prompt_hash_returns_none_when_managed_files_missing(tmp_path: Path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    assert read_current_managed_prompt_hash(home) is None


def test_read_current_managed_prompt_hash_matches_helper(tmp_path: Path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    home.agents_path.write_text("agent body\n", encoding="utf-8")
    home.claude_path.write_text("claude body\n", encoding="utf-8")

    assert read_current_managed_prompt_hash(home) == compute_managed_prompt_hash(
        "agent body\n",
        "claude body\n",
    )
