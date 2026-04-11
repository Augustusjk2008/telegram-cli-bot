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


def build_executable_invocation(resolved_path: str) -> list[str]:
    ext = os.path.splitext(resolved_path)[1].lower()
    if os.name == "nt" and ext == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolved_path]
    if os.name == "nt" and ext in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/c", resolved_path]
    return [resolved_path]
