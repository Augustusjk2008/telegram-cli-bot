"""First upgrade from a legacy installation, using only code from a verified new package.

Run this script from the new release with --package, --sha256, --repo-root and
--work-dir (outside the installation). Preparation is the default; --apply requires
--host-stopped and a --health-url for the actual local listener.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import tempfile
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import socket
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def format_command(arguments: list[str]) -> str:
    if os.name == "nt":
        return "& " + " ".join("'" + value.replace("'", "''") + "'" for value in arguments)
    return shlex.join(arguments)


def _verified_validator(package: Path, expected_hash: str):
    """Load only the validator from the checksum-authenticated new full release."""
    if not expected_hash or digest(package).lower() != expected_hash.lower():
        raise RuntimeError("Full release SHA-256 does not match")
    wanted = "scripts/update_package.py"
    candidates = []

    def is_validator(raw):
        name = raw.replace("\\", "/")
        while name.startswith("./"):
            name = name[2:]
        return name == wanted

    if package.name.lower().endswith(".zip"):
        with zipfile.ZipFile(package) as archive:
            for member in archive.infolist():
                if is_validator(member.filename) and not member.is_dir():
                    if stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG):
                        raise RuntimeError("Release validator must be a regular file")
                    if member.file_size > 2 * 1024**2:
                        raise RuntimeError("Release validator is too large")
                    candidates.append(archive.read(member))
    elif package.name.lower().endswith((".tar.gz", ".tgz")):
        with tarfile.open(package, "r:gz") as archive:
            for member in archive:
                if is_validator(member.name) and member.isfile():
                    if member.size > 2 * 1024**2:
                        raise RuntimeError("Release validator is too large")
                    with archive.extractfile(member) as handle:
                        candidates.append(handle.read())
    if len(candidates) != 1:
        raise RuntimeError("Full release must contain exactly one scripts/update_package.py")
    if digest(package).lower() != expected_hash.lower():
        raise RuntimeError("Full release changed while reading the validator")
    # No archive path is extracted before the shared validator has checked it.
    with tempfile.TemporaryDirectory(prefix="orbit-update-validator-") as directory:
        path = Path(directory) / "update_package.py"
        path.write_bytes(candidates[0])
        spec = importlib.util.spec_from_file_location("bootstrap_update_package", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def extract_verified(package: Path, destination: Path, expected_hash: str) -> Path:
    validator = _verified_validator(package, expected_hash)
    manifest = validator.inspect_package(package, staging_dir=destination)
    required = {"scripts/update_runner.py", "scripts/update_transaction.py", "scripts/update_bootstrap.py",
                "scripts/update_package.py", "bot/update_state.py", "bot/update_preparation.py", "bot/updater.py", "VERSION"}
    if not required.issubset(manifest["files"]):
        raise RuntimeError("Full release is missing the new recovery implementation")
    if digest(package).lower() != expected_hash.lower():
        raise RuntimeError("Full release changed during extraction")
    return destination


def establish_baseline(repo: Path, package: Path, expected_hash: str, workspace: Path) -> None:
    from scripts.update_package import create_baseline
    if (repo / ".update-baseline.json").exists():
        raise RuntimeError("An ownership baseline already exists")
    # The shared validator derives hashes exclusively from the verified old release.
    # Local changes remain visible to ownership_plan when preparing the target.
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="baseline-", dir=workspace) as directory:
        verified = Path(directory) / package.name
        shutil.copyfile(package, verified)
        if not expected_hash or digest(verified).lower() != expected_hash.lower():
            raise RuntimeError("Baseline release SHA-256 does not match")
        create_baseline(repo, verified)


def _require_stopped(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    addresses = {"127.0.0.1", "localhost", "::1"}
    addresses.update(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None))
    if parsed.scheme != "http" or parsed.hostname not in addresses:
        raise RuntimeError("Bootstrap health URL must be a local HTTP address")
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2):
            pass
    except urllib.error.HTTPError:
        raise RuntimeError("A service still responds at the local health address") from None
    except urllib.error.URLError:
        return
    raise RuntimeError("Exit the old host before applying the first upgrade")


def prepare_new(args, release: Path) -> int:
    # This mode runs exclusively with the verified full release at sys.path[0].
    sys.path.insert(0, str(release))
    from dotenv import dotenv_values
    for name, value in dotenv_values(args.repo_root / ".env").items():
        if value is not None:
            os.environ.setdefault(name, value)
    if json.loads((release / ".update-manifest.json").read_text(encoding="utf-8-sig")).get("package_kind") == "portable":
        root = args.repo_root
        os.environ.update(WEB_ENABLED="true", PYTHONUTF8="1", PYTHONNOUSERSITE="1",
                          TCB_DATA_DIR=str(root / "data/orbit-safe-claw"),
                          PI_AGENT_SETTINGS=str(root / "data/pi-home/.pi/agent/settings.json"),
                          PI_AGENT_MODELS=str(root / "data/pi-home/.pi/agent/models.json"),
                          NATIVE_AGENT_PI_HOME=str(root / "data/pi-home"), NATIVE_AGENT_ENABLED="true",
                          NATIVE_AGENT_PI_COMMAND=str(root / "tools/pi/pi.cmd"),
                          NATIVE_AGENT_COMMAND=str(root / "tools/pi/pi.cmd"),
                          TCB_CLUSTER_MCP_CONFIG=str(root / ".tcb/cluster-mcp/config.json"))
        entries = [root / name for name in ("runtime/node", "tools/pi", "tools/pi/node_modules/.bin",
                                            "tools/git/cmd", "tools/git/bin", "tools/git/usr/bin", "tools/git/mingw64/bin")]
        os.environ["PATH"] = os.pathsep.join([*(str(path) for path in entries), os.environ.get("PATH", "")])
    from bot.update_state import UpdateStore
    from bot.updater import prepare_update_payload
    from bot.update_preparation import prepare_runtime
    from bot.update_migration_gate import validate_update_migrations
    from scripts import update_runner
    store = UpdateStore(args.repo_root)
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    job_dir.mkdir(parents=True)
    if not (args.repo_root / ".update-manifest.json").is_file() and not (args.repo_root / ".update-baseline.json").is_file():
        if args.baseline_package:
            establish_baseline(args.repo_root, args.baseline_package, args.baseline_sha256, args.work_dir)
        elif not (args.repo_root / ".git").exists():
            raise RuntimeError("Legacy archive installations require --baseline-package and --baseline-sha256 for the installed release")
    prepared = prepare_update_payload(args.repo_root, args.package, job_dir)
    validate_update_migrations(args.repo_root, prepared)
    # Freeze the new runner, never the old installation's apply implementation.
    # Keep the verified release as code source while retaining the installation's
    # identity and external-control-interpreter boundary.
    prepared["runner_source_root"] = str(release)
    runtime = prepare_runtime(args.repo_root, job_dir, prepared)
    candidates = [args.repo_root / ".venv/Scripts/python.exe", args.repo_root / ".venv/bin/python"]
    source_python = next((str(path) for path in candidates if path.is_file()), sys.executable)
    previous = args.previous_python or str(args.repo_root / "runtime/python/python.exe" if prepared["package_kind"] == "portable" else source_python)
    job = {**prepared, **runtime}
    job.update(job_id=job_id, phase="ready", revision=0, job_dir=str(job_dir),
               previous_python_executable=os.path.abspath(previous), bootstrap_legacy=True,
               progress={}, error="", result=None,
               launcher={"supported": True, "protocol": 1, "command": str(release / "scripts/update_bootstrap.py"), "reason": ""})
    if args.health_url:
        job["health_url"] = args.health_url
        job["health_base_path"] = urllib.parse.urlsplit(args.health_url).path.removesuffix("/api/health").rstrip("/")
    store.mutate(lambda state: state.update(job=job))
    (args.work_dir / "bootstrap-state.json").write_text(json.dumps({"state_file": str(store.state_path)}), encoding="utf-8")
    print(f"Prepared first upgrade: {store.state_path}", flush=True)
    print("Recovery command: " + format_command(update_runner.recovery_command(args.repo_root, store, job)), flush=True)
    if not args.apply:
        print("Apply command: " + format_command([
            job["control_python_executable"], str(release / "scripts/update_bootstrap.py"),
            "--repo-root", str(args.repo_root), "--work-dir", str(args.work_dir),
            "--resume", "--apply", "--host-stopped", "--health-url", job["health_url"]]), flush=True)
        return 0
    return apply_prepared(args, store, job)


def apply_prepared(args, store, job) -> int:
    if not args.host_stopped or not args.health_url:
        raise RuntimeError("Application requires --host-stopped and the actual --health-url")
    _require_stopped(args.health_url)
    if job.get("phase") != "ready":
        raise RuntimeError("Only a prepared first-upgrade job can be resumed")
    store.mutate(lambda state: state["job"].update(phase="waiting_restart"))
    return subprocess.call([job["control_python_executable"], job["runner_path"], "apply",
                            "--repo-root", str(args.repo_root), "--state-file", str(store.state_path), "--job-id", job["job_id"]],
                           env={**os.environ, **job.get("host_environment", {})})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--previous-python", default="")
    parser.add_argument("--baseline-package", type=Path)
    parser.add_argument("--baseline-sha256", default="")
    parser.add_argument("--health-url", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--host-stopped", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--extract-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verified-release", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.repo_root, args.work_dir = args.repo_root.resolve(), args.work_dir.resolve()
    try:
        if args.work_dir.is_relative_to(args.repo_root):
            raise RuntimeError("First-upgrade workspace must be outside the old installation")
        if args.resume:
            pointer = json.loads((args.work_dir / "bootstrap-state.json").read_text(encoding="utf-8"))
            state_file = Path(pointer["state_file"])
            state = json.loads(state_file.read_text(encoding="utf-8"))
            job = state["job"]
            sys.path.insert(0, str(Path(job["runner_path"]).parent))
            from update_state import UpdateStore
            return apply_prepared(args, UpdateStore(args.repo_root, state_file.parent), job)
        if not args.package:
            raise RuntimeError("A full release package is required")
        args.package = args.package.resolve()
        if args.verified_release:
            return prepare_new(args, args.verified_release)
        release = extract_verified(args.package, args.work_dir / "release", args.sha256)
        portable_python = release / "runtime/python/python.exe"
        python = str(portable_python) if portable_python.is_file() else sys.executable
        command = [python, str(release / "scripts/update_bootstrap.py"), "--verified-release", str(release),
                   "--repo-root", str(args.repo_root), "--work-dir", str(args.work_dir), "--package", str(args.package),
                   "--sha256", args.sha256, "--previous-python", args.previous_python, "--health-url", args.health_url]
        if args.apply:
            command.append("--apply")
        if args.host_stopped:
            command.append("--host-stopped")
        if args.baseline_package:
            command += ["--baseline-package", str(args.baseline_package.resolve()), "--baseline-sha256", args.baseline_sha256]
        if args.extract_only:
            print(json.dumps({"command": command}))
            return 0
        if args.apply and Path(getattr(sys, "_base_executable", sys.executable)).resolve().is_relative_to(args.repo_root):
            raise RuntimeError("Use update_bootstrap.ps1 so the old portable interpreter exits before application")
        return subprocess.call(command, cwd=args.repo_root)
    except Exception as exc:
        print(f"[bootstrap] {exc}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
