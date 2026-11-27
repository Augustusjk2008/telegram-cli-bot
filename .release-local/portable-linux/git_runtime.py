"""Package the build distribution's Git, its helpers, native libraries and notices."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from urllib.parse import quote


def output(*command: str | Path) -> str:
    return subprocess.check_output(command, text=True).strip()


def package_owner(path: Path) -> str:
    # Debian's merged /usr can differ from the paths in an older dpkg database.
    resolved = str(path.resolve())
    for name in dict.fromkeys([resolved, resolved.removeprefix("/usr")]):
        query = subprocess.run(["dpkg-query", "-S", name], capture_output=True, text=True)
        if query.returncode == 0:
            return query.stdout.splitlines()[0].split(": ", 1)[0].split(":")[0]
    raise RuntimeError(f"No distribution package owns {path}")


def write_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nset -eu\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def is_elf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"\x7fELF"


def bundle_git_and_libraries(stage: Path) -> None:
    git = Path(shutil.which("git") or "/usr/bin/git").resolve(strict=True)
    source = Path(output(git, "--exec-path"))
    root = stage / "tools/git"
    helpers = root / "libexec/git-core"
    helpers.mkdir(parents=True)
    native = [stage / "runtime/node/bin/node", helpers / "git"]
    shutil.copy2(git, helpers / "git")
    for path in sorted(source.iterdir()):
        target = helpers / path.name
        if path.name == "git":
            continue
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.samefile(source / "git") and path.name.startswith("git-"):
            write_script(target, f'exec "$(dirname "$0")/git" {path.name[4:]} "$@"')
        else:
            shutil.copy2(path, target)
            if is_elf(target):
                native.append(target)

    templates = source.parent.parent / "share/git-core/templates"
    shutil.copytree(templates, root / "share/templates")
    write_script(root / "bin/git", '''root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export GIT_EXEC_PATH="${GIT_EXEC_PATH:-$root/libexec/git-core}"
export GIT_TEMPLATE_DIR="${GIT_TEMPLATE_DIR:-$root/share/templates}"
exec "$root/libexec/git-core/git" "$@"''')
    for subcommand in ("upload-pack", "receive-pack", "upload-archive"):
        write_script(root / f"bin/git-{subcommand}", f'exec "$(dirname "$0")/git" {subcommand} "$@"')

    # Bundle non-glibc dependencies without putting private libraries on the host's LD_LIBRARY_PATH.
    libs = stage / "runtime/linux-libs"
    libs.mkdir()
    owners = {package_owner(git)}
    dependencies = {}
    for binary in native:
        listing = output("ldd", binary)
        if "not found" in listing:
            raise RuntimeError(f"Unresolved library for {binary}: {listing}")
        for name, filename in re.findall(r"^\s*(\S+) => (/\S+)", listing, re.MULTILINE):
            dependencies[name] = Path(filename)
    for name, path in sorted(dependencies.items()):
        package = package_owner(path)
        if package == "libc6":
            continue
        owners.add(package)
        target = libs / name
        shutil.copy2(path, target)
        native.append(target)
    for binary in native:
        relative = os.path.relpath(libs, binary.parent)
        rpath = "$ORIGIN" if relative == "." else f"$ORIGIN/{relative}"
        subprocess.run(["patchelf", "--set-rpath", rpath, binary], check=True)

    notices = root / "licenses"
    notices.mkdir()
    records = []
    distro = platform.freedesktop_os_release()["ID"]
    for package in sorted(owners):
        notice = Path("/usr/share/doc") / package / "copyright"
        shutil.copy2(notice, notices / f"{package}.txt")
        binary, version, src, revision = output("dpkg-query", "-W",
            "-f=${binary:Package} ${Version} ${source:Package} ${source:Version}", package).split()
        url = f"https://sources.debian.org/src/{src}/{quote(revision)}/"
        if distro == "ubuntu":
            url = f"https://launchpad.net/ubuntu/+source/{src}/{quote(revision)}"
            if src == "git" and "ppa" in revision:
                url = "https://launchpad.net/~git-core/+archive/ubuntu/ppa/+packages?field.name_filter=git"
        records.append(f"{binary} {version} (source: {src} {revision}) {url}")
    shutil.copy2(Path("/usr/share/doc") / package_owner(git) / "copyright", root / "LICENSE.txt")
    shutil.copytree("/usr/share/common-licenses", notices / "common-licenses")
    (notices / "packages.txt").write_text("\n".join(records) + "\n", encoding="utf-8")
