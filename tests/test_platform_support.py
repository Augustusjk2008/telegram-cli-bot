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


def test_truncate_path_for_display_handles_unix_paths():
    rendered = paths.truncate_path_for_display("/srv/telegram-cli-bridge/projects/demo-repo", max_len=22)
    assert rendered.endswith("/demo-repo")
    assert "..." in rendered
