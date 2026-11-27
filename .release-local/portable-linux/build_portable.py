"""Add the native offline runtimes to a freshly staged Linux x64 release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

from git_runtime import bundle_git_and_libraries, write_script


HERE = Path(__file__).resolve().parent
PYTHON_ARCHIVE = (
    "python-3.12.16-20261124.tar.gz",
    "https://github.com/astral-sh/python-build-standalone/releases/download/20261124/"
    "cpython-3.12.16%2B20261124-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
    "7e1adaea26c959d13aa1120be1ae62a1ea1bb52adcb382679fffe9217e22adff",
)
PYTHON_LICENSES = (
    "python-3.12.16-licenses.tar.zst",
    "https://github.com/astral-sh/python-build-standalone/releases/download/20261124/"
    "cpython-3.12.16%2B20261124-x86_64-unknown-linux-gnu-pgo%2Blto-full.tar.zst",
    "1962e693cb4a5ecbb004e6606cf0d196baa19672f6814586a366faeb8f2fd56c",
)
NODE_ARCHIVE = (
    "node-v22.23.5-linux-x64.tar.xz",
    "https://nodejs.org/dist/v22.23.5/node-v22.23.5-linux-x64.tar.xz",
    "cdeb8670a0c81f51b4dc4ac61919f9b1ad917b304bf8221eb939570663d240f8",
)


def download(cache: Path, spec: tuple[str, str, str]) -> Path:
    name, url, expected = spec
    target = cache / name
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return target
    with tempfile.TemporaryDirectory(dir=cache) as temp:
        partial = Path(temp) / name
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
                        "--output", partial, url], check=True)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch: {name}")
        partial.replace(target)
    return target


def unpack(archive: Path, dest: Path, *excludes: str) -> None:
    dest.mkdir(parents=True)
    subprocess.run(["tar", "-xf", archive, "--strip-components=1", *excludes, "-C", dest], check=True)


def flatten_links(root: Path) -> None:
    # The updater only accepts ordinary files. Resolve upstream aliases before creating the manifest.
    for link in sorted(root.rglob("*")):
        if link.is_symlink():
            target = link.resolve(strict=True)
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError(f"Unexpected runtime link: {link}")
            link.unlink()
            shutil.copy2(target, link)


def build(stage: Path, cache: Path) -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Build this package on x86-64 Linux")
    cache.mkdir(parents=True, exist_ok=True)
    python_root = stage / "runtime/python"
    node_root = stage / "runtime/node"
    # System terminfo is used on Linux. The upstream database has case-only aliases which cannot
    # be represented in the cross-platform update manifest.
    unpack(download(cache, PYTHON_ARCHIVE), python_root, "--exclude=python/share/terminfo")
    subprocess.run(["tar", "--zstd", "-xf", download(cache, PYTHON_LICENSES), "--strip-components=1",
                    "-C", python_root, "python/licenses", "python/PYTHON.json"], check=True)
    python = python_root / "bin/python3"
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([python, "-I", "-B", "-m", "pip", "--disable-pip-version-check", "install",
                    "--only-binary=:all:", "--require-hashes", "--no-compile", "-r", HERE / "requirements.lock"],
                   cwd=stage, env=env, check=True)
    subprocess.run([python, "-I", "-B", "-m", "pip", "check"], cwd=stage, env=env, check=True)
    # pip's console scripts contain the build directory in their shebang. Recreate them relative
    # to the extracted interpreter. Entry-point metadata comes from the just-installed wheels.
    entries = subprocess.check_output([python, "-I", "-B", "-c",
        "import importlib.metadata as m, json; print(json.dumps([(e.name,e.module,e.attr) "
        "for e in m.entry_points(group='console_scripts')]))"], env=env, text=True)
    for name, module, attr in json.loads(entries):
        path = python_root / "bin" / name
        if path.is_file():
            code = f"from {module} import {attr.split('.')[0]}; import sys; sys.exit({attr}())"
            write_script(path, f'exec "$(dirname "$0")/python3" -c {shlex.quote(code)} "$@"')
    for name in ("pip", "pip3", "pip3.12"):
        write_script(python_root / "bin" / name, 'exec "$(dirname "$0")/python3" -m pip "$@"')
    shutil.copy2(python_root / "lib/python3.12/LICENSE.txt", python_root / "LICENSE.txt")
    flatten_links(python_root)
    for folder in list(python_root.rglob("__pycache__")):
        if folder.exists():
            shutil.rmtree(folder)

    unpack(download(cache, NODE_ARCHIVE), node_root)
    for name in ("npm", "npx", "corepack"):
        shim = node_root / "bin" / name
        target = os.path.relpath(shim.resolve(strict=True), shim.parent)
        shim.unlink()
        write_script(shim, f'bin=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$bin/node" "$bin/{target}" "$@"')
    flatten_links(node_root)
    bundle_git_and_libraries(stage)

    (stage / ".env").write_text(
        "CLI_TYPE=codex\nWORKING_DIR=.\nWEB_ENABLED=true\nWEB_HOST=127.0.0.1\nWEB_PORT=8765\n"
        "WEB_TUNNEL_MODE=disabled\nWEB_TUNNEL_AUTOSTART=false\nTELEGRAM_ENABLED=false\n", encoding="utf-8")
    write_script(stage / "install.sh", 'echo "Offline runtimes are included. Run: bash start.sh"')
    (stage / "PORTABLE-README.txt").write_text(
        "Orbit Safe Claw | Linux x86-64 portable (Ubuntu 24.04 / glibc)\n\n"
        "Extract into a writable directory and run: bash start.sh\n"
        "Open http://127.0.0.1:8765 on the same computer. No sudo, pip or npm install is needed.\n"
        "The package includes Python, Node.js, Git and the web UI. Set up your chosen AI CLI separately.\n"
        "Settings and chat data live in data/ and .tcb/ by default. Update from Admin Center.\n",
        encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path)
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    build(args.stage.resolve(), args.cache.resolve())
