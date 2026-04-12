from pathlib import Path

import pytest

from bot.assistant_docs import (
    compute_managed_prompt_hash,
    read_current_managed_prompt_hash,
    resolve_assistant_managed_template_path,
    sync_managed_prompt_files,
)
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_compaction import save_compaction_state


def test_resolve_assistant_managed_template_path_points_to_repo_asset():
    path = resolve_assistant_managed_template_path()

    assert path.name == "managed_prompt_template.md"
    assert path.is_file()

    text = path.read_text(encoding="utf-8")
    assert "你是宿主管理的本地长期 assistant" in text
    assert ".assistant/proposals" in text
    assert ".assistant/memory/skills" in text
    assert "current_goal.md" in text
    assert "open_loops.md" in text
    assert "user_prefs.md" in text
    assert "recent_summary.md" in text
    assert "不要创建任意新的 working 记忆文件" in text
    assert "AGENTS.md" in text
    assert "CLAUDE.md" in text


def test_sync_managed_prompt_files_uses_single_template_for_both_outputs(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "# Goal\n- Finish task 2 sync\n",
        encoding="utf-8",
    )

    result = sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    claude_text = home.claude_path.read_text(encoding="utf-8")

    assert result.agents_changed is True
    assert result.claude_changed is True
    assert agents_text == claude_text
    assert agents_text.startswith(
        "assistant template\n\n"
        "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->\n"
        "current_goal:\n"
        "- Finish task 2 sync\n"
    )
    assert agents_text.endswith("<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n")


def test_sync_managed_prompt_files_raises_when_template_missing(tmp_path: Path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    with pytest.raises(FileNotFoundError):
        sync_managed_prompt_files(home, template_path=tmp_path / "missing-template.md")


def test_sync_managed_prompt_files_creates_agents_and_claude_with_memory_block(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "# Goal\n- Finish task 2 sync\n",
        encoding="utf-8",
    )

    result = sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    claude_text = home.claude_path.read_text(encoding="utf-8")

    assert result.agents_changed is True
    assert result.claude_changed is True
    assert result.managed_prompt_hash
    assert agents_text.startswith(
        "assistant template\n\n"
        "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->\n"
        "current_goal:\n"
        "- Finish task 2 sync\n"
    )
    assert "compaction_maintenance" not in agents_text
    assert agents_text.endswith("<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n")
    assert agents_text == claude_text
    assert "compaction_maintenance" not in claude_text
    assert claude_text.endswith("<!-- END HOST_MANAGED_MEMORY_PROMPT -->\n")


def test_sync_managed_prompt_files_includes_compaction_tail_when_pending(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

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

    sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert "后台维护" in agents_text
    assert ".assistant/proposals" in agents_text


def test_sync_managed_prompt_files_overwrites_drifted_copy(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("fresh assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    (home.root / "memory" / "working" / "current_goal.md").write_text(
        "- Correct drifted prompts\n",
        encoding="utf-8",
    )
    home.agents_path.write_text("drifted agents", encoding="utf-8")
    home.claude_path.write_text("drifted claude", encoding="utf-8")

    first = sync_managed_prompt_files(home, template_path=template_path)
    second = sync_managed_prompt_files(home, template_path=template_path)

    assert first.agents_changed is True
    assert first.claude_changed is True
    assert second.agents_changed is False
    assert second.claude_changed is False
    assert second.managed_prompt_hash == first.managed_prompt_hash
    assert home.agents_path.read_text(encoding="utf-8") == home.claude_path.read_text(encoding="utf-8")
    assert home.agents_path.read_text(encoding="utf-8").startswith("fresh assistant template\n\n")


def test_sync_managed_prompt_files_rebuilds_memory_tail_after_working_memory_change(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    working_dir = home.root / "memory" / "working"
    (working_dir / "current_goal.md").write_text("- First goal\n", encoding="utf-8")

    first = sync_managed_prompt_files(home, template_path=template_path)

    (working_dir / "current_goal.md").write_text("- Second goal\n", encoding="utf-8")
    second = sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert first.managed_prompt_hash != second.managed_prompt_hash
    assert second.agents_changed is True
    assert "- Second goal" in agents_text
    assert "- First goal" not in agents_text


def test_sync_managed_prompt_files_includes_assistant_skill_descriptions(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    skill_dir = home.root / "memory" / "skills" / "summarize_logs"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: summarize_logs\n"
        "description: Summarize noisy log output into concise findings.\n"
        "---\n\n"
        "# Summarize Logs\n",
        encoding="utf-8",
    )

    sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert "assistant_skills:" in agents_text
    assert ".assistant/memory/skills" in agents_text
    assert "summarize_logs: Summarize noisy log output into concise findings." in agents_text


def test_sync_managed_prompt_files_rebuilds_memory_tail_after_skill_description_change(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)
    skill_dir = home.root / "memory" / "skills" / "summarize_logs"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: summarize_logs\n"
        "description: Summarize noisy log output into concise findings.\n"
        "---\n\n"
        "# Summarize Logs\n",
        encoding="utf-8",
    )

    first = sync_managed_prompt_files(home, template_path=template_path)

    skill_path.write_text(
        "---\n"
        "name: summarize_logs\n"
        "description: Turn noisy logs into short issue summaries and likely causes.\n"
        "---\n\n"
        "# Summarize Logs\n",
        encoding="utf-8",
    )

    second = sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert first.managed_prompt_hash != second.managed_prompt_hash
    assert second.agents_changed is True
    assert "Turn noisy logs into short issue summaries and likely causes." in agents_text
    assert "Summarize noisy log output into concise findings." not in agents_text


def test_sync_managed_prompt_files_keeps_managed_prompt_hash_stable_for_compaction_only_changes(tmp_path: Path):
    template_path = tmp_path / "managed_prompt_template.md"
    template_path.write_text("assistant template", encoding="utf-8")

    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    home = bootstrap_assistant_home(workdir)

    first = sync_managed_prompt_files(home, template_path=template_path)

    from bot.assistant_state import record_assistant_capture
    from bot.assistant_compaction import refresh_compaction_state

    capture = record_assistant_capture(home, 1001, "assistant 是全局的，工作路径固定，不允许修改", "记住了")
    refresh_compaction_state(home, latest_capture=capture)
    second = sync_managed_prompt_files(home, template_path=template_path)

    agents_text = home.agents_path.read_text(encoding="utf-8")
    assert first.managed_prompt_hash == second.managed_prompt_hash
    assert second.agents_changed is True
    assert "maintenance:" in agents_text


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
