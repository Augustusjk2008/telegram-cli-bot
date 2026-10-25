"""Prepare dependencies, frontend and a frozen recovery runner before host shutdown."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(callback, stage: str, message: str) -> None:
    if callback:
        callback({"stage": stage, "message": message})


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _run(command, cwd: Path, log: Path, env=None) -> str:
    result = subprocess.run([str(item) for item in command], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    with log.open("a", encoding="utf-8") as output:
        output.write(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Preparation failed (exit {result.returncode}); see {log}")
    return result.stdout


_CHECK_ENV = r'''
import hashlib, importlib.metadata as metadata, json, platform, sys
try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
from pathlib import Path
for line in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    requirement = Requirement(line)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    version = metadata.version(requirement.name)
    if requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
        raise RuntimeError(f"Dependency mismatch: {requirement.name} {version}")
packages = sorted((d.metadata['Name'].lower(), d.version) for d in metadata.distributions() if d.metadata['Name'])
print(json.dumps({"python": sys.version, "executable": sys.executable,
                  "platform": platform.platform(), "packages": packages}, sort_keys=True))
'''


def _check_environment(python: Path, requirements: Path, log: Path) -> str:
    output = _run([python, "-c", _CHECK_ENV, requirements], requirements.parent, log)
    return hashlib.sha256(output.encode()).hexdigest()


def _prepare_python(repo: Path, job_dir: Path, prepared: dict, log: Path) -> dict:
    staging = Path(prepared["staging_dir"])
    requirements = staging / "requirements.txt"
    wanted = prepared["manifest"].get("dependencies", {}).get("requirements_sha256")
    if not wanted or not requirements.is_file() or _sha256(requirements) != wanted:
        raise RuntimeError("Update requirements fingerprint is missing or invalid")
    # Resolving a POSIX venv's python symlink would select the base interpreter
    # and lose the old environment needed for rollback.
    previous = Path(os.path.abspath(sys.executable))
    if prepared["package_kind"] == "portable":
        python = staging / "runtime" / "python" / "python.exe"
        if not python.is_file():
            raise RuntimeError("Portable package has no complete Python runtime")
        fingerprint = _check_environment(python, requirements, log)
        return {"python_executable": str(repo / "runtime" / "python" / "python.exe"),
                "previous_python_executable": str(previous), "environment_fingerprint": fingerprint}
    current_requirements = repo / "requirements.txt"
    same_requirements = current_requirements.is_file() and _sha256(current_requirements) == wanted
    if same_requirements and not _truthy("TCB_STARTUP_FORCE_DEP_INSTALL"):
        try:
            fingerprint = _check_environment(previous, requirements, log)
            return {"python_executable": str(previous), "previous_python_executable": str(previous),
                    "environment_fingerprint": fingerprint}
        except (OSError, RuntimeError):
            pass
    if _truthy("TCB_STARTUP_SKIP_DEP_SYNC"):
        raise RuntimeError("Target dependencies require preparation; TCB_STARTUP_SKIP_DEP_SYNC blocks it")
    if _truthy("TCB_STARTUP_USE_SYSTEM_PYTHON"):
        # The selected system interpreter may be reused only when it already satisfies the target.
        fingerprint = _check_environment(previous, requirements, log)
        return {"python_executable": str(previous), "previous_python_executable": str(previous),
                "environment_fingerprint": fingerprint}
    environment = job_dir / "environment"
    if environment.exists():
        raise RuntimeError("Dependency environment already exists; retry with a new preparation job")
    _run([previous, "-m", "venv", environment], job_dir, log)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run([python, "-m", "pip", "install", "-r", requirements], staging, log)
    fingerprint = _check_environment(python, requirements, log)
    _run([python, "-m", "pip", "check"], staging, log)
    return {"python_executable": str(python), "previous_python_executable": str(previous),
            "environment_fingerprint": fingerprint}


def _deployment() -> dict:
    from . import config
    host = config.WEB_HOST
    if host in {"0.0.0.0", ""}:
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    base = "/" + config.WEB_BASE_PATH.strip().strip("/") if config.WEB_BASE_PATH.strip().strip("/") else ""
    public_base = base
    if base:
        urls = [getattr(config, "WEB_PUBLIC_URL", "")]
        if getattr(config, "WEB_FIXED_PUBLIC_FORWARD_ENABLED", False):
            urls.append(getattr(config, "WEB_FIXED_PUBLIC_FORWARD_URL", ""))
        for value in urls:
            try:
                url = urlsplit(str(value or "").strip())
                if not url.scheme:
                    continue
                path = "/" + url.path.strip().strip("/") if url.path.strip().strip("/") else ""
                if path and path != base and path.endswith(base):
                    public_base = path
                    break
            except ValueError:
                continue
    return {"health_url": f"http://{host}:{config.WEB_PORT}{base}/api/health", "health_base_path": base,
            "frontend_base_path": public_base}


def _frontend_files(staging: Path) -> list[str]:
    return sorted(path.relative_to(staging).as_posix() for path in (staging / "front" / "dist").rglob("*") if path.is_file())


def frontend_is_current(repo_root) -> bool:
    """Allow official startup to reuse a verified build with unchanged source inputs."""
    root = Path(repo_root).resolve()
    try:
        manifest = json.loads((root / ".update-manifest.json").read_text(encoding="utf-8-sig"))
        frontend = manifest["frontend"]
        base = _deployment()["frontend_base_path"].rstrip("/")
        if frontend["base_path"].rstrip("/") != base:
            return False
        if "api_base_url" in frontend and str(frontend["api_base_url"]).rstrip("/") != base:
            return False
        if base and frontend.get("root_base") is True:
            return False
        if "front/dist/index.html" not in frontend["files"]:
            return False
        hashes = {relative: expected for relative, expected in manifest["files"].items()
                  if relative.startswith(("front/", "scripts/build_web_frontend"))}
        hashes.update(frontend["files"])
        for relative, expected in hashes.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file() or _sha256(path) != expected:
                return False
        return True
    except (OSError, KeyError, TypeError, ValueError):
        return False


def _prepare_frontend(repo: Path, prepared: dict, deployment: dict, log: Path) -> dict:
    staging = Path(prepared["staging_dir"])
    marker = prepared["manifest"].get("frontend", {})
    base = deployment["frontend_base_path"].rstrip("/")
    hashes = marker.get("files", {})
    reusable = marker.get("base_path", "").rstrip("/") == base and bool(hashes)
    if "api_base_url" in marker:
        reusable = reusable and str(marker["api_base_url"]).rstrip("/") == base
    if base and marker.get("root_base") is True:
        reusable = False
    if reusable:
        for relative, expected in hashes.items():
            target = staging / relative
            if not target.resolve().is_relative_to((staging / "front" / "dist").resolve()):
                raise RuntimeError("Frontend manifest path is outside front/dist")
            if not target.is_file() or _sha256(target) != expected:
                raise RuntimeError(f"Frontend asset hash mismatch: {relative}")
        if not (staging / "front" / "dist" / "index.html").is_file():
            raise RuntimeError("Frontend entry is missing")
        return {"frontend_prebuilt": True, "files": list(prepared["files"])}
    if _truthy("TCB_STARTUP_SKIP_DEP_SYNC") or _truthy("TCB_STARTUP_SKIP_FRONTEND_BUILD"):
        raise RuntimeError("Frontend build does not match deployment; startup options disable building")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise RuntimeError("Preparing this frontend requires Node.js 22.13+ and npm")
    version = _run([node, "--version"], staging, log).strip().lstrip("v")
    if tuple(int(part) for part in version.split(".")[:2]) < (22, 13):
        raise RuntimeError("Preparing this frontend requires Node.js 22.13+")
    front = staging / "front"
    if not (front / "package-lock.json").is_file():
        raise RuntimeError("Frontend build requires package-lock.json")
    env = dict(os.environ, WEB_BASE_PATH=deployment["health_base_path"], VITE_BASE_PATH=base, VITE_API_BASE_URL=base,
               TCB_FRONT_BUILD_ROOT_BASE="0")
    _run([npm, "ci", "--no-audit", "--no-fund"], front, log, env)
    _run([npm, "run", "build"], front, log, env)
    assets = _frontend_files(staging)
    if "front/dist/index.html" not in assets:
        raise RuntimeError("Frontend build did not produce index.html")
    manifest = prepared["manifest"]
    build = json.loads((staging / "front/dist/build-info.json").read_text(encoding="utf-8-sig"))
    from scripts.update_package import normalize_version, ownership_plan
    if (normalize_version(build.get("version")) != normalize_version(prepared["target_version"])
            or str(build.get("base_path", "")).rstrip("/") != base
            or str(build.get("api_base_url", "")).rstrip("/") != base):
        raise RuntimeError("Rebuilt frontend metadata does not match the target deployment")
    manifest["files"] = {path: value for path, value in manifest["files"].items() if not path.startswith("front/dist/")}
    built_hashes = {path: _sha256(staging / path) for path in assets}
    manifest["files"].update(built_hashes)
    manifest["frontend"] = {**build, "files": built_hashes, "local_build": True}
    (staging / ".update-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files, deleted = ownership_plan(repo, manifest)
    original_hashes = {relative: _sha256(repo / relative) if (repo / relative).is_file() else None
                       for relative in [*files, *deleted]}
    return {"frontend_prebuilt": False, "files": files, "delete_paths": deleted, "original_hashes": original_hashes}


def prepare_runtime(repo_root, job_dir, prepared, progress_callback=None) -> dict:
    repo, job_dir = Path(repo_root).resolve(), Path(job_dir).resolve()
    staging = Path(prepared["staging_dir"]).resolve()
    if staging == repo or not staging.is_relative_to(job_dir):
        raise RuntimeError("Update preparation must use this job's staging directory")
    if prepared["manifest"].get("migrations", {}).get("backward_compatible") is not True:
        raise RuntimeError("Automatic update requires backward-compatible data migrations")
    job_dir.mkdir(parents=True, exist_ok=True)
    log = job_dir / "preparation.log"
    _progress(progress_callback, "dependencies", "Preparing the target Python environment")
    runtime = _prepare_python(repo, job_dir, prepared, log)
    deployment = _deployment()
    _progress(progress_callback, "frontend", "Checking frontend deployment and assets")
    frontend = _prepare_frontend(repo, prepared, deployment, log)
    _progress(progress_callback, "runner", "Freezing the independent recovery executor")
    runner_source = Path(prepared.get("runner_source_root") or staging).resolve()
    spec = importlib.util.spec_from_file_location("update_preparation_runner", runner_source / "scripts" / "update_runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    snapshot = runner.freeze_runner(repo, job_dir / "runner", source_root=runner_source)
    files = frontend["files"]
    result = dict(prepared, **runtime, **deployment)
    result.update(frontend)
    result.update(snapshot)
    result.update(backup_dir=str(job_dir / "transaction"),
                  previous_frontend_hashes={relative: _sha256(repo / relative) for relative in _frontend_files(repo)},
                  prepared_hashes={relative: _sha256(staging / relative) for relative in files},
                  host_environment={name: os.environ[name] for name in (
                      "PATH", "WEB_ENABLED", "TCB_DATA_DIR", "PYTHONUTF8", "PYTHONNOUSERSITE",
                      "PI_AGENT_SETTINGS", "PI_AGENT_MODELS", "NATIVE_AGENT_PI_HOME", "NATIVE_AGENT_ENABLED",
                      "NATIVE_AGENT_PI_COMMAND", "NATIVE_AGENT_COMMAND", "TCB_CLUSTER_MCP_CONFIG") if name in os.environ},
                  preparation_log=str(log))
    _progress(progress_callback, "ready", "Dependencies, frontend and recovery executor are ready")
    return result
