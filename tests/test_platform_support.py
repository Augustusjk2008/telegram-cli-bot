from bot.platform import executables, paths, runtime


def test_get_default_shell_returns_bash_on_linux(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "posix")
    assert runtime.get_runtime_platform() == "linux"
    assert runtime.get_default_shell() == "bash"


def test_get_default_shell_returns_powershell_on_windows(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    assert runtime.get_runtime_platform() == "windows"
    assert runtime.get_default_shell() == "powershell"


def test_build_executable_invocation_wraps_powershell_script_on_windows(monkeypatch):
    monkeypatch.setattr(executables.os, "name", "nt")
    argv = executables.build_executable_invocation(r"C:\tools\codex.ps1")
    assert argv[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]


def test_build_executable_invocation_leaves_linux_binary_unwrapped(monkeypatch):
    monkeypatch.setattr(executables.os, "name", "posix")
    assert executables.build_executable_invocation("/usr/local/bin/codex") == ["/usr/local/bin/codex"]


def test_resolve_cli_executable_checks_sudo_user_npm_global_bin(tmp_path, monkeypatch):
    fake_home = tmp_path / "user-home"
    npm_bin = fake_home / ".npm-global" / "bin"
    npm_bin.mkdir(parents=True)
    codex = npm_bin / "codex"
    codex.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(executables.os, "name", "posix")
    monkeypatch.setattr(executables.shutil, "which", lambda value: None)
    monkeypatch.setenv("HOME", str(tmp_path / "current-home"))
    monkeypatch.setenv("SUDO_USER", "jiangkai")
    monkeypatch.setattr(executables, "_get_home_for_user", lambda username: str(fake_home))

    assert executables.resolve_cli_executable("codex") == str(codex)


def test_truncate_path_for_display_handles_unix_paths():
    rendered = paths.truncate_path_for_display("/srv/telegram-cli-bridge/projects/demo-repo", max_len=22)
    assert rendered.endswith("/demo-repo")
    assert "..." in rendered
