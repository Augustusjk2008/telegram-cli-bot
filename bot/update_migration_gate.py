"""Inspect staged migration declarations without importing uninstalled application code."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re


def trace_rollback_origin(job):
    if job.get("phase") != "succeeded" or not (job.get("manifest") or {}).get("commit"):
        return None
    from scripts.update_package import TRACE_READER_FILES
    originals = job.get("original_hashes") or {}
    origin = {"target_commit": job["manifest"]["commit"], "files": {name: originals.get(name) for name in TRACE_READER_FILES}}
    if job.get("job_id"):
        origin["job_id"] = job["job_id"]
    expected_manifest = (job.get("prepared_hashes") or {}).get(".update-manifest.json")
    if expected_manifest:
        origin["target_manifest_sha256"] = expected_manifest
    return origin


def reads_trace_v1(staging, manifest):
    """Check the verified staged files without executing candidate code."""
    from scripts.update_package import TRACE_READER_FILES, trace_body_declaration
    staging = Path(staging)
    declaration = trace_body_declaration(manifest)
    if declaration is not None:
        if "zlib-v1" not in declaration["read"]:
            return False
        for name in TRACE_READER_FILES:
            path = staging / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != (manifest.get("files") or {}).get(name):
                raise ValueError(f"执行明细读取器与更新清单不一致: {name}")
        return True
    # The verified reader at 0c412028 predates the package capability field.
    digest = hashlib.sha256()
    for name in TRACE_READER_FILES:
        path = staging / name
        if not path.is_file():
            return False
        digest.update(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
    return digest.hexdigest() == "9538101cf332bb83e05e2911989eb9a02ba16fa78cf5a3cf752267f311fc8e9b"


def _migration_ids(root):
    path = Path(root) / "bot" / "migrations" / "runner.py"
    if not path.is_file():
        return set()
    constants = {}
    for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                constants[name] = value.value
            elif name == "MIGRATION_IDS" and isinstance(value, (ast.Tuple, ast.List)):
                ids = set()
                for item in value.elts:
                    resolved = constants.get(item.id) if isinstance(item, ast.Name) else (
                        item.value if isinstance(item, ast.Constant) else None)
                    if not isinstance(resolved, str):
                        raise ValueError("无法确认目标版本的数据迁移列表")
                    ids.add(resolved)
                return ids
    raise ValueError("目标版本没有可核验的数据迁移列表")


def validate_update_migrations(repo_root, prepared):
    manifest = prepared.get("manifest") or {}
    migrations = manifest.get("migrations") or {}
    if migrations.get("backward_compatible") is not True:
        raise ValueError("更新包未声明数据迁移向后兼容，无法自动应用")
    staging = Path(prepared["staging_dir"])
    unknown = _migration_ids(staging) - _migration_ids(repo_root)
    if unknown:
        raise ValueError("新数据迁移尚未确认备份与恢复边界，请人工处理: " + ", ".join(sorted(unknown)))
    def migration_path(name):
        name = str(name).replace("\\", "/")
        return (name.startswith("bot/migrations/")
                or name.startswith("bot/storage_migration")
                or name == "bot/storage_runtime.py")

    changed = {str(name).replace("\\", "/") for name in prepared.get("files", []) if migration_path(name)}
    deleted = {str(name).replace("\\", "/") for name in prepared.get("delete_paths", []) if migration_path(name)}
    for directory in (staging / "bot" / "migrations",):
        changed.update(path.relative_to(staging).as_posix() for path in directory.rglob("*")
                       if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    changed.update(path.relative_to(staging).as_posix() for path in (staging / "bot").glob("storage_migration*") if path.is_file())
    if (staging / "bot" / "storage_runtime.py").is_file():
        changed.add("bot/storage_runtime.py")
    for name in sorted(changed | deleted):
        current, target = Path(repo_root) / name, staging / name
        if (name in deleted or not current.is_file() or not target.is_file()
                or hashlib.sha256(current.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest()):
            raise ValueError(f"数据迁移实现变更尚未确认恢复边界: {name}")
    if migrations.get("trace_bodies") is not None or (Path(repo_root) / "bot/web/trace_body_policy.py").is_file():
        if not reads_trace_v1(staging, manifest):
            from scripts.trace_body_compression import require_legacy_ready
            require_legacy_ready()


def frontend_readiness(repo_root, static_dir, base_path=""):
    root, static = Path(repo_root), Path(static_dir)
    try:
        html = (static / "index.html").read_text(encoding="utf-8")
        for reference in re.findall(r'''(?:src|href)=["']([^"']+)["']''', html):
            if reference.startswith(("http:", "https:", "data:", "#")):
                continue
            relative = reference.split("?", 1)[0].split("#", 1)[0]
            if base_path and relative.startswith(base_path + "/"):
                relative = relative[len(base_path):]
            elif "/assets/" in relative:
                # The public proxy can add a prefix outside the node's local base path.
                relative = relative[relative.index("/assets/"):]
            if relative.startswith("/assets/") or relative.startswith("assets/"):
                target = (static / relative.lstrip("/")).resolve()
                if not target.is_relative_to(static.resolve()) or not target.is_file():
                    return False
        marker = root / ".update-manifest.json"
        if marker.is_file():
            manifest = json.loads(marker.read_text(encoding="utf-8"))
            for name, expected in (manifest.get("frontend", {}).get("files") or {}).items():
                target = (root / name).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    return False
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    return False
        return True
    except (OSError, ValueError, TypeError):
        return False
