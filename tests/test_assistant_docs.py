from pathlib import Path

from bot.assistant_docs import sync_managed_prompt_files
from bot.assistant_home import bootstrap_assistant_home


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
    assert agents_text == (
        "agent template\n\n"
        "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->\n"
        "current_goal:\n"
        "- Finish task 2 sync\n"
        "<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n"
    )
    assert claude_text == (
        "claude template\n\n"
        "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->\n"
        "current_goal:\n"
        "- Finish task 2 sync\n"
        "<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n"
    )


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
