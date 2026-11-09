"""Prepare dependencies, frontend and a frozen recovery runner before host shutdown."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit

CANCEL_POLL_SECONDS = 0.5
# The preparing worker thread installs its cancellation and progress hooks here,
# so long pip/npm steps stop promptly without changing helper signatures.
_hooks = threading.local()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(callback, stage: str, message: str) -> None:
    if callback:
        callback({"stage": stage, "message": message})


def _notify(stage: str, message: str) -> None:
    _progress(getattr(_hooks, "progress", None), stage, message)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _terminate_tree(process) -> None:
    """Stop a preparation command and everything it spawned."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                                            "System32", "taskkill.exe")
        try:
            subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except OSError:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(2):
        try:
            process.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
            process.kill()


def _run(command, cwd: Path, log: Path, env=None) -> str:
    cancel_check = getattr(_hooks, "cancel_check", None)
    options = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([str(item) for item in command], stdout=output, **options)
        try:
            while True:
                try:
                    returncode = process.wait(timeout=CANCEL_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_check is not None:
                        cancel_check()
        except BaseException:
            _terminate_tree(process)
            raise
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    with log.open("a", encoding="utf-8") as handle:
        handle.write(text)
    if returncode:
        raise RuntimeError(f"准备步骤失败（退出码 {returncode}），详见 {log}")
    return text


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
        raise RuntimeError("更新包的依赖指纹缺失或无效")
    # Resolving a POSIX venv's python symlink would select the base interpreter
    # and lose the old environment needed for rollback.
    previous = Path(os.path.abspath(sys.executable))
    if prepared["package_kind"] == "portable":
        python = staging / "runtime" / "python" / "python.exe"
        if not python.is_file():
            raise RuntimeError("绿色版更新包缺少完整的 Python 运行时")
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
        raise RuntimeError("目标版本需要安装新的 Python 依赖，但 TCB_STARTUP_SKIP_DEP_SYNC 禁止了该操作")
    if _truthy("TCB_STARTUP_USE_SYSTEM_PYTHON"):
        # The selected system interpreter may be reused only when it already satisfies the target.
        fingerprint = _check_environment(previous, requirements, log)
        return {"python_executable": str(previous), "previous_python_executable": str(previous),
                "environment_fingerprint": fingerprint}
    environment = job_dir / "environment"
    if environment.exists():
        raise RuntimeError("依赖环境目录已存在，请重新发起准备任务")
    _notify("dependencies", "正在创建独立依赖环境并安装 Python 依赖，可能需要几分钟")
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
                raise RuntimeError("前端清单路径超出 front/dist")
            if not target.is_file() or _sha256(target) != expected:
                raise RuntimeError(f"前端资源哈希不一致: {relative}")
        if not (staging / "front" / "dist" / "index.html").is_file():
            raise RuntimeError("缺少前端入口文件")
        return {"frontend_prebuilt": True, "files": list(prepared["files"])}
    if _truthy("TCB_STARTUP_SKIP_DEP_SYNC") or _truthy("TCB_STARTUP_SKIP_FRONTEND_BUILD"):
        raise RuntimeError("前端构建与当前部署路径不匹配，且启动选项禁止重新构建")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise RuntimeError("重新构建前端需要 Node.js 22.13+ 和 npm")
    version = _run([node, "--version"], staging, log).strip().lstrip("v")
    if tuple(int(part) for part in version.split(".")[:2]) < (22, 13):
        raise RuntimeError("重新构建前端需要 Node.js 22.13+")
    front = staging / "front"
    if not (front / "package-lock.json").is_file():
        raise RuntimeError("重新构建前端需要 package-lock.json")
    env = dict(os.environ, WEB_BASE_PATH=deployment["health_base_path"], VITE_BASE_PATH=base, VITE_API_BASE_URL=base,
               TCB_FRONT_BUILD_ROOT_BASE="0")
    _notify("frontend", "正在按当前部署路径重新构建前端（npm ci 与 npm run build），可能需要几分钟")
    _run([npm, "ci", "--no-audit", "--no-fund"], front, log, env)
    _run([npm, "run", "build"], front, log, env)
    assets = _frontend_files(staging)
    if "front/dist/index.html" not in assets:
        raise RuntimeError("前端构建未生成 index.html")
    manifest = prepared["manifest"]
    build = json.loads((staging / "front/dist/build-info.json").read_text(encoding="utf-8-sig"))
    from scripts.update_package import normalize_version, ownership_plan
    if (normalize_version(build.get("version")) != normalize_version(prepared["target_version"])
            or str(build.get("base_path", "")).rstrip("/") != base
            or str(build.get("api_base_url", "")).rstrip("/") != base):
        raise RuntimeError("重新构建的前端元信息与目标部署不一致")
    manifest["files"] = {path: value for path, value in manifest["files"].items() if not path.startswith("front/dist/")}
    built_hashes = {path: _sha256(staging / path) for path in assets}
    manifest["files"].update(built_hashes)
    manifest["frontend"] = {**build, "files": built_hashes, "local_build": True}
    (staging / ".update-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files, deleted = ownership_plan(repo, manifest)
    original_hashes = {relative: _sha256(repo / relative) if (repo / relative).is_file() else None
                       for relative in [*files, *deleted]}
    return {"frontend_prebuilt": False, "files": files, "delete_paths": deleted, "original_hashes": original_hashes}


def prepare_runtime(repo_root, job_dir, prepared, progress_callback=None, cancel_check=None) -> dict:
    """``cancel_check`` raises to abort; running pip/npm commands are then stopped."""
    _hooks.progress, _hooks.cancel_check = progress_callback, cancel_check
    try:
        return _prepare_runtime(repo_root, job_dir, prepared, progress_callback)
    finally:
        _hooks.progress = _hooks.cancel_check = None


def _prepare_runtime(repo_root, job_dir, prepared, progress_callback) -> dict:
    repo, job_dir = Path(repo_root).resolve(), Path(job_dir).resolve()
    staging = Path(prepared["staging_dir"]).resolve()
    if staging == repo or not staging.is_relative_to(job_dir):
        raise RuntimeError("升级准备必须使用本任务的暂存目录")
    if prepared["manifest"].get("migrations", {}).get("backward_compatible") is not True:
        raise RuntimeError("自动升级要求数据迁移向后兼容")
    job_dir.mkdir(parents=True, exist_ok=True)
    log = job_dir / "preparation.log"
    _progress(progress_callback, "dependencies", "正在准备目标版本的 Python 运行环境")
    runtime = _prepare_python(repo, job_dir, prepared, log)
    deployment = _deployment()
    _progress(progress_callback, "frontend", "正在检查前端部署参数与资源")
    frontend = _prepare_frontend(repo, prepared, deployment, log)
    _progress(progress_callback, "runner", "正在固定独立的恢复执行器")
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
    _progress(progress_callback, "ready", "依赖、前端与恢复执行器已就绪")
    return result
