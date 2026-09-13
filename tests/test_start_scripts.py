from pathlib import Path


def test_start_ps1_keeps_utf8_bom_for_windows_powershell_compatibility() -> None:
    assert Path("start.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
def test_install_ps1_node_fallback_matches_required_minimum_version() -> None:
    """Node 回退下载线必须与 MinimumVersion 一致（v20 下载 + >=22 校验曾在无 winget 时必败）。"""
    content = Path("install.ps1").read_text(encoding="utf-8")

    assert "latest-v20" not in content
    assert content.count("latest-v22.x") == 2  # SHASUMS 与安装包 URL
    assert 'MinimumVersion "22.0.0"' in content


def test_start_scripts_guard_python_version_consistently() -> None:
    """start.ps1/start.sh 与 install 脚本、README 的 Python 支持区间必须一致（3.10-3.13）。"""
    powershell = Path("start.ps1").read_text(encoding="utf-8")
    shell = Path("start.sh").read_text(encoding="utf-8")
    install_ps1 = Path("install.ps1").read_text(encoding="utf-8")
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    # start.ps1：候选必须过版本校验，且优先 py -3.12（与 install.ps1 一致）
    assert "Test-PythonVersionSupported" in powershell
    assert 'Arguments @("-3.12")' in powershell
    assert powershell.count('[Version]"3.10.0"') >= 1 and powershell.count('[Version]"3.14.0"') >= 1

    # start.sh：解释器选中后必须有 3.10-3.13 护栏
    assert "python_version_supported" in shell
    assert "ensure_python_version_supported" in shell

    for text in (install_ps1, install_sh, readme):
        assert "3.10" in text and "3.14" in text


