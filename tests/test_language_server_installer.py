from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

import pytest

from bot.language_server.installer import LanguageServerInstallError, LanguageServerInstaller


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_tgz(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for relative, content in files.items():
            info = tarfile.TarInfo(f"package/{relative}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _write_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for relative, content in files.items():
            archive.writestr(relative, content)


def _write_manifest(
    root: Path,
    *,
    pyright_archive: Path,
    pyright_version: str = "1.0.0",
    pyright_sha256: str | None = None,
    typescript_server_archive: Path | None = None,
    typescript_archive: Path | None = None,
    clangd_windows_archive: Path | None = None,
    clangd_linux_archive: Path | None = None,
) -> Path:
    typescript_server_archive = typescript_server_archive or pyright_archive
    typescript_archive = typescript_archive or pyright_archive
    clangd_windows_archive = clangd_windows_archive or pyright_archive
    clangd_linux_archive = clangd_linux_archive or clangd_windows_archive
    payload = {
        "schemaVersion": 1,
        "providers": {
            "pyright": {
                "displayName": "Pyright",
                "version": pyright_version,
                "runtime": "node",
                "environmentVariable": "TCB_LSP_PYRIGHT_COMMAND",
                "pathCommands": ["pyright-langserver"],
                "managedCommand": {"entrypoint": "node_modules/pyright/langserver.index.js", "args": ["--stdio"]},
                "extensions": [".py"],
                "license": {"spdx": "MIT", "url": "https://example.test/pyright-license"},
                "assets": [
                    {
                        "id": "pyright",
                        "version": pyright_version,
                        "platform": "any",
                        "url": pyright_archive.as_uri(),
                        "sha256": pyright_sha256 or _sha256(pyright_archive),
                        "archive": "tar.gz",
                        "archiveRoot": "package",
                        "target": "node_modules/pyright",
                    }
                ],
            },
            "typescript": {
                "displayName": "TypeScript",
                "version": "4.4.1",
                "runtime": "node",
                "environmentVariable": "TCB_LSP_TYPESCRIPT_COMMAND",
                "pathCommands": ["typescript-language-server"],
                "managedCommand": {
                    "entrypoint": "node_modules/typescript-language-server/lib/cli.mjs",
                    "args": ["--stdio"],
                },
                "extensions": [".ts"],
                "license": {"spdx": "Apache-2.0", "url": "https://example.test/typescript-license"},
                "assets": [
                    {
                        "id": "typescript-language-server",
                        "version": "4.4.1",
                        "platform": "any",
                        "url": typescript_server_archive.as_uri(),
                        "sha256": _sha256(typescript_server_archive),
                        "archive": "tar.gz",
                        "archiveRoot": "package",
                        "target": "node_modules/typescript-language-server",
                    },
                    {
                        "id": "typescript",
                        "version": "5.9.2",
                        "platform": "any",
                        "url": typescript_archive.as_uri(),
                        "sha256": _sha256(typescript_archive),
                        "archive": "tar.gz",
                        "archiveRoot": "package",
                        "target": "node_modules/typescript",
                    },
                ],
            },
            "clangd": {
                "displayName": "clangd",
                "version": "1.0.0",
                "runtime": "native",
                "environmentVariable": "TCB_LSP_CLANGD_COMMAND",
                "pathCommands": ["clangd"],
                "managedCommand": {"entrypoint": "", "args": ["--stdio"]},
                "extensions": [".cpp"],
                "license": {"spdx": "Apache-2.0", "url": "https://example.test/clangd-license"},
                "assets": [
                    {
                        "id": "clangd",
                        "version": "1.0.0",
                        "platform": "windows-x64",
                        "url": clangd_windows_archive.as_uri(),
                        "sha256": _sha256(clangd_windows_archive),
                        "archive": "zip",
                        "archiveRoot": "clangd_test",
                        "target": "current",
                        "entrypoint": "bin/clangd.exe",
                    },
                    {
                        "id": "clangd",
                        "version": "1.0.0",
                        "platform": "linux-x64",
                        "url": clangd_linux_archive.as_uri(),
                        "sha256": _sha256(clangd_linux_archive),
                        "archive": "zip",
                        "archiveRoot": "clangd_test",
                        "target": "current",
                        "entrypoint": "bin/clangd",
                    },
                ],
            },
        },
    }
    path = root / f"manifest-{pyright_version}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _archives(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    pyright = root / "pyright.tgz"
    typescript_server = root / "typescript-language-server.tgz"
    typescript = root / "typescript.tgz"
    clangd_windows = root / "clangd-windows.zip"
    clangd_linux = root / "clangd-linux.zip"
    _write_tgz(pyright, {"langserver.index.js": b"pyright"})
    _write_tgz(typescript_server, {"lib/cli.mjs": b"typescript-server"})
    _write_tgz(typescript, {"lib/typescript.js": b"typescript"})
    _write_zip(clangd_windows, {"clangd_test/bin/clangd.exe": b"windows-clangd"})
    _write_zip(clangd_linux, {"clangd_test/bin/clangd": b"linux-clangd"})
    return pyright, typescript_server, typescript, clangd_windows, clangd_linux


def test_installer_selects_platform_archive_and_shares_node_tools(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    installer = LanguageServerInstaller(
        manifest_path=manifest,
        managed_root=tmp_path / "data",
        platform_key="windows-x64",
    )

    assert installer.install("pyright")["status"] == "installed"
    assert installer.install("typescript")["status"] == "installed"
    assert installer.install("clangd")["status"] == "installed"

    node_root = tmp_path / "data" / "node"
    assert installer.installation_root("pyright") == node_root
    assert installer.installation_root("typescript") == node_root
    assert (node_root / "node_modules" / "pyright" / "langserver.index.js").read_bytes() == b"pyright"
    assert (node_root / "node_modules" / "typescript-language-server" / "lib" / "cli.mjs").exists()
    assert (node_root / "node_modules" / "typescript" / "lib" / "typescript.js").exists()
    assert (tmp_path / "data" / "native" / "clangd" / "current" / "bin" / "clangd.exe").read_bytes() == b"windows-clangd"


def test_installer_rejects_checksum_and_keeps_previous_version(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest_v1 = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    data = tmp_path / "data"
    LanguageServerInstaller(manifest_path=manifest_v1, managed_root=data, platform_key="windows-x64").install("pyright")

    new_archive = tmp_path / "pyright-v2.tgz"
    _write_tgz(new_archive, {"langserver.index.js": b"new-pyright"})
    manifest_v2 = _write_manifest(
        tmp_path,
        pyright_archive=new_archive,
        pyright_version="2.0.0",
        pyright_sha256="0" * 64,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )

    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer = LanguageServerInstaller(manifest_path=manifest_v2, managed_root=data, platform_key="windows-x64")
        installer.install("pyright", update=True)

    state = json.loads((data / "node" / ".providers" / "pyright.json").read_text(encoding="utf-8"))
    assert exc_info.value.code == "language_server_checksum_mismatch"
    assert installer.last_error("pyright") == {
        "code": "language_server_checksum_mismatch",
        "message": "pyright 校验和不匹配，未安装该版本",
    }
    assert state["version"] == "1.0.0"
    assert (data / "node" / "node_modules" / "pyright" / "langserver.index.js").read_bytes() == b"pyright"


def test_installer_keeps_old_manifest_version_available_until_explicit_update(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    data = tmp_path / "data"
    manifest_v1 = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    LanguageServerInstaller(manifest_path=manifest_v1, managed_root=data, platform_key="windows-x64").install("pyright")

    new_archive = tmp_path / "pyright-v2-available.tgz"
    _write_tgz(new_archive, {"langserver.index.js": b"new-pyright"})
    manifest_v2 = _write_manifest(
        tmp_path,
        pyright_archive=new_archive,
        pyright_version="2.0.0",
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    installer = LanguageServerInstaller(manifest_path=manifest_v2, managed_root=data, platform_key="windows-x64")

    current = installer.current_installation("pyright")
    result = installer.install("pyright")

    assert current is not None
    assert current["version"] == "1.0.0"
    assert current["updateAvailable"] is True
    assert result["status"] == "update_available"
    assert result["version"] == "1.0.0"
    assert result["targetVersion"] == "2.0.0"
    assert (data / "node" / "node_modules" / "pyright" / "langserver.index.js").read_bytes() == b"pyright"


def test_installer_detects_changed_asset_identity_at_same_provider_version(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    data = tmp_path / "data"
    manifest_v1 = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    LanguageServerInstaller(manifest_path=manifest_v1, managed_root=data, platform_key="windows-x64").install("pyright")

    repacked = tmp_path / "pyright-repacked.tgz"
    _write_tgz(repacked, {"langserver.index.js": b"repacked-pyright"})
    manifest_repacked = _write_manifest(
        tmp_path,
        pyright_archive=repacked,
        pyright_version="1.0.0",
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    installer = LanguageServerInstaller(manifest_path=manifest_repacked, managed_root=data, platform_key="windows-x64")

    current = installer.current_installation("pyright")

    assert current is not None
    assert current["version"] == "1.0.0"
    assert current["updateAvailable"] is True


def test_installer_rolls_back_target_when_activation_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    data = tmp_path / "data"
    manifest_v1 = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    LanguageServerInstaller(manifest_path=manifest_v1, managed_root=data, platform_key="windows-x64").install("pyright")

    new_archive = tmp_path / "pyright-v2.tgz"
    _write_tgz(new_archive, {"langserver.index.js": b"new-pyright"})
    manifest_v2 = _write_manifest(
        tmp_path,
        pyright_archive=new_archive,
        pyright_version="2.0.0",
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    installer = LanguageServerInstaller(manifest_path=manifest_v2, managed_root=data, platform_key="windows-x64")

    def fail_state(*_args, **_kwargs) -> None:
        raise OSError("state write failed")

    monkeypatch.setattr(installer, "_write_state_atomic", fail_state)
    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer.install("pyright", update=True)

    state = json.loads((data / "node" / ".providers" / "pyright.json").read_text(encoding="utf-8"))
    assert exc_info.value.code == "language_server_install_failed"
    assert state["version"] == "1.0.0"
    assert (data / "node" / "node_modules" / "pyright" / "langserver.index.js").read_bytes() == b"pyright"


def test_installer_preserves_backup_when_rollback_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    data = tmp_path / "data"
    manifest_v1 = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    LanguageServerInstaller(manifest_path=manifest_v1, managed_root=data, platform_key="windows-x64").install("pyright")

    new_archive = tmp_path / "pyright-v2-rollback.tgz"
    _write_tgz(new_archive, {"langserver.index.js": b"new-pyright"})
    manifest_v2 = _write_manifest(
        tmp_path,
        pyright_archive=new_archive,
        pyright_version="2.0.0",
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    installer = LanguageServerInstaller(manifest_path=manifest_v2, managed_root=data, platform_key="windows-x64")

    monkeypatch.setattr(installer, "_write_state_atomic", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("state")))
    real_replace = __import__("os").replace

    def fail_old_version_restore(source, target) -> None:
        if ".backup-" in str(source):
            raise OSError("restore failed")
        real_replace(source, target)

    monkeypatch.setattr("bot.language_server.installer.os.replace", fail_old_version_restore)

    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer.install("pyright", update=True)

    backups = list((data / "node").glob(".backup-*"))
    assert exc_info.value.code == "language_server_rollback_failed"
    assert exc_info.value.data["recovery_available"] is True
    assert len(backups) == 1
    assert (backups[0] / "0" / "langserver.index.js").read_bytes() == b"pyright"


def test_installer_serializes_concurrent_installation(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    calls = 0
    calls_lock = threading.Lock()
    download_started = threading.Event()
    allow_download = threading.Event()

    def counted_opener(url: str, *, timeout: float):
        nonlocal calls
        with calls_lock:
            calls += 1
        download_started.set()
        assert allow_download.wait(timeout=3)
        return urlopen(url, timeout=timeout)

    installer = LanguageServerInstaller(
        manifest_path=manifest,
        managed_root=tmp_path / "data",
        platform_key="windows-x64",
        opener=counted_opener,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(installer.install, "pyright")
        assert download_started.wait(timeout=3)
        assert installer.is_installing("pyright")
        second = executor.submit(installer.install, "pyright")
        allow_download.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert calls == 1
    assert sorted(item["status"] for item in results) == ["already_installed", "installed"]


def test_installer_ignores_an_unlocked_stale_lock_file(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    data = tmp_path / "data"
    installer = LanguageServerInstaller(
        manifest_path=manifest,
        managed_root=data,
        platform_key="windows-x64",
    )
    root = installer.installation_root("pyright")
    root.mkdir(parents=True)
    (root / ".install.lock").write_text("999999\n", encoding="utf-8")

    assert installer.is_installing("pyright") is False


def test_installer_wraps_and_remembers_unwritable_storage_errors(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    data = tmp_path / "data"
    data.write_text("not a directory", encoding="utf-8")
    installer = LanguageServerInstaller(manifest_path=manifest, managed_root=data, platform_key="windows-x64")

    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer.install("pyright")

    assert exc_info.value.code == "language_server_storage_unavailable"
    assert installer.last_error("pyright")["code"] == "language_server_storage_unavailable"


def test_installer_rejects_oversized_download_and_removes_temporary_file(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    data = tmp_path / "data"
    installer = LanguageServerInstaller(
        manifest_path=manifest,
        managed_root=data,
        platform_key="windows-x64",
        download_max_bytes=16,
    )

    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer.install("pyright")

    assert exc_info.value.code == "language_server_download_too_large"
    assert list((data / "node").glob(".download-*")) == []


def test_installer_enforces_total_download_deadline(tmp_path: Path) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    content = pyright.read_bytes()

    class SlowResponse:
        headers: dict[str, str] = {}

        def __init__(self) -> None:
            self.sent = False

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, _size: int) -> bytes:
            if self.sent:
                return b""
            self.sent = True
            time.sleep(0.08)
            return content

    installer = LanguageServerInstaller(
        manifest_path=manifest,
        managed_root=tmp_path / "data",
        platform_key="windows-x64",
        download_timeout_seconds=0.05,
        opener=lambda *_args, **_kwargs: SlowResponse(),
    )

    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer.install("pyright")

    assert exc_info.value.code == "language_server_download_timeout"


def test_installer_rejects_environment_managed_root_inside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyright, ts_server, ts, clangd_windows, clangd_linux = _archives(tmp_path)
    manifest = _write_manifest(
        tmp_path,
        pyright_archive=pyright,
        typescript_server_archive=ts_server,
        typescript_archive=ts,
        clangd_windows_archive=clangd_windows,
        clangd_linux_archive=clangd_linux,
    )
    monkeypatch.setenv("TCB_DATA_DIR", str(Path.cwd()))
    installer = LanguageServerInstaller(manifest_path=manifest, platform_key="windows-x64")

    assert installer.can_install("pyright") is False
    with pytest.raises(LanguageServerInstallError) as exc_info:
        installer.install("pyright")
    assert exc_info.value.code == "language_server_storage_unsafe"
