from pathlib import Path
import re


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "empty_recycle_bin.bat"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def test_recycle_bin_clear_failure_is_reported_by_powershell() -> None:
    script = _script_text()

    assert "Clear-RecycleBin -Confirm:$false -ErrorAction Stop" in script
    assert re.search(
        r"try\s*\{.*?Clear-RecycleBin.*?-ErrorAction Stop.*?"
        r"Write-Host 'Recycle Bin emptied'.*?\}\s*catch\s*\{.*?"
        r"\[Console\]::Error\.WriteLine\(.*?\).*?exit 1",
        script,
        re.DOTALL,
    )


def test_recycle_bin_batch_exits_before_done_when_powershell_fails() -> None:
    script = _script_text()

    assert re.search(
        r"powershell .*?\r?\n\s*if errorlevel 1 \(\s*.*?exit /b 1\s*\)"
        r"\s*echo Done",
        script,
        re.DOTALL,
    )
