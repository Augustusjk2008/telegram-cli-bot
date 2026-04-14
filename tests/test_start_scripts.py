from pathlib import Path


def test_start_bat_forwards_arguments_to_start_ps1():
    content = Path("start.bat").read_text(encoding="utf-8")

    assert "start.ps1" in content
    assert "%*" in content


def test_start_ps1_declares_web_mode_and_sets_web_envs():
    content = Path("start.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("default", "web")' in content
    assert '$env:WEB_ENABLED = "true"' in content
    assert ("TELEGRAM" "_ENABLED") not in content


def test_start_sh_runs_python_module_and_sets_supervisor_env():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert "CLI_BRIDGE_SUPERVISOR=1" in content
    assert 'if command -v python3 >/dev/null 2>&1; then' in content
    assert 'elif command -v python >/dev/null 2>&1; then' in content
    assert '"$PYTHON_BIN" -m bot' in content
    assert "set +e" in content
    assert 'if [[ "$exit_code" -ne 75 ]]' in content


def test_start_sh_is_web_only():
    content = Path("start.sh").read_text(encoding="utf-8")

    assert 'export WEB_ENABLED="true"' in content
    assert ("TELEGRAM" "_ENABLED") not in content
