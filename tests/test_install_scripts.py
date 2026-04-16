import os
import subprocess
from pathlib import Path

import pytest


WINDOWS_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def _run_install_ps1_command(command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script_path = Path("install.ps1").resolve()
    wrapped = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$env:CLI_BRIDGE_INSTALLER_TEST_SKIP_MAIN = '1'",
            f". '{script_path}'",
            command,
        ]
    )
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=merged_env,
        cwd=Path.cwd(),
    )


def test_install_bat_forwards_arguments_to_install_ps1_and_pauses():
    content = Path("install.bat").read_text(encoding="utf-8")

    assert "install.ps1" in content
    assert "%*" in content
    assert "pause" in content.lower()


def test_install_sh_mentions_apt_node_check_only_and_cli_warning():
    content = Path("install.sh").read_text(encoding="utf-8")

    assert "apt-get" in content
    assert "--check-only" in content
    assert "--non-interactive" in content
    assert "codex" in content
    assert "claude" in content
    assert ".env.example" in content


def test_env_example_preconfigures_default_update_repository():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "APP_UPDATE_REPOSITORY=Augustusjk2008/telegram-cli-bot" in content


def test_env_example_defaults_web_host_to_wildcard():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "WEB_HOST=0.0.0.0" in content
    assert "WEB_HOST=127.0.0.1" not in content


def test_env_example_omits_unused_assistant_mode_settings():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "Assistant Mode Optional" not in content
    assert "ANTHROPIC_API_KEY=" not in content
    assert "ANTHROPIC_MODEL=" not in content
    assert "ANTHROPIC_BASE_URL=" not in content


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_parses_in_windows_powershell():
    script_path = Path("install.ps1").resolve()
    assert script_path.exists(), "install.ps1 应存在"

    command = "\n".join(
        [
            "$errors = $null",
            "$tokens = $null",
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors)",
            "'count=' + $errors.Count",
            "$errors | ForEach-Object { $_.Message }",
        ]
    )

    result = subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert result.returncode == 0
    assert "count=0" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_can_skip_main_for_function_level_tests():
    script_path = Path("install.ps1").resolve()
    assert script_path.exists(), "install.ps1 应存在"

    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$env:CLI_BRIDGE_INSTALLER_TEST_SKIP_MAIN = '1'",
            f". '{script_path}'",
            "'skip-main-ok'",
        ]
    )

    result = subprocess.run(
        [str(WINDOWS_POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "skip-main-ok" in result.stdout


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_install_ps1_check_only_mode_warns_when_no_cli():
    script_path = Path("install.ps1").resolve()
    assert script_path.exists(), "install.ps1 应存在"

    env = os.environ.copy()
    env["CLI_BRIDGE_INSTALLER_TEST_FORCE_NO_CLI"] = "1"

    result = subprocess.run(
        [
            str(WINDOWS_POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-CheckOnly",
            "-NonInteractive",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
        cwd=Path.cwd(),
    )

    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "[警告]" in output
    assert "codex" in output.lower()
    assert "claude" in output.lower()
