import json
from pathlib import Path


def test_agents_and_claude_guides_stay_in_sync():
    assert Path("AGENTS.md").read_text(encoding="utf-8") == Path("CLAUDE.md").read_text(encoding="utf-8")


def test_repo_ignores_runtime_state_and_tracks_example_bot_config():
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "managed_bots.json" in ignore
    assert ".web_admin_settings.json" in ignore
    assert ".updates/" in ignore

    example = json.loads(Path("managed_bots.example.json").read_text(encoding="utf-8"))
    assert isinstance(example["bots"], list)


def test_readme_mentions_linux_entrypoints_and_update_flow():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "install.sh" in readme
    assert "start.sh" in readme
    assert "GitHub Release" in readme
    assert "重启后生效" in readme
