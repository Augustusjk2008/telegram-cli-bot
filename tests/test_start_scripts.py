from pathlib import Path


def test_start_bat_prefers_pwsh_and_requests_elevation():
    content = Path("start.bat").read_text(encoding="utf-8").lower()

    assert "start.ps1" in content
    assert "%*" in content
    assert "pwsh" in content
    assert "powershell" in content
    assert "runas" in content


def test_start_sh_runs_python_module_and_sets_supervisor_env():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert "CLI_BRIDGE_SUPERVISOR=1" in content
    assert 'if command -v python3 >/dev/null 2>&1; then' in content
    assert 'elif command -v python >/dev/null 2>&1; then' in content
    assert '"$PYTHON_BIN" -m bot' in content
    assert "set +e" in content
    assert 'if [[ "$exit_code" -ne 75 ]]' in content


def test_start_sh_requires_env_and_applies_pending_updates():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert ".env" in content
    assert "bot.updater" in content
    assert "apply-pending" in content
    assert "WEB_TUNNEL_MODE" in content
    assert "WEB_PUBLIC_URL" in content
    assert "install.sh 或 install.bat" in content


def test_start_sh_drops_sudo_to_original_user():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert "SUDO_USER" in content
    assert "CLI_BRIDGE_ALLOW_ROOT" in content
    assert 'sudo -H -u "$SUDO_USER"' in content
    assert ".npm-global/bin" in content
    assert "dscl" in content
    assert "/opt/homebrew/bin" in content
    assert ".bun/bin" in content


def test_start_ps1_applies_pending_updates_before_boot():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert "bot.updater" in content
    assert "apply-pending" in content
    assert "正在检查并应用待更新版本" in content


def test_start_ps1_reports_update_failure_but_continues_boot():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert "应用待更新版本失败" in content
    assert "继续启动当前程序" in content
    updater_section = content.split('"bot.updater", "apply-pending"', 1)[1].split("Show-TunnelHint", 1)[0]
    assert "exit $LASTEXITCODE" not in updater_section


def test_start_scripts_run_env_migration_before_boot():
    start_ps1 = Path("start.ps1").read_text(encoding="utf-8")
    start_sh = Path("start.sh").read_text(encoding="utf-8")

    assert "bot.env_migration" in start_ps1
    assert "bot.env_migration" in start_sh


def test_install_sh_offers_kimi_choice_but_keeps_codex_default():
    content = Path("install.sh").read_text(encoding="utf-8")

    assert "选择默认 CLI：1) codex" in content
    assert "2) kimi" in content or "3) kimi" in content
    assert "printf 'codex\\n'" in content


def test_install_sh_supports_macos_without_gnu_linux_only_tools():
    content = Path("install.sh").read_text(encoding="utf-8")

    assert "Darwin" in content
    assert "RUNTIME_PLATFORM=\"macos\"" in content
    assert "brew install" in content
    assert "@tailwindcss/oxide-darwin-arm64" in content
    assert "@tailwindcss/oxide-darwin-x64" in content
    assert "dpkg --compare-versions" not in content
    assert "sed -i" not in content
    assert "shasum -a 256" in content
