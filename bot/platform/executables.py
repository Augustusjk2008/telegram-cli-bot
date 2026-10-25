"""Executable resolution and invocation helpers."""

import os
import shutil
import stat
from typing import Optional


_WINDOWS_DSH_CLI_RELATIVE = os.path.join("resources", "runtime", "cli", "bin", "dsh.cmd")


def resolve_cli_executable(cli_path: str, working_dir: Optional[str] = None) -> Optional[str]:
    path = (cli_path or "").strip().strip('"').strip("'")
    if not path:
        return None

    def _existing_file(candidate: str) -> Optional[str]:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
        return None

    if os.path.isabs(path):
        found = _existing_file(path)
        if found:
            return found

    if any(sep in path for sep in ("/", "\\")):
        candidates = []
        if working_dir:
            candidates.append(os.path.join(working_dir, path))
        candidates.append(path)
        for candidate in candidates:
            found = _existing_file(os.path.abspath(os.path.expanduser(candidate)))
            if found:
                return found

    found = shutil.which(path)
    if found:
        return found

    if os.name != "nt" and not any(sep in path for sep in ("/", "\\")):
        for bin_dir in _iter_posix_user_bin_dirs():
            found = _existing_file(os.path.join(bin_dir, path))
            if found:
                return found

    if os.name == "nt" and not os.path.splitext(path)[1]:
        for ext in (".cmd", ".bat", ".exe", ".com"):
            found = shutil.which(path + ext)
            if found:
                return found

    if os.name == "nt" and not any(sep in path for sep in ("/", "\\")):
        appdata = os.getenv("APPDATA")
        userprofile = os.getenv("USERPROFILE")
        npm_dirs: list[str] = []
        if appdata:
            npm_dirs.append(os.path.join(appdata, "npm"))
        if userprofile:
            npm_dirs.append(os.path.join(userprofile, "AppData", "Roaming", "npm"))

        seen: set[str] = set()
        npm_dirs = [item for item in npm_dirs if not (item in seen or seen.add(item))]

        if os.path.splitext(path)[1]:
            names = [path]
        else:
            names = [path + ext for ext in (".cmd", ".bat", ".exe", ".com", ".ps1")]

        for npm_dir in npm_dirs:
            for name in names:
                found = _existing_file(os.path.join(npm_dir, name))
                if found:
                    return found

        if path.lower() == "agy":
            local_app_data = os.getenv("LOCALAPPDATA")
            if local_app_data:
                found = _existing_file(os.path.join(local_app_data, "agy", "bin", "agy.exe"))
                if found:
                    return found

        if path.lower() == "dsh":
            for candidate in _iter_windows_dsh_candidates():
                found = _existing_file(candidate)
                if found:
                    return found

    return None


def _get_home_for_user(username: str) -> Optional[str]:
    if not username:
        return None
    try:
        import pwd

        return pwd.getpwnam(username).pw_dir
    except (ImportError, KeyError, OSError):
        candidate = os.path.join("/home", username)
        if os.path.isdir(candidate):
            return candidate
    return None


def _iter_posix_user_bin_dirs() -> list[str]:
    homes: list[str] = []
    current_home = os.path.expanduser("~")
    if current_home and current_home != "~":
        homes.append(current_home)

    sudo_user = os.environ.get("SUDO_USER", "").strip()
    if sudo_user and sudo_user != "root":
        sudo_home = _get_home_for_user(sudo_user)
        if sudo_home:
            homes.append(sudo_home)

    dirs: list[str] = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    for home in homes:
        dirs.extend(
            [
                os.path.join(home, ".local", "bin"),
                os.path.join(home, ".npm-global", "bin"),
                os.path.join(home, ".cargo", "bin"),
                os.path.join(home, ".bun", "bin"),
            ]
        )
        nvm_root = os.path.join(home, ".nvm", "versions", "node")
        try:
            node_versions = sorted(os.listdir(nvm_root), reverse=True)
        except OSError:
            node_versions = []
        dirs.extend(os.path.join(nvm_root, version, "bin") for version in node_versions)

    seen: set[str] = set()
    return [item for item in dirs if item and not (item in seen or seen.add(item))]


def _iter_windows_dsh_candidates() -> list[str]:
    """Return Desktop-installed dsh wrappers after PATH/npm resolution."""
    roots: list[str] = []
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots.extend(
            os.path.join(local_app_data, "Programs", name)
            for name in ("DeepSeek Harness", "dsh")
        )
        roots.extend(
            os.path.join(local_app_data, name)
            for name in ("DeepSeek Harness", "dsh")
        )

    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg is not None:
        registry_paths = (
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        )
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for registry_path in registry_paths:
                try:
                    with winreg.OpenKey(hive, registry_path) as uninstall_key:
                        index = 0
                        while True:
                            try:
                                subkey_name = winreg.EnumKey(uninstall_key, index)
                            except OSError:
                                break
                            index += 1
                            try:
                                with winreg.OpenKey(uninstall_key, subkey_name) as entry:
                                    display_name = str(winreg.QueryValueEx(entry, "DisplayName")[0] or "")
                                    install_location = str(
                                        winreg.QueryValueEx(entry, "InstallLocation")[0] or ""
                                    ).strip().strip('"')
                            except OSError:
                                continue
                            if install_location and (
                                "deepseek harness" in display_name.lower()
                                or display_name.strip().lower() == "dsh"
                            ):
                                roots.append(install_location)
                except OSError:
                    continue

    candidates = [os.path.join(root, _WINDOWS_DSH_CLI_RELATIVE) for root in roots if root]
    seen: set[str] = set()
    return [item for item in candidates if not (item.casefold() in seen or seen.add(item.casefold()))]


def build_executable_invocation(resolved_path: str) -> list[str]:
    ext = os.path.splitext(resolved_path)[1].lower()
    if os.name == "nt" and ext == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolved_path]
    if os.name == "nt" and ext in {".cmd", ".bat"}:
        # The @ prefix keeps cmd /c from stripping quotes around the batch path.
        return ["cmd.exe", "/d", "/c", "@", resolved_path]
    if os.name != "nt" and not _has_posix_execute_bit(resolved_path):
        return ["bash", resolved_path]
    return [resolved_path]


def _has_posix_execute_bit(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return True
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
