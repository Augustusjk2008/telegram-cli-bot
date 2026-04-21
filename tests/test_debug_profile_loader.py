from __future__ import annotations

from pathlib import Path

import pytest

from bot.debug.profile_loader import DebugProfileLoadError, load_debug_profile, require_debug_profile


def _write_workspace(root: Path, *, server_address: str = "192.168.1.88:2345", config_name: str = "(gdb) Remote Debug") -> None:
    vscode_dir = root / ".vscode"
    vscode_dir.mkdir(parents=True)
    (root / "debug.ps1").write_text(
        """
param(
    [string]$RemoteHost = "192.168.1.29",
    [string]$RemoteUser = "root",
    [string]$RemoteDir = "/home/sast8/tmp",
    [int]$RemoteGdbPort = 1234
)
""".strip(),
        encoding="utf-8",
    )
    (vscode_dir / "launch.json").write_text(
        f"""
{{
  // comment
  "version": "0.2.0",
  "configurations": [
    {{
      "name": "{config_name}",
      "type": "cppdbg",
      "request": "launch",
      "program": "${{workspaceFolder}}/build/aarch64/Debug/MB_DDF",
      "cwd": "${{workspaceFolder}}",
      "stopAtEntry": true,
      "MIMode": "gdb",
      "miDebuggerPath": "D:\\\\Toolchain\\\\aarch64-none-linux-gnu-gdb.exe",
      "miDebuggerServerAddress": "{server_address}",
      "setupCommands": [
        {{ "text": "-enable-pretty-printing", "ignoreFailures": true }},
        {{ "text": "set pagination off", "ignoreFailures": false }},
        {{ "text": "set sysroot H:\\\\Resources\\\\RTLinux\\\\sysroot" }},
      ],
    }}
  ],
}}
""".strip(),
        encoding="utf-8",
    )
    (vscode_dir / "c_cpp_properties.json").write_text(
        """
{
  "configurations": [
    {
      "name": "Win32",
      "compileCommands": "${workspaceFolder}/.vscode/compile_commands.json"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )


def test_load_debug_profile_resolves_workspace_paths_and_remote_defaults(tmp_path: Path) -> None:
    _write_workspace(tmp_path)

    profile = load_debug_profile(tmp_path)

    assert profile is not None
    assert profile.config_name == "(gdb) Remote Debug"
    assert profile.program == str(tmp_path / "build" / "aarch64" / "Debug" / "MB_DDF")
    assert profile.cwd == str(tmp_path)
    assert profile.mi_debugger_path.endswith("aarch64-none-linux-gnu-gdb.exe")
    assert profile.compile_commands == str(tmp_path / ".vscode" / "compile_commands.json")
    assert profile.prepare_command == r".\debug.bat"
    assert profile.remote_host == "192.168.1.88"
    assert profile.remote_port == 2345
    assert profile.remote_user == "root"
    assert profile.remote_dir == "/home/sast8/tmp"
    assert profile.setup_commands == [
        "-enable-pretty-printing",
        "set pagination off",
        "set sysroot H:\\Resources\\RTLinux\\sysroot",
    ]
    assert profile.setup_command_ignore_failures == [True, False, False]


def test_load_debug_profile_falls_back_to_debug_script_defaults_when_server_address_missing(tmp_path: Path) -> None:
    _write_workspace(tmp_path, server_address="")

    profile = require_debug_profile(tmp_path)

    assert profile.remote_host == "192.168.1.29"
    assert profile.remote_port == 1234


def test_load_debug_profile_returns_none_when_required_files_are_missing(tmp_path: Path) -> None:
    assert load_debug_profile(tmp_path) is None


def test_require_debug_profile_raises_when_target_launch_config_missing(tmp_path: Path) -> None:
    _write_workspace(tmp_path, config_name="Other Config")

    with pytest.raises(DebugProfileLoadError) as exc_info:
        require_debug_profile(tmp_path)

    assert exc_info.value.code == "launch_config_missing"
