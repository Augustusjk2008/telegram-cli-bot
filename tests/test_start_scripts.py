from pathlib import Path


def test_start_bat_delegates_to_start_ps1_with_args():
    content = Path("start.bat").read_text(encoding="utf-8").lower()

    assert "start.ps1" in content
    assert "%*" in content
    assert "pwsh" in content


def test_start_sh_runs_update_and_env_migration_before_bot_loop():
    content = Path("start.sh").read_text(encoding="utf-8")

    env_migration_index = content.index("bot.env_migration")
    update_index = content.index("bot.updater")
    boot_index = content.index('\n  "$PYTHON_BIN" -m bot\n')

    assert env_migration_index < update_index < boot_index


def test_start_ps1_applies_update_and_env_migration_before_boot():
    content = Path("start.ps1").read_text(encoding="utf-8")

    env_migration_index = content.index("bot.env_migration")
    update_index = content.index("bot.updater")
    boot_index = content.index('@("-m", "bot")')

    assert env_migration_index < update_index < boot_index


def test_start_ps1_reports_update_failure_but_continues_boot():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert "应用待更新版本失败" in content
    assert "继续启动当前程序" in content
    updater_section = content.split('"bot.updater", "apply-pending"', 1)[1].split("Show-TunnelHint", 1)[0]
    assert "exit $LASTEXITCODE" not in updater_section
