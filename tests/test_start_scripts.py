from pathlib import Path


def test_start_bat_forwards_arguments_to_start_ps1():
    content = Path("start.bat").read_text(encoding="utf-8")

    assert "start.ps1" in content
    assert "%*" in content


def test_start_ps1_declares_web_mode_and_sets_web_envs():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("default", "web")' in content
    assert '$env:TELEGRAM_ENABLED = "false"' in content
    assert '$env:WEB_ENABLED = "true"' in content
