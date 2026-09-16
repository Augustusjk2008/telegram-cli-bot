from pathlib import Path


def test_windows_ps1_entrypoints_keep_utf8_bom_for_powershell_compatibility() -> None:
    for name in ("start.ps1", "install.ps1"):
        assert Path(name).read_bytes().startswith(b"\xef\xbb\xbf")
