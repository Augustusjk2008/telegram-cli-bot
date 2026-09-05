from pathlib import Path


def test_start_ps1_keeps_utf8_bom_for_windows_powershell_compatibility() -> None:
    assert Path("start.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
