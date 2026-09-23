"""Windows path boundaries and executable Windows PowerShell transport contracts."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from bot.remote_workspace import windows
from bot.remote_workspace.transport import RemoteWorkspaceError, _absolute, _inside, join_remote_path


@pytest.mark.parametrize("path, expected", [
    (r"c:\Users\开发者\project", "/C:/Users/开发者/project"),
    ("C:/", "/C:/"), ("/c:", "/C:/"), ("/D:/work/../project", "/D:/project"),
])
def test_windows_drive_paths_are_canonical(path, expected):
    assert _absolute(path, "windows") == expected


@pytest.mark.parametrize("path", [
    "C:relative", r"\\server\share\project", r"\\?\C:\project", "/project",
    "C:/project/file:secret", "C:/project/NUL.txt", "C:/project/COM1",
    "C:/project/file.", "C:/project/dir /file", "C:/project/a\nb", "C:/project/*.py",
])
def test_windows_ambiguous_and_device_paths_are_rejected(path):
    with pytest.raises(RemoteWorkspaceError, match="Windows|UNC"):
        _absolute(path, "windows")


@pytest.mark.parametrize("path", [r"..\secret", r"D:\secret", r"C:\project-other\secret"])
def test_windows_mixed_separators_cannot_escape_workspace(path):
    with pytest.raises(RemoteWorkspaceError) as exc:
        _inside("/C:/project", join_remote_path("/C:/project", path, "windows"))
    assert exc.value.code == "forbidden_path"


@pytest.fixture
def powershell():
    if os.name != "nt":
        pytest.skip("Requires actual Windows PowerShell 5.1")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not executable.is_file():
        pytest.skip("Windows PowerShell is not installed")

    def run(script):
        return subprocess.run(
            [str(executable), *windows.STDIN_COMMAND.split()[1:]],
            input=script.encode("utf-8"), capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    return run


def remote_path(path):
    return "/" + path.as_posix()


def test_powershell_stdin_preserves_long_unicode_batch_and_scope(powershell, tmp_path):
    folder = tmp_path / "项目 ' & $()"
    folder.mkdir()
    command = windows.batch([
        "$answer = '你好'",
        "$long = '" + "x" * 12000 + "'; Write-Output ($answer + ':' + $long.Length)",
        "Write-Output (Get-Location).Path",
    ])
    result = powershell(windows.command_script(command, remote_path(folder)))
    assert result.returncode == 0, result.stderr
    assert "你好:12000" in result.stdout.decode("utf-8")
    assert str(folder) in result.stdout.decode("utf-8")
    assert result.stderr == b""


@pytest.mark.parametrize("name", ["a‘b’c", "x’; Write-Output ORBIT_INJECTED; #"])
def test_windows_path_data_cannot_inject_powershell(powershell, tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    root = remote_path(folder)
    command = windows.terminal_command(root)
    startup = base64.b64decode(command.split()[-1]).decode("utf-16-le")
    result = powershell(startup + "\n[Console]::Write((Get-Location).Path)")
    assert result.returncode == 0 and result.stdout.decode("utf-8") == str(folder)
    result = powershell(windows.file_script([root]))
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""


@pytest.mark.parametrize("command, exit_code", [("cmd.exe /d /c exit 7", 7), ("throw 'failed'", 1)])
def test_powershell_batch_stops_and_propagates_failure(powershell, tmp_path, command, exit_code):
    result = powershell(windows.command_script(windows.batch([command, "Write-Output 'must-not-run'"]), remote_path(tmp_path)))
    assert result.returncode == exit_code
    assert b"must-not-run" not in result.stdout


def test_windows_replace_preserves_bytes_and_conflict_contract(powershell, tmp_path):
    target, staged = tmp_path / "中文 ' file.txt", tmp_path / ".orbit-stage.tmp"
    original = b"\xef\xbb\xbfone\r\ntwo\r\n"
    target.write_bytes(original)
    staged.write_bytes(b"")
    paths = [remote_path(tmp_path), remote_path(target)]
    prepare = powershell(windows.file_script(paths, action="prepare", temporary=remote_path(staged), exists=True))
    assert prepare.returncode == 0, prepare.stderr
    staged.write_bytes(b"new\r\n")
    conflict = powershell(windows.file_script(paths, action="commit", temporary=remote_path(staged), exists=True, version="sha256:" + "0" * 64))
    assert conflict.returncode == 1 and b"ORBIT:file_version_conflict" in conflict.stderr
    assert target.read_bytes() == original and staged.read_bytes() == b"new\r\n"
    saved = powershell(windows.file_script(paths, action="commit", temporary=remote_path(staged), exists=True, version="sha256:" + hashlib.sha256(original).hexdigest()))
    assert saved.returncode == 0, saved.stderr
    assert target.read_bytes() == b"new\r\n" and not staged.exists()
    assert not Path(str(staged) + ".bak").exists()


def test_windows_staging_gets_restricted_target_acl_before_content(powershell, tmp_path):
    target, staged = tmp_path / "restricted.txt", tmp_path / ".orbit-stage.tmp"
    target.write_bytes(b"original")
    staged.touch()
    target_literal, staged_literal = windows.literal(str(target)), windows.literal(str(staged))
    setup = f"""$acl = New-Object Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
$rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
$acl.AddAccessRule($rule)
[IO.File]::SetAccessControl({target_literal}, $acl)
"""
    assert powershell(setup).returncode == 0
    result = powershell(windows.file_script([remote_path(tmp_path), remote_path(target)], action="prepare", temporary=remote_path(staged), exists=True))
    assert result.returncode == 0, result.stderr
    compare = f"""$access = [Security.AccessControl.AccessControlSections]::Access
$original = [IO.File]::GetAccessControl({target_literal}).GetSecurityDescriptorSddlForm($access)
$stage = [IO.File]::GetAccessControl({staged_literal}).GetSecurityDescriptorSddlForm($access)
if ($original -ne $stage) {{ exit 1 }}
"""
    assert powershell(compare).returncode == 0


def test_windows_locked_replace_preserves_original_and_staging(powershell, tmp_path):
    target, staged = tmp_path / "file.txt", tmp_path / ".orbit-stage.tmp"
    target.write_bytes(b"original")
    staged.write_bytes(b"replacement")
    script = "$lock = [IO.File]::Open(" + windows.literal(str(target)) + ", 'Open', 'ReadWrite', 'None')\n"
    script += windows.file_script([remote_path(tmp_path), remote_path(target)], action="commit", temporary=remote_path(staged), exists=True)
    result = powershell(script)
    assert result.returncode == 1 and b"ORBIT:remote_io_error" in result.stderr
    assert target.read_bytes() == b"original" and staged.read_bytes() == b"replacement"


def test_windows_new_file_never_overwrites_and_allows_only_missing_leaf(powershell, tmp_path):
    target, staged = tmp_path / "new.txt", tmp_path / ".orbit-stage.tmp"
    staged.write_bytes(b"new")
    result = powershell(windows.file_script([remote_path(tmp_path), remote_path(target)], missing=True, action="commit", temporary=remote_path(staged)))
    assert result.returncode == 0, result.stderr
    staged.write_bytes(b"other")
    result = powershell(windows.file_script([remote_path(tmp_path), remote_path(target)], missing=True, action="commit", temporary=remote_path(staged)))
    assert result.returncode == 1 and b"ORBIT:path_exists" in result.stderr
    assert target.read_bytes() == b"new"
    result = powershell(windows.file_script([remote_path(tmp_path / "missing" / "file.txt")], missing=True))
    assert result.returncode == 1 and b"ORBIT:path_not_found" in result.stderr


def test_windows_reparse_ancestors_cannot_escape_workspace(powershell, tmp_path):
    outside, link = tmp_path / "outside", tmp_path / "junction"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    setup = powershell("New-Item -ItemType Junction -Path " + windows.literal(str(link)) + " -Target " + windows.literal(str(outside)))
    assert setup.returncode == 0, setup.stderr
    try:
        result = powershell(windows.file_script([remote_path(link / "secret.txt")]))
        assert result.returncode == 1 and b"ORBIT:forbidden_path" in result.stderr
        result = powershell(windows.file_script([remote_path(link)], missing=True))
        assert result.returncode == 1 and b"ORBIT:forbidden_path" in result.stderr
    finally:
        os.rmdir(link)  # Remove only the junction, never its target.
