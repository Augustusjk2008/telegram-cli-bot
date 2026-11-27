"""Exercise an extracted, verified release without starting a service or opening a port."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def smoke(root: Path, work: Path) -> None:
    home = work / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
           "TCB_PORTABLE_SMOKE_IMPORT_ONLY": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PIP_NO_INDEX": "1", "npm_config_offline": "true", "GIT_CONFIG_NOSYSTEM": "1"}
    def run(*args, **kwargs):
        return subprocess.run(args, cwd=root, env=env, check=True, **kwargs)

    run("bash", "start.sh")
    info = json.loads((root / ".tcb/startup/update-launcher.json").read_text())
    control = Path(info["control_python_executable"]).resolve()
    if control.is_relative_to(root) or not Path(info["state_file"]).is_relative_to(root / "data"):
        raise RuntimeError("Unexpected recovery interpreter or portable data location")
    run(control, "-I", "-S", "-c", "import json, ssl, sqlite3, sys; assert sys.prefix == sys.argv[1]", str(control.parent.parent))
    run(root / "runtime/python/bin/python3", "-B", "-c", """
from pathlib import Path
import json, aiohttp, dotenv, paramiko, pypdf, psutil, qrcode
from bot.updater import detect_update_package_kind
from bot.update_preparation import _prepare_python
root = Path.cwd()
manifest = json.loads((root / '.update-manifest.json').read_text())
assert detect_update_package_kind(root) == manifest['package_kind'] == 'linux-portable'
assert manifest['frontend']['files']['front/dist/index.html']
prepared = dict(package_kind='linux-portable', staging_dir=str(root), manifest=manifest)
result = _prepare_python(root, root, prepared, root / '.tcb/smoke-environment.log')
assert result['python_executable'] == str(root / 'runtime/python/bin/python3')
""")
    run(root / "runtime/node/bin/node", "--version")
    run(root / "runtime/node/bin/npm", "--version")
    git = root / "tools/git/bin/git"
    run(git, "--version")
    run(git, "init", "-q", work / "repo")
    run(git, "-C", work / "repo", "-c", "user.name=Offline", "-c", "user.email=offline@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "offline")
    run(git, "clone", "-q", "--no-local", work / "repo", work / "clone")
    run(git, "remote-https", "origin", "https://example.invalid/", input=b"capabilities\n\n", stdout=subprocess.PIPE)
    print("Offline launcher, control Python, dependencies, frontend, Node/npm and Git passed.", flush=True)


if __name__ == "__main__":
    source = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="orbit-linux-smoke-") as temp:
        work = Path(temp)
        if source.is_dir():
            root = source
        else:
            root = work / "relocated installation"
            root.mkdir()
            subprocess.run(["tar", "-xzf", source, "-C", root], check=True)
        smoke(root, work)
