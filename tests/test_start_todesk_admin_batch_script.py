from pathlib import Path


SCRIPT_PATH = Path("scripts/start_todesk_admin.bat")


def _script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_todesk_admin_batch_uses_verified_environment_candidates_and_accurate_copy() -> None:
    content = _script()

    assert "without user confirmation" not in content.casefold()
    assert "started successfully" not in content.casefold()
    assert "可能会显示 UAC" in content
    assert "管理员启动请求已提交" in content
    assert "C:\\Program Files\\ToDesk\\ToDesk.exe" not in content
    assert "$env:ProgramFiles" in content
    assert "[Environment]::GetEnvironmentVariable('ProgramFiles(x86)')" in content
    assert "$env:LOCALAPPDATA" in content
    assert "Join-Path -Path $_ -ChildPath 'ToDesk\\ToDesk.exe'" in content
    assert "Test-Path -LiteralPath $_ -PathType Leaf" in content


def test_todesk_admin_batch_reports_and_propagates_launch_failures() -> None:
    content = _script()

    assert "if (-not $toDesk)" in content
    assert "try { Start-Process" in content
    assert "-Verb RunAs" in content
    assert "-ErrorAction Stop" in content
    assert "catch {" in content
    assert content.count("exit 1") >= 2
    assert 'set "EXIT_CODE=%ERRORLEVEL%"' in content
    assert 'if not "%EXIT_CODE%"=="0" exit /b %EXIT_CODE%' in content
    assert "echo Done" not in content
