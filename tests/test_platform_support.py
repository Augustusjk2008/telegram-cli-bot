from bot.platform import executables, paths, runtime, terminal


def test_get_default_shell_returns_bash_on_linux(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "posix")
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert runtime.get_runtime_platform() == "linux"
    assert runtime.get_default_shell() == "bash"


def test_get_default_shell_returns_powershell_on_windows(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    assert runtime.get_runtime_platform() == "windows"
    assert runtime.get_default_shell() == "powershell"


def test_get_default_shell_returns_macos_user_shell(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "posix")
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setenv("SHELL", "/bin/zsh")

    assert runtime.get_runtime_platform() == "macos"
    assert runtime.get_default_shell() == "/bin/zsh"


def test_get_default_shell_returns_zsh_on_macos_without_shell(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "posix")
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.delenv("SHELL", raising=False)

    assert runtime.get_default_shell() == "/bin/zsh"


def test_build_executable_invocation_wraps_powershell_script_on_windows(monkeypatch):
    monkeypatch.setattr(executables.os, "name", "nt")
    argv = executables.build_executable_invocation(r"C:\tools\codex.ps1")
    assert argv[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]


def test_build_executable_invocation_leaves_linux_binary_unwrapped(monkeypatch):
    monkeypatch.setattr(executables.os, "name", "posix")
    assert executables.build_executable_invocation("/usr/local/bin/codex") == ["/usr/local/bin/codex"]


def test_build_executable_invocation_wraps_non_executable_posix_script(tmp_path, monkeypatch):
    script = tmp_path / "codex"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)
    monkeypatch.setattr(executables.os, "name", "posix")

    assert executables.build_executable_invocation(str(script)) == ["bash", str(script)]


def test_posix_user_bin_dirs_include_homebrew(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/demo")
    monkeypatch.delenv("SUDO_USER", raising=False)

    dirs = executables._iter_posix_user_bin_dirs()

    assert "/opt/homebrew/bin" in dirs
    assert "/usr/local/bin" in dirs


def test_macos_terminal_shell_uses_login_shell_and_shlex(monkeypatch):
    monkeypatch.setattr(terminal.sys, "platform", "darwin")

    assert terminal._build_posix_shell_argv('/bin/zsh -i') == ["/bin/zsh", "-i", "-l"]


def test_linux_terminal_shell_uses_shlex(monkeypatch):
    monkeypatch.setattr(terminal.sys, "platform", "linux")

    assert terminal._build_posix_shell_argv('bash -lc "echo hi"') == ["bash", "-lc", "echo hi"]


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
