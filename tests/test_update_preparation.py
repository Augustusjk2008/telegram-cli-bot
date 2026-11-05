from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from bot import update_preparation as preparation


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("public,fixed,enabled,expected", [
    ("https://example.test/tcb-hub/node/x/", "", False, "/tcb-hub/node/x"),
    ("https://example.test/node/x/", "https://fixed.test/gateway/node/x/", True, "/gateway/node/x"),
    ("invalid URL", "https://fixed.test/gateway/node/x", True, "/gateway/node/x"),
    ("https://example.test/other", "https://fixed.test/gateway/node/x", False, "/node/x"),
    ("https://example.test/first/node/x", "https://fixed.test/second/node/x", True, "/first/node/x"),
    ("", "https://fixed.test/gateway/node/x", False, "/node/x"),
])
def test_deployment_keeps_local_health_path_and_uses_eligible_public_prefix(monkeypatch, public, fixed, enabled, expected):
    from bot import config
    for name, value in {"WEB_HOST": "0.0.0.0", "WEB_PORT": 19876, "WEB_BASE_PATH": "/node/x",
                        "WEB_PUBLIC_URL": public, "WEB_FIXED_PUBLIC_FORWARD_URL": fixed,
                        "WEB_FIXED_PUBLIC_FORWARD_ENABLED": enabled}.items():
        monkeypatch.setattr(config, name, value)
    deployment = preparation._deployment()
    assert deployment["health_url"] == "http://127.0.0.1:19876/node/x/api/health"
    assert deployment["health_base_path"] == "/node/x"
    assert deployment["frontend_base_path"] == expected


@pytest.fixture
def payload(tmp_path, monkeypatch):
    repo = tmp_path / "install"
    repo.mkdir()
    job_dir = tmp_path / "jobs/job-1"
    stage = job_dir / "stage"
    (stage / "front/dist").mkdir(parents=True)
    (repo / "requirements.txt").write_text("old-package==1")
    (repo / ".update-baseline.json").write_text(json.dumps({"files": {
        "requirements.txt": hashlib.sha256(b"old-package==1").hexdigest()}}))
    (stage / "requirements.txt").write_text("new-package==2")
    (stage / "front/dist/index.html").write_text("built frontend")
    (stage / "front/dist/chunk.js").write_text("lazy chunk")
    (stage / "front/package-lock.json").write_text("{}")
    for directory, names in (("scripts", ["update_runner.py", "update_transaction.py", "update_package.py"]), ("bot", ["update_state.py"])):
        (repo / directory).mkdir()
        (stage / directory).mkdir()
        for name in names:
            shutil.copy2(ROOT / directory / name, repo / directory / name)
            shutil.copy2(ROOT / directory / name, stage / directory / name)
    files = ["requirements.txt", "front/dist/index.html", "front/dist/chunk.js"]
    hashes = {name: hashlib.sha256((stage / name).read_bytes()).hexdigest() for name in files}
    manifest = {"dependencies": {"requirements_sha256": hashes["requirements.txt"]}, "files": hashes,
                "frontend": {"base_path": "/node/x", "files": {name: value for name, value in hashes.items() if name.startswith("front/")}},
                "migrations": {"backward_compatible": True}}
    prepared = {"package_kind": "source", "staging_dir": str(stage), "files": files,
                "delete_paths": [], "manifest": manifest, "target_version": "2.0.0",
                "original_hashes": {name: preparation._sha256(repo / name) if (repo / name).is_file() else None for name in files}}
    monkeypatch.setattr(preparation, "_deployment", lambda: {"health_url": "http://127.0.0.1:9999/node/x/api/health",
                                                            "health_base_path": "/node/x", "frontend_base_path": "/node/x"})
    monkeypatch.setenv("TCB_UPDATE_CONTROL_ROOT", str(tmp_path / "control"))
    for name in ("TCB_STARTUP_SKIP_DEP_SYNC", "TCB_STARTUP_SKIP_FRONTEND_BUILD", "TCB_STARTUP_FORCE_DEP_INSTALL", "TCB_STARTUP_USE_SYSTEM_PYTHON"):
        monkeypatch.delenv(name, raising=False)
    return repo, job_dir, prepared


def test_changed_dependencies_are_installed_in_stable_separate_environment(payload, monkeypatch):
    repo, job_dir, prepared = payload
    (repo / "scripts/update_runner.py").write_text("raise RuntimeError('old executor must not be imported')")
    commands = []
    monkeypatch.setattr(preparation, "_run", lambda command, *args: commands.append(command) or "")
    monkeypatch.setattr(preparation, "_check_environment", lambda *args: "environment-fingerprint")
    runtime = preparation.prepare_runtime(repo, job_dir, prepared)
    assert runtime["python_executable"].startswith(str(job_dir / "environment"))
    # A POSIX venv python is a symlink; resolving it would lose the old environment.
    assert runtime["previous_python_executable"] == os.path.abspath(sys.executable)
    pip = next(command for command in commands if "install" in command)
    assert str(pip[0]).startswith(str(job_dir / "environment"))
    assert runtime["frontend_prebuilt"] is True
    assert Path(runtime["runner_path"]).is_file()
    assert Path(runtime["runner_path"]).read_bytes() == (Path(prepared["staging_dir"]) / "scripts/update_runner.py").read_bytes()
    assert runtime["prepared_hashes"]["front/dist/index.html"]
    assert (repo / "requirements.txt").read_text() == "old-package==1"
    assert not (repo / "front").exists()


def test_dependency_install_failure_leaves_current_environment_and_frontend_unchanged(payload, monkeypatch):
    repo, job_dir, prepared = payload
    def fail(command, *args):
        if "install" in command:
            raise RuntimeError("offline wheel unavailable")
        return ""
    monkeypatch.setattr(preparation, "_run", fail)
    with pytest.raises(RuntimeError, match="offline wheel"):
        preparation.prepare_runtime(repo, job_dir, prepared)
    assert (repo / "requirements.txt").read_text() == "old-package==1"
    assert not (repo / ".venv").exists()


def test_matching_requirements_still_verify_installed_versions(payload, monkeypatch):
    repo, job_dir, prepared = payload
    shutil.copy2(Path(prepared["staging_dir"]) / "requirements.txt", repo / "requirements.txt")
    checked = []
    monkeypatch.setattr(preparation, "_check_environment", lambda *args: checked.append(args[0]) or "fingerprint")
    monkeypatch.setattr(preparation, "_run", lambda *args: pytest.fail("No install for an exact valid environment"))
    runtime = preparation.prepare_runtime(repo, job_dir, prepared)
    assert runtime["python_executable"] == os.path.abspath(sys.executable)
    assert checked == [Path(os.path.abspath(sys.executable))]


@pytest.mark.parametrize("option", ["TCB_STARTUP_SKIP_DEP_SYNC", "TCB_STARTUP_USE_SYSTEM_PYTHON"])
def test_options_block_incompatible_target_without_mutating_system(payload, monkeypatch, option):
    repo, job_dir, prepared = payload
    monkeypatch.setenv(option, "1")
    monkeypatch.setattr(preparation, "_check_environment", lambda *args: (_ for _ in ()).throw(RuntimeError("Dependency mismatch")))
    monkeypatch.setattr(preparation, "_run", lambda *args: pytest.fail("Must not install into system Python"))
    with pytest.raises(RuntimeError):
        preparation.prepare_runtime(repo, job_dir, prepared)


@pytest.mark.parametrize("mismatch", ["base_path", "api_base_url"])
@pytest.mark.parametrize("public_path", ["/node/x", "/tcb-hub/node/x"])
def test_frontend_rebuild_uses_lockfile_and_staging_with_deployment_prefix(payload, monkeypatch, mismatch, public_path):
    repo, job_dir, prepared = payload
    prepared["manifest"]["frontend"][mismatch] = "/"
    deployment = {**preparation._deployment(), "frontend_base_path": public_path}
    monkeypatch.setattr(preparation, "_deployment", lambda: deployment)
    monkeypatch.setattr(preparation, "_prepare_python", lambda *args: {})
    monkeypatch.setattr(preparation.shutil, "which", lambda name: name)
    (repo / "front/dist").mkdir(parents=True)
    (repo / "front/dist/chunk.js").write_text("lazy chunk")
    baseline = json.loads((repo / ".update-baseline.json").read_text())
    baseline["files"]["front/dist/chunk.js"] = preparation._sha256(repo / "front/dist/chunk.js")
    (repo / ".update-baseline.json").write_text(json.dumps(baseline))
    commands = []
    def run(command, cwd, log, env=None):
        commands.append((command, cwd, env))
        if command[1:] == ["run", "build"]:
            (cwd / "dist/chunk.js").unlink()
            (cwd / "dist/new-chunk.js").write_text("rebuilt resource")
            (cwd / "dist/build-info.json").write_text(json.dumps({"schema_version": 1, "version": "2.0.0",
                "base_path": public_path + "/", "api_base_url": public_path, "root_base": False}))
        return "v22.13.0" if "--version" in command else ""
    monkeypatch.setattr(preparation, "_run", run)
    result = preparation.prepare_runtime(repo, job_dir, prepared)
    assert [command[0][1] for command in commands] == ["--version", "ci", "run"]
    assert all(str(command[1]).startswith(prepared["staging_dir"]) for command in commands)
    assert commands[-1][2]["VITE_BASE_PATH"] == public_path
    assert commands[-1][2]["VITE_API_BASE_URL"] == public_path
    assert commands[-1][2]["WEB_BASE_PATH"] == "/node/x"
    assert result["health_url"] == "http://127.0.0.1:9999/node/x/api/health"
    assert not result["frontend_prebuilt"]
    manifest = json.loads((Path(prepared["staging_dir"]) / ".update-manifest.json").read_text())
    assert manifest["frontend"]["base_path"] == public_path + "/"
    assert manifest["frontend"]["api_base_url"] == public_path
    assert manifest["files"]["front/dist/build-info.json"] == preparation._sha256(Path(prepared["staging_dir"]) / "front/dist/build-info.json")
    assert "front/dist/chunk.js" not in manifest["files"]
    assert result["delete_paths"] == ["front/dist/chunk.js"]
    assert "front/dist/new-chunk.js" in result["files"]
    assert (repo / "front/dist/chunk.js").read_text() == "lazy chunk"
    assert set(result["original_hashes"]) == set(result["files"] + result["delete_paths"])
    assert result["original_hashes"]["front/dist/chunk.js"] == baseline["files"]["front/dist/chunk.js"]
    assert result["original_hashes"]["front/dist/new-chunk.js"] is None
    assert result["original_hashes"][".update-manifest.json"] is None


@pytest.mark.parametrize("reason", ["hash", "old_node", "build", "migration"])
def test_preparation_errors_stop_before_host_mutation(payload, monkeypatch, reason):
    repo, job_dir, prepared = payload
    monkeypatch.setattr(preparation, "_prepare_python", lambda *args: {})
    monkeypatch.setattr(preparation.shutil, "which", lambda name: name)
    if reason == "hash":
        (Path(prepared["staging_dir"]) / "front/dist/chunk.js").write_text("tampered")
    elif reason == "migration":
        prepared["manifest"]["migrations"]["backward_compatible"] = False
    else:
        prepared["manifest"]["frontend"]["base_path"] = "/"
        def run(command, *args):
            if "--version" in command:
                return "v22.12.0" if reason == "old_node" else "v22.13.0"
            raise RuntimeError("Build failed")
        monkeypatch.setattr(preparation, "_run", run)
    with pytest.raises(RuntimeError):
        preparation.prepare_runtime(repo, job_dir, prepared)
    assert (repo / "requirements.txt").read_text() == "old-package==1"


def test_startup_reuses_prebuilt_frontend_and_detects_modified_source(payload):
    repo, job_dir, prepared = payload
    stage = Path(prepared["staging_dir"])
    (stage / ".update-manifest.json").write_text(json.dumps(prepared["manifest"]))
    assert preparation.frontend_is_current(stage)
    (stage / "front/dist/chunk.js").write_text("changed")
    assert not preparation.frontend_is_current(stage)


def test_outer_prefix_prebuilt_assets_are_reused_with_inner_health_path(payload, monkeypatch):
    repo, job_dir, prepared = payload
    stage = Path(prepared["staging_dir"])
    public = "/tcb-hub/node/x"
    deployment = {**preparation._deployment(), "frontend_base_path": public}
    monkeypatch.setattr(preparation, "_deployment", lambda: deployment)
    monkeypatch.setattr(preparation, "_prepare_python", lambda *args: {})
    monkeypatch.setattr(preparation, "_run", lambda *args: pytest.fail("Matching public build must be reused"))
    build = {"version": "2.0.0", "base_path": public + "/", "api_base_url": public, "root_base": False}
    relative = "front/dist/build-info.json"
    (stage / relative).write_text(json.dumps(build))
    checksum = preparation._sha256(stage / relative)
    prepared["files"].append(relative)
    prepared["original_hashes"][relative] = None
    prepared["manifest"]["files"][relative] = checksum
    prepared["manifest"]["frontend"].update(build)
    prepared["manifest"]["frontend"]["files"][relative] = checksum
    marker = stage / ".update-manifest.json"
    marker.write_text(json.dumps(prepared["manifest"]))
    result = preparation.prepare_runtime(repo, job_dir, prepared)
    assert result["frontend_prebuilt"] is True
    assert result["frontend_base_path"] == public
    assert result["health_url"] == "http://127.0.0.1:9999/node/x/api/health"
    assert result["original_hashes"] == prepared["original_hashes"]
    assert preparation.frontend_is_current(stage)
    prepared["manifest"]["frontend"]["api_base_url"] = "/node/x"
    marker.write_text(json.dumps(prepared["manifest"]))
    assert not preparation.frontend_is_current(stage)


def test_reused_virtual_environment_keeps_its_interpreter_symlink(payload, monkeypatch):
    repo, job_dir, prepared = payload
    interpreter = repo / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    try:
        interpreter.symlink_to(sys.executable)
    except OSError:
        pytest.skip("Creating interpreter symlinks is unavailable on this platform")
    shutil.copy2(Path(prepared["staging_dir"]) / "requirements.txt", repo / "requirements.txt")
    monkeypatch.setattr(preparation.sys, "executable", str(interpreter))
    checked = []
    monkeypatch.setattr(preparation, "_check_environment", lambda python, *args: checked.append(python) or "fingerprint")
    result = preparation._prepare_python(repo, job_dir, prepared, job_dir / "log")
    assert result["previous_python_executable"] == str(interpreter)
    assert result["python_executable"] == str(interpreter)
    assert checked == [interpreter]
