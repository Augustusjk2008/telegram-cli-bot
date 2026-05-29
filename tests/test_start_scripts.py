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
    runtime_migration_index = content.index("bot.migrations run")
    boot_index = content.index('\n  "$PYTHON_BIN" -m bot\n')

    assert env_migration_index < update_index < runtime_migration_index < boot_index


def test_start_ps1_applies_update_and_env_migration_before_boot():
    content = Path("start.ps1").read_text(encoding="utf-8")

    env_migration_index = content.index("bot.env_migration")
    update_index = content.index("bot.updater")
    runtime_migration_index = content.index('"bot.migrations", "run"')
    boot_index = content.index('@("-m", "bot")')

    assert env_migration_index < update_index < runtime_migration_index < boot_index


def test_start_ps1_reports_update_failure_but_continues_boot():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert "应用待更新版本失败" in content
    assert "继续启动当前程序" in content
    updater_section = content.split('"bot.updater", "apply-pending"', 1)[1].split("正在迁移运行数据", 1)[0]
    assert "exit $LASTEXITCODE" not in updater_section


def test_python_module_entry_runs_runtime_migration_before_importing_main():
    content = Path("bot/__main__.py").read_text(encoding="utf-8")

    migration_index = content.index("run_pending_migrations")
    main_import_index = content.index("from bot.main import main")

    assert migration_index < main_import_index


def test_install_sh_initializes_invites_in_runtime_data_dir():
    content = Path("install.sh").read_text(encoding="utf-8")

    install_section = content.split("initialize_register_code()", 1)[1].split("install_example_plugins()", 1)[0]

    assert "from bot.runtime_paths import" in install_section
    assert "get_auth_accounts_dir" in install_section
    assert "get_auth_register_codes_path" in install_section
    assert "get_auth_secret_path" in install_section
    assert 'CLI_BRIDGE_USERS_PATH="$SCRIPT_DIR/.web_users.json"' not in install_section
    assert 'CLI_BRIDGE_REGISTER_CODES_PATH="$SCRIPT_DIR/.web_register_codes.json"' not in install_section
    assert 'CLI_BRIDGE_AUTH_SECRET_PATH="$SCRIPT_DIR/.web_auth_secret.json"' not in install_section


def test_install_ps1_initializes_invites_in_runtime_data_dir():
    content = Path("install.ps1").read_text(encoding="utf-8")

    install_section = content.split("function Initialize-WebRegisterCode", 1)[1].split(
        "function Resolve-ExamplePluginInstallMode",
        1,
    )[0]

    assert "from bot.runtime_paths import" in install_section
    assert "get_auth_accounts_dir" in install_section
    assert "get_auth_register_codes_path" in install_section
    assert "get_auth_secret_path" in install_section
    assert 'Join-Path $script:RootDir ".web_users.json"' not in install_section
    assert 'Join-Path $script:RootDir ".web_register_codes.json"' not in install_section
    assert 'Join-Path $script:RootDir ".web_auth_secret.json"' not in install_section
