from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def test_disk_space_reports_used_percentage_with_zero_size_guard() -> None:
    script = (SCRIPTS_DIR / "disk_space.bat").read_text(encoding="utf-8")

    assert "if ($_.Size -gt 0)" in script
    assert "(($_.Size - $_.FreeSpace) / $_.Size) * 100" in script
    assert "'  Total: ' + $size + ' GB'" in script
    assert "'  Used:  ' + $used + ' GB (' + $pct + '%%)'" in script
    assert "'  Free:  ' + $free + ' GB'" in script
    assert "'  Free:  ' + $free + ' GB (' + $pct + '%%)'" not in script


def test_processes_uses_operating_system_memory_not_working_set_sum() -> None:
    script = (SCRIPTS_DIR / "get_processes.bat").read_text(encoding="utf-8")

    assert "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20" in script
    assert "Get-WmiObject -Class Win32_OperatingSystem" in script
    assert "$total = $os.TotalVisibleMemorySize / 1KB" in script
    assert "($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1KB" in script
    assert "' MB, Used: ' + ([math]::Round($used, 0)) + ' MB'" in script
    assert "Measure-Object WorkingSet64 -Sum" not in script
