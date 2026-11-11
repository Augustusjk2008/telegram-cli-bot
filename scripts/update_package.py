"""Versioned update payload contract shared by publishing and recovery tools.

Only the standard library is used so this module can run from a recovery snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import zipfile

MANIFEST = ".update-manifest.json"
MARKER = ".distribution.json"
PROTECTED = {
    ".env", "managed_bots.json", ".git", ".tcb", ".updates", ".plugins", "plugins",
    "data", "history", "attachments", ".venv", "venv", "node_modules", ".claude",
    ".session_store.json", ".web_admin_settings.json", ".web_announcement_reads.json",
    ".web_announcements.json",
    ".web_tunnel_state.json", ".web_lan_chat.json", ".web_lan_chat_messages.json",
    ".update-baseline.json", ".release-local",
}
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")


def normalize_version(value) -> str:
    version = str(value or "").strip()
    if version.startswith(("v", "V")):
        version = version[1:]
    match = VERSION_PATTERN.fullmatch(version)
    if not match or any(not part or (part.isdigit() and len(part) > 1 and part[0] == "0")
                        for part in (match.group(4) or "release").split(".")):
        raise ValueError(f"版本格式无效: {value}")
    return version


def compare_versions(left: str, right: str) -> int:
    a, b = VERSION_PATTERN.fullmatch(normalize_version(left)), VERSION_PATTERN.fullmatch(normalize_version(right))
    core_a, core_b = tuple(map(int, a.group(1, 2, 3))), tuple(map(int, b.group(1, 2, 3)))
    if core_a != core_b:
        return (core_a > core_b) - (core_a < core_b)
    pre_a, pre_b = a.group(4), b.group(4)
    if pre_a == pre_b:
        return 0
    if pre_a is None or pre_b is None:
        return 1 if pre_a is None else -1
    for x, y in zip(pre_a.split("."), pre_b.split(".")):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return (int(x) > int(y)) - (int(x) < int(y))
        if x.isdigit() != y.isdigit():
            return -1 if x.isdigit() else 1
        return (x > y) - (x < y)
    return (len(pre_a.split(".")) > len(pre_b.split("."))) - (len(pre_a.split(".")) < len(pre_b.split(".")))


def normalize_path(value: str) -> str:
    raw = str(value).replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.rstrip("/")
    if not raw or raw == ".":
        return ""
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if raw.startswith("/") or any(
        p in {"", ".", ".."} or any(c in p for c in ':*?"<>|') or p.endswith((".", " "))
        or p.split(".")[0].casefold() in reserved or any(ord(c) < 32 for c in p)
        for p in raw.split("/")
    ):
        raise ValueError(f"非法归档路径: {value}")
    return raw


def protected(path: str) -> bool:
    normalized = normalize_path(path).casefold()
    if "__pycache__" in normalized.split("/") or normalized.endswith((".pyc", ".pyo")):
        return True
    return normalized.split("/", 1)[0] in PROTECTED or normalized.startswith(".update-") and normalized != MANIFEST


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def archive_entries(package: Path):
    """Yield validated (path, size, mode, opener) entries without unsafe extraction."""
    if package.name.lower().endswith(".zip"):
        archive = zipfile.ZipFile(package)
        entries = []
        for item in archive.infolist():
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                archive.close()
                raise ValueError(f"更新包不允许链接或特殊文件: {item.filename}")
            entries.append((item.filename, item.is_dir(), item.file_size, mode, lambda item=item: archive.open(item)))
    elif package.name.lower().endswith((".tar.gz", ".tgz")):
        archive = tarfile.open(package, "r:gz")
        entries = []
        for item in archive:
            if not (item.isfile() or item.isdir()):
                archive.close()
                raise ValueError(f"更新包不允许链接或特殊文件: {item.name}")
            entries.append((item.name, item.isdir(), item.size, item.mode, lambda item=item: archive.extractfile(item)))
    else:
        raise ValueError("更新包只支持 .zip 或 .tar.gz")
    try:
        files, directories, result = set(), set(), []
        total_size = 0
        for raw, is_dir, size, mode, opener in entries:
            name = normalize_path(raw)
            if not name or name == ".":
                if is_dir:
                    continue
                raise ValueError("归档包含空文件路径")
            key = name.casefold()
            parents = ["/".join(key.split("/")[:i]) for i in range(1, len(key.split("/")))]
            if key in files or (not is_dir and key in directories) or any(p in files for p in parents):
                raise ValueError(f"归档重复目标或文件/目录冲突: {name}")
            directories.update(parents)
            if is_dir:
                directories.add(key)
                continue
            files.add(key)
            total_size += size
            if len(files) > 250000 or total_size > 16 * 1024**3:
                raise ValueError("更新包解压规模超出限制")
            result.append((name, size, mode, opener))
        yield result
    finally:
        archive.close()


def _json_bytes(raw: bytes, name: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"更新包元信息无效: {name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"更新包元信息无效: {name}")
    return value


def inspect_package(package: Path, *, staging_dir: Path | None = None, expected_version="",
                    current_version="", expected_kind="", expected_platform="", progress_callback=None) -> dict:
    with archive_entries(Path(package)) as entries:
        entry_map = {name: (size, mode, opener) for name, size, mode, opener in entries}
        for required in (MANIFEST, MARKER, "VERSION"):
            if required not in entry_map:
                raise ValueError(f"更新包缺少 {required}，请使用含升级协议的新包")
        def read_small(name):
            if entry_map[name][0] > 32 * 1024**2:
                raise ValueError(f"更新包元信息过大: {name}")
            with entry_map[name][2]() as handle:
                return handle.read()
        manifest = _json_bytes(read_small(MANIFEST), MANIFEST)
        marker = _json_bytes(read_small(MARKER), MARKER)
        version = normalize_version(manifest.get("version"))
        versions = [normalize_version(marker.get("version")), normalize_version(read_small("VERSION").decode("utf-8-sig"))]
        if expected_version:
            versions.append(normalize_version(expected_version))
        if any(value != version for value in versions):
            raise ValueError("Release 标签、清单、分发标记和 VERSION 不一致")
        if current_version and compare_versions(version, current_version) < 0:
            raise ValueError(f"禁止降级: {current_version} → {version}")
        if manifest.get("schema_version") != 1 or manifest.get("update_protocol") != 1:
            raise ValueError("更新协议版本不兼容")
        if not isinstance(manifest.get("commit"), str) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", manifest["commit"]):
            raise ValueError("更新清单缺少有效源码提交标识")
        if type(manifest.get("dirty")) is not bool:
            raise ValueError("更新清单缺少工作树状态")
        kind = manifest.get("package_kind")
        if not isinstance(kind, str) or kind not in {"installer", "portable", "linux", "macos"} or kind != (marker.get("package_kind") or marker.get("packageKind")):
            raise ValueError("分发包类型不一致")
        if expected_kind and kind != expected_kind:
            raise ValueError(f"更新包类型不匹配: {kind}; 当前 {expected_kind}")
        package_platform = manifest.get("platform")
        if not package_platform or marker.get("platform") != package_platform or (expected_platform and expected_platform != package_platform):
            raise ValueError("更新包平台不匹配")
        architecture = manifest.get("architecture")
        if not isinstance(architecture, str) or architecture not in {"x64", "arm64", "universal"}:
            raise ValueError("更新包架构无效")
        machine = platform.machine().lower()
        host_arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine
        if expected_kind and architecture not in {host_arch, "universal"}:
            raise ValueError(f"更新包架构不匹配: {architecture}; 当前 {host_arch}")
        declared = manifest.get("files")
        if not isinstance(declared, dict) or not declared:
            raise ValueError("更新清单缺少文件哈希")
        managed = manifest.get("managed_data_files", [])
        if not isinstance(managed, list) or managed:
            raise ValueError("更新清单包含未授权的数据目录文件")
        normalized = {}
        for path, digest in declared.items():
            name = normalize_path(path)
            if name != path or name.casefold() in normalized or protected(name):
                raise ValueError(f"更新清单包含重复或受保护路径: {path}")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"文件哈希无效: {path}")
            normalized[name.casefold()] = name
        expected_files = {name for name in entry_map if name != MANIFEST and not protected(name)}
        if set(declared) != expected_files:
            raise ValueError("归档程序文件与更新清单不一致")
        if staging_dir:
            staging_dir = Path(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)
            if any(staging_dir.iterdir()):
                raise ValueError("暂存目录必须为空")
            required_size = sum(size for name, size, _, _ in entries if name in declared or name == MANIFEST)
            if shutil.disk_usage(staging_dir).free < required_size + 64 * 1024**2:
                raise ValueError("更新暂存空间不足")
        for name, _, mode, opener in entries:
            if name not in declared and name != MANIFEST:
                continue
            digest = hashlib.sha256()
            output = None
            try:
                if staging_dir:
                    output_path = staging_dir.joinpath(*name.split("/"))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output = output_path.open("xb")
                with opener() as reader:
                    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                        digest.update(chunk)
                        if output:
                            output.write(chunk)
                        if progress_callback:
                            progress_callback({"phase": "verifying", "message": f"校验: {name}"})
            finally:
                if output:
                    output.close()
            if name in declared and digest.hexdigest() != declared[name]:
                raise ValueError(f"文件哈希不一致: {name}")
            if staging_dir and mode & 0o111:
                output_path.chmod(0o755)
        dependencies = manifest.get("dependencies")
        if not isinstance(dependencies, dict):
            raise ValueError("更新清单缺少依赖指纹")
        requirements = dependencies.get("requirements_sha256", "")
        if requirements != declared.get("requirements.txt", ""):
            raise ValueError("依赖指纹与 requirements.txt 不一致")
        frontend = manifest.get("frontend", {})
        if not isinstance(frontend, dict) or not isinstance(frontend.get("files"), dict):
            raise ValueError("缺少前端构建标记")
        for path, digest in frontend["files"].items():
            if not path.startswith("front/dist/") or declared.get(path) != digest:
                raise ValueError("前端资源哈希与清单不一致")
        if "front/dist/index.html" not in frontend["files"]:
            raise ValueError("缺少前端入口资源")
        if set(frontend["files"]) != {name for name in declared if name.startswith("front/dist/")}:
            raise ValueError("前端构建清单未覆盖全部资源")
        if "front/dist/build-info.json" not in declared:
            raise ValueError("缺少前端部署构建标记")
        build = _json_bytes(read_small("front/dist/build-info.json"), "front/dist/build-info.json")
        if (normalize_version(build.get("version")) != version
                or str(build.get("base_path", "")).rstrip("/") != str(frontend.get("base_path", "")).rstrip("/")):
            raise ValueError("前端构建版本或部署路径与清单不一致")
        if "source_files" in build and (not isinstance(build["source_files"], dict)
                or any(declared.get(path) != digest for path, digest in build["source_files"].items())):
            raise ValueError("前端构建使用的源码与归档不一致")
        return manifest


def _git(root: Path, *args) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("无法校验源码工作树: " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout.decode("utf-8", "replace").strip()


def source_identity(root: Path) -> dict:
    commit = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    difference = _git(root, "diff", "HEAD", "--binary", "--no-ext-diff")
    if _git(root, "rev-parse", "HEAD") != commit:
        raise ValueError("构建期间源码提交发生变化")
    fingerprint = hashlib.sha256((commit + "\0" + status + "\0" + difference).encode()).hexdigest()
    return {"commit": commit, "fingerprint": fingerprint, "dirty": bool(status)}


def verify_source_identity(root: Path) -> dict:
    identity = source_identity(root)
    expected_commit = os.environ.get("TCB_RELEASE_SOURCE_COMMIT", "")
    expected_fingerprint = os.environ.get("TCB_RELEASE_SOURCE_FINGERPRINT", "")
    if ((expected_commit and identity["commit"] != expected_commit)
            or (expected_fingerprint and identity["fingerprint"] != expected_fingerprint)):
        raise ValueError("构建期间源码提交或工作树发生变化，请重新构建")
    return identity


def ownership_plan(root: Path, manifest: dict) -> tuple[list[str], list[str]]:
    old = {}
    for name in (MANIFEST, ".update-baseline.json"):
        path = root / name
        if path.is_file():
            old = _json_bytes(path.read_bytes(), name).get("files", {})
            break
    if not isinstance(old, dict):
        raise ValueError("当前安装的文件所有权清单无效")
    paths = [*manifest["files"], MANIFEST]
    old_by_key = {os.path.normcase(p): digest for p, digest in old.items()}
    new_keys = {os.path.normcase(p) for p in manifest["files"]}
    deleted = [p for p in old if os.path.normcase(p) not in new_keys and not protected(p)]
    git_root = (root / ".git").exists()
    tracked = set(_git(root, "ls-files", "-z").split("\0")) if git_root else set()
    changed = set(_git(root, "diff", "--name-only", "-z", "HEAD").split("\0")) if git_root else set()
    conflicts = []
    try:
        from .update_transaction import safe_target
    except ImportError:
        from update_transaction import safe_target
    for relative in dict.fromkeys([*paths, *deleted]):
        target = safe_target(root, relative)
        key = os.path.normcase(relative)
        if not target.exists():
            if relative in paths and (key in old_by_key or relative in changed):
                conflicts.append(relative)
            continue
        if not target.is_file():
            conflicts.append(relative)
            continue
        digest = file_hash(target)
        if key in old_by_key:
            if digest != old_by_key[key]:
                conflicts.append(relative)
        elif relative == MANIFEST:
            continue
        elif relative in tracked:
            if relative in changed:
                conflicts.append(relative)
        elif digest != manifest["files"].get(relative):
            conflicts.append(relative)
    if conflicts:
        raise ValueError("存在本地修改或无法确认归属的文件，请保留并处理冲突: " + ", ".join(conflicts[:30]))
    return paths, deleted


def create_manifest(root: Path, source_root: Path) -> dict:
    identity = verify_source_identity(source_root)
    marker = _json_bytes((root / MARKER).read_bytes(), MARKER)
    version = normalize_version((root / "VERSION").read_text(encoding="utf-8-sig"))
    if normalize_version(marker.get("version")) != version:
        raise ValueError("分发标记版本与 VERSION 不一致")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"发布目录含链接: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST or protected(relative):
            continue
        files[normalize_path(relative)] = file_hash(path)
    frontend_files = {p: digest for p, digest in files.items() if p.startswith("front/dist/")}
    build_path = root / "front/dist/build-info.json"
    if not build_path.is_file():
        raise ValueError("缺少前端 build-info.json，请重新构建")
    build = _json_bytes(build_path.read_bytes(), str(build_path))
    if normalize_version(build.get("version")) != version:
        raise ValueError("前端构建与当前版本不一致，请重新构建")
    if not isinstance(build.get("source_files"), dict) or not build["source_files"]:
        raise ValueError("前端构建缺少输入指纹，请重新构建")
    if any(files.get(name) != digest for name, digest in build["source_files"].items()):
        raise ValueError("前端构建后源码发生变化，请重新构建")
    value = {
        "schema_version": 1, "update_protocol": 1, "version": version,
        "commit": identity["commit"], "source_fingerprint": identity["fingerprint"],
        "dirty": identity["dirty"],
        "package_kind": marker.get("packageKind") or marker.get("package_kind"),
        "platform": marker.get("platform"),
        "architecture": "universal" if "universal" in marker.get("platform", "") else "x64",
        "files": files,
        "dependencies": {"requirements_sha256": files.get("requirements.txt", "")},
        "frontend": {**build, "base_path": build.get("base_path", "/"), "files": frontend_files},
        "migrations": {"backward_compatible": True,
                       "files": {p: digest for p, digest in files.items() if p.startswith("bot/migrations/")}},
    }
    if source_identity(source_root) != identity:
        raise ValueError("生成清单期间源码发生变化，请重新构建")
    (root / MANIFEST).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return value


def create_baseline(root: Path, package: Path) -> None:
    """Prove legacy ownership using the user's verified original release archive."""
    files, version = {}, ""
    with archive_entries(package) as entries:
        for name, _, _, opener in entries:
            if protected(name):
                continue
            with opener() as handle:
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    if name == "VERSION":
                        version += chunk.decode("utf-8-sig")
                    digest.update(chunk)
                files[name] = digest.hexdigest()
    if normalize_version(version) != normalize_version((root / "VERSION").read_text(encoding="utf-8-sig")):
        raise ValueError("基线包与当前安装版本不一致")
    (root / ".update-baseline.json").write_text(json.dumps({"files": files}), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    identity_parser = commands.add_parser("identity")
    identity_parser.add_argument("--source-root", type=Path, required=True)
    identity_parser.add_argument("--plain", action="store_true")
    identity_parser.add_argument("--verify", action="store_true")
    create = commands.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--source-root", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("packages", nargs="+", type=Path)
    verify.add_argument("--commit", default="")
    verify.add_argument("--version", default="")
    verify.add_argument("--require-clean", action="store_true")
    verify.add_argument("--source-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "identity":
            identity = verify_source_identity(args.source_root) if args.verify else source_identity(args.source_root)
            print(identity["commit"] + " " + identity["fingerprint"] if args.plain else json.dumps(identity))
        elif args.command == "create":
            create_manifest(args.root, args.source_root)
        else:
            if args.source_root:
                verify_source_identity(args.source_root)
            for package in args.packages:
                manifest = inspect_package(package, expected_version=args.version)
                if args.commit and manifest.get("commit") != args.commit:
                    raise ValueError(f"发布产物与待发布提交不一致: {package.name}")
                if args.require_clean and manifest.get("dirty") is not False:
                    raise ValueError(f"脏工作树产物不可正式发布: {package.name}")
                print(f"更新包校验通过: {package.name}")
        return 0
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
