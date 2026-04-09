import os
import subprocess
from pathlib import Path

import pytest


WINDOWS_CMD = Path(os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe"))
WINDOWS_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


@pytest.mark.skipif(not WINDOWS_POWERSHELL.exists(), reason="Windows PowerShell 5.1 不可用")
def test_turn_off_monitor_script_parses_in_windows_powershell():
    script_path = Path("scripts/turn_off_monitor.ps1").resolve()
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


@pytest.mark.skipif(not WINDOWS_CMD.exists(), reason="cmd.exe 不可用")
def test_codex_switch_source_script_swaps_files_in_temporary_userprofile(tmp_path):
    script_path = Path("scripts/codex_switch_source.bat").resolve()
    userprofile = tmp_path / "user"
    codex_dir = userprofile / ".codex"
    backup_dir = codex_dir / "backup"
    backup_dir.mkdir(parents=True)

    current_auth = '{"active":"main"}\n'
    backup_auth = '{"active":"backup"}\n'
    current_config = 'mode = "main"\n'
    backup_config = 'mode = "backup"\n'

    (codex_dir / "auth.json").write_text(current_auth, encoding="utf-8")
    (backup_dir / "auth.json").write_text(backup_auth, encoding="utf-8")
    (codex_dir / "config.toml").write_text(current_config, encoding="utf-8")
    (backup_dir / "config.toml").write_text(backup_config, encoding="utf-8")

    env = os.environ.copy()
    env["USERPROFILE"] = str(userprofile)

    result = subprocess.run(
        [str(WINDOWS_CMD), "/c", str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "auth.json").read_text(encoding="utf-8") == backup_auth
    assert (backup_dir / "auth.json").read_text(encoding="utf-8") == current_auth
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == backup_config
    assert (backup_dir / "config.toml").read_text(encoding="utf-8") == current_config
