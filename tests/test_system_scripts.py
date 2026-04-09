import subprocess
from pathlib import Path

import pytest


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
