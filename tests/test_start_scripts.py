from pathlib import Path


def test_start_bat_prefers_pwsh_and_requests_elevation():
    content = Path("start.bat").read_text(encoding="utf-8").lower()

    assert "start.ps1" in content
    assert "%*" in content
    assert "pwsh" in content
    assert "powershell" in content
    assert "runas" in content


def test_start_bat_uses_ascii_only_messages_for_double_click_cmd():
    raw = Path("start.bat").read_bytes()

    assert all(byte < 128 or byte in (9, 10, 13) for byte in raw)


def test_start_ps1_declares_web_mode_sets_web_envs_and_mentions_tunnel_config():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("default", "web")' in content
    assert '$env:WEB_ENABLED = "true"' in content
    assert "WEB_TUNNEL_MODE" in content
    assert "WEB_PUBLIC_URL" in content
    assert ("TELEGRAM" "_ENABLED") not in content


def test_start_ps1_removes_tray_and_hidden_window_logic():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert "System.Windows.Forms" not in content
    assert "NotifyIcon" not in content
    assert "WindowStyle" not in content
    assert "ShowBalloonTip" not in content
    assert "ContextMenuStrip" not in content


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


def test_start_sh_is_web_only():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert 'export WEB_ENABLED="true"' in content
    assert ("TELEGRAM" "_ENABLED") not in content
