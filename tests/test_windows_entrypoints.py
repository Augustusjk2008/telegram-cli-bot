import os
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Windows-only launcher tests")


def _copy_entrypoint(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    destination.write_bytes((PROJECT_ROOT / name).read_bytes())
    return destination


def _write_cmd_stub(tmp_path: Path, name: str, content: str) -> Path:
    destination = tmp_path / name
    destination.write_text(content, encoding="ascii", newline="\r\n")
    return destination


def _run_process(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_env_example_is_ascii_only() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_bytes()
    env_example.decode("ascii")


@WINDOWS_ONLY
def test_start_bat_runs_install_when_env_is_missing(tmp_path: Path) -> None:
    _copy_entrypoint(tmp_path, "start.bat")
    _write_cmd_stub(
        tmp_path,
        "install.bat",
        """@echo off
> "%~dp0install.invoked" echo install
(
echo WEB_API_TOKEN=test-token
) > "%~dp0.env"
exit /b 0
""",
    )
    _write_cmd_stub(
        tmp_path,
        "pwsh.cmd",
        """@echo off
> "%~dp0pwsh.invoked" echo %*
exit /b 0
""",
    )

    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    env["CLI_BRIDGE_INSTALLER_NO_PAUSE"] = "1"

    result = _run_process(["cmd.exe", "/c", "start.bat"], cwd=tmp_path, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "install.invoked").exists()
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "pwsh.invoked").exists()


@WINDOWS_ONLY
def test_start_ps1_runs_install_when_env_is_missing(tmp_path: Path) -> None:
    _copy_entrypoint(tmp_path, "start.ps1")
    _write_cmd_stub(
        tmp_path,
        "install.bat",
        """@echo off
> "%~dp0install.invoked" echo install
(
echo WEB_API_TOKEN=test-token
) > "%~dp0.env"
exit /b 0
""",
    )
    _write_cmd_stub(
        tmp_path,
        "python.cmd",
        """@echo off
>> "%~dp0python.invoked" echo %*
exit /b 0
""",
    )

    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    env["CLI_BRIDGE_INSTALLER_NO_PAUSE"] = "1"

    result = _run_process(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(tmp_path / "start.ps1"),
        ],
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "install.invoked").exists()
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "python.invoked").exists()
