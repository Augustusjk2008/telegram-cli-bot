"""Executable resolution and invocation helpers."""

import os
import shutil
from typing import Optional


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

    dirs: list[str] = []
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


def build_executable_invocation(resolved_path: str) -> list[str]:
    ext = os.path.splitext(resolved_path)[1].lower()
    if os.name == "nt" and ext == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolved_path]
    if os.name == "nt" and ext in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/c", resolved_path]
    return [resolved_path]
