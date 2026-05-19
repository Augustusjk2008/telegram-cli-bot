from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .models import PluginConfig

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ROOT = PLUGIN_ROOT / "vendor" / "graphviz"
WINDOWS_RUNTIME_DIR = VENDOR_ROOT / "win-x64"


def vendor_dot_path() -> Path:
    return WINDOWS_RUNTIME_DIR / "bin" / "dot.exe"


def resolve_dot_path(config: PluginConfig) -> str:
    vendor_dot = vendor_dot_path()
    if config.bundled_graphviz_enabled and vendor_dot.is_file():
        return str(vendor_dot)
    if config.dot_path and config.dot_path != "dot":
        return config.dot_path
    return "dot"


def graphviz_status(config: PluginConfig) -> dict[str, object]:
    vendor_dot = vendor_dot_path()
    return {
        "vendorInstalled": vendor_dot.is_file(),
        "vendorDotPath": str(vendor_dot),
        "resolvedDotPath": resolve_dot_path(config),
        "bundledEnabled": config.bundled_graphviz_enabled,
        "installAvailable": bool(config.graphviz_runtime_url and config.graphviz_runtime_sha256),
        "version": config.graphviz_runtime_version,
    }


def install_graphviz_runtime(config: PluginConfig) -> dict[str, object]:
    if not config.graphviz_runtime_url or not config.graphviz_runtime_sha256:
        return {"ok": False, "message": "未配置 Graphviz 运行时下载地址或 SHA256"}

    guard_error = _validate_runtime_target()
    if guard_error:
        return {"ok": False, "message": guard_error}

    try:
        with tempfile.TemporaryDirectory(prefix="mermaid-visio-graphviz-") as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / "graphviz-runtime.zip"
            urllib.request.urlretrieve(config.graphviz_runtime_url, archive_path)
            digest = _sha256_file(archive_path)
            if digest.lower() != config.graphviz_runtime_sha256.lower():
                return {"ok": False, "message": f"Graphviz 校验失败: {digest}"}

            extract_dir = tmp_path / "extract"
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, extract_dir)

            dot = _find_dot(extract_dir)
            if dot is None:
                return {"ok": False, "message": "下载包中未找到 bin/dot.exe"}

            next_root = tmp_path / "runtime"
            shutil.copytree(dot.parents[1], next_root)
            _replace_runtime_dir(next_root, WINDOWS_RUNTIME_DIR)
            _write_license_notice(config)
            return {"ok": True, "message": "Graphviz 运行时已安装", "dotPath": str(vendor_dot_path())}
    except Exception as exc:
        return {"ok": False, "message": f"Graphviz 安装失败: {exc}"}


def _validate_runtime_target() -> str:
    plugin_root = PLUGIN_ROOT.resolve()
    target = WINDOWS_RUNTIME_DIR.resolve()
    if target == plugin_root:
        return "Graphviz 安装目录不能是插件根目录"
    if plugin_root not in target.parents:
        return "Graphviz 安装目录越界"
    return ""


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_extract(archive: zipfile.ZipFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in archive.infolist():
        destination = (target_dir / member.filename).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise RuntimeError("Graphviz 下载包包含越界路径")
    archive.extractall(target_dir)


def _replace_runtime_dir(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.next"
    backup = target.parent / f".{target.name}.backup"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    shutil.copytree(source, staging)
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def _find_dot(root: Path) -> Path | None:
    candidates = list(root.rglob("dot.exe"))
    for candidate in candidates:
        if candidate.parent.name.lower() == "bin":
            return candidate
    return candidates[0] if candidates else None


def _write_license_notice(config: PluginConfig) -> None:
    notice = WINDOWS_RUNTIME_DIR / "MERMAID_VISIO_GRAPHVIZ_NOTICE.txt"
    notice.write_text(
        "Graphviz runtime is installed locally for Mermaid Visio.\n"
        "Graphviz is distributed under the Common Public License.\n"
        "License: https://graphviz.gitlab.io/license/\n"
        f"Version: {config.graphviz_runtime_version or 'unknown'}\n",
        encoding="utf-8",
    )
