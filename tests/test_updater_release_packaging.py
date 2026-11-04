from __future__ import annotations

import io
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from bot import updater
from scripts import update_package


REQUIRED_RELEASE_LEGAL_FILES = (
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "CONTRIBUTING.md",
)
REQUIRED_RELEASE_ARCHIVE_FILES = (
    *REQUIRED_RELEASE_LEGAL_FILES,
    "front/dist/THIRD_PARTY_LICENSES.txt",
)
PORTABLE_RUNTIME_LICENSE_FILES = (
    "runtime/python/LICENSE.txt",
    "runtime/node/LICENSE",
    "tools/git/LICENSE.txt",
)
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _ps_quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _announcement_payload(*item_ids: str) -> dict:
    return {
        "version": 1,
        "updated_at": "2026-06-29T00:00:00Z",
        "items": [
            {
                "id": item_id,
                "published_at": "2026-06-29T00:00:00+00:00",
                "publisher": "Orbit Safe Claw",
                "title": f"公告 {item_id}",
                "category": "release",
                "severity": "info",
                "summary": f"摘要 {item_id}",
                "sections": [],
            }
            for item_id in item_ids
        ],
    }


def test_sync_runtime_announcements_from_package_merges_new_items(monkeypatch, tmp_path: Path) -> None:
    runtime_content = tmp_path / "runtime" / "announcements" / "content.json"
    runtime_content.parent.mkdir(parents=True)
    runtime_content.write_text(json.dumps(_announcement_payload("ann-old"), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(updater, "get_announcements_content_path", lambda: runtime_content)

    package_path = tmp_path / "update.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr(".web_announcements.json", json.dumps(_announcement_payload("ann-old", "ann-new")))

    changed = updater._sync_runtime_announcements_from_package(
        package_path,
        [".web_announcements.json"],
    )

    saved = json.loads(runtime_content.read_text(encoding="utf-8"))
    assert changed is True
    assert [item["id"] for item in saved["items"]] == ["ann-old", "ann-new"]


def _write_legal_archive(path: Path, members: tuple[str, ...]) -> None:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path, "w") as archive:
            for member in members:
                archive.writestr(member, f"content for {member}")
        return
    with tarfile.open(path, "w:gz") as archive:
        for member in members:
            payload = f"content for {member}".encode()
            info = tarfile.TarInfo(f"./{member}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_release_archive_legal_file_verifier_accepts_complete_zip_and_tar(tmp_path: Path) -> None:
    verifier = Path("scripts/verify_release_legal_files.py")
    zip_path = tmp_path / "release.zip"
    tar_path = tmp_path / "release.tar.gz"
    _write_legal_archive(zip_path, REQUIRED_RELEASE_ARCHIVE_FILES)
    _write_legal_archive(tar_path, REQUIRED_RELEASE_ARCHIVE_FILES)

    result = subprocess.run(
        [sys.executable, str(verifier), str(zip_path), str(tar_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_release_archive_legal_file_verifier_rejects_missing_or_directory_entries(tmp_path: Path) -> None:
    verifier = Path("scripts/verify_release_legal_files.py")
    archive_path = tmp_path / "release.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for member in REQUIRED_RELEASE_ARCHIVE_FILES[:-1]:
            archive.writestr(member, "content")
        archive.writestr(f"{REQUIRED_RELEASE_ARCHIVE_FILES[-1]}/", "")

    result = subprocess.run(
        [sys.executable, str(verifier), str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert REQUIRED_RELEASE_ARCHIVE_FILES[-1] in result.stderr


def test_release_archive_legal_file_verifier_requires_portable_runtime_licenses(tmp_path: Path) -> None:
    verifier = Path("scripts/verify_release_legal_files.py")
    archive_path = tmp_path / "portable.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for member in REQUIRED_RELEASE_ARCHIVE_FILES:
            archive.writestr(member, "content")
        archive.writestr("runtime/python/python.exe", "binary")

    missing_result = subprocess.run(
        [sys.executable, str(verifier), str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_result.returncode == 1
    for member in PORTABLE_RUNTIME_LICENSE_FILES:
        assert member in missing_result.stderr

    _write_legal_archive(
        archive_path,
        (*REQUIRED_RELEASE_ARCHIVE_FILES, *PORTABLE_RUNTIME_LICENSE_FILES, "runtime/python/python.exe"),
    )
    complete_result = subprocess.run(
        [sys.executable, str(verifier), str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert complete_result.returncode == 0, complete_result.stderr


def test_updater_rejects_checksum_mismatch_and_archive_traversal(tmp_path: Path) -> None:
    package_path = tmp_path / "update.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("../outside.py", "blocked")

    with pytest.raises(RuntimeError, match="SHA256"):
        updater._verify_file_sha256(package_path, "0" * 64)
    with pytest.raises(updater._PackageStreamError, match="非法归档路径"):
        updater._list_package_entry_paths(package_path)


def test_portable_build_does_not_embed_fixed_web_token() -> None:
    portable = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert "WEB_HOST=127.0.0.1" in portable
    assert "WEB_API_TOKEN=" in portable
    assert "WEB_API_TOKEN=$Token" not in portable
    assert "WEB_API_TOKEN: $Token" not in portable
    assert "[完成] WEB_API_TOKEN" not in portable
    assert "$token = New-WebToken" not in portable
    assert "Write-PortableEnv -PackageRoot $packageRoot -Token" not in portable
    assert "Write-PortableReadme -PackageRoot $packageRoot -Token" not in portable

    migration_index = portable.index('Invoke-RepoModule -Module "bot.env_migration"')
    ensure_token_index = portable.index("Ensure-PortableWebToken -Path $envPath")
    import_index = portable.index("Import-DotEnv -Path $envPath")
    assert migration_index < ensure_token_index < import_index
    assert '$env:TCB_PORTABLE_SMOKE_IMPORT_ONLY -eq "1"' in portable
    assert portable.index('$env:TCB_PORTABLE_SMOKE_IMPORT_ONLY -eq "1"') < ensure_token_index
    assert '$env:TCB_PORTABLE_ROOT = $PackageRoot' in portable
    assert '$portableLocator = Join-Path $PackageRoot ".tcb\\storage.json"' in portable
    assert 'Remove-Item Env:TCB_DATA_DIR -ErrorAction SilentlyContinue' in portable


def test_release_builders_require_packaged_theme_catalogs() -> None:
    for relative_path in (
        ".release-local/publish-release.ps1",
        ".release-local/portable-win/build-portable.ps1",
    ):
        script = Path(relative_path).read_text(encoding="utf-8")
        assert '"bot/web/theme_presets.json"' in script
        assert '"bot/web/theme_illustrations.json"' in script
        assert "Assert-ThemeFilesInStage" in script


def test_portable_build_writes_windows_scripts_and_python_files_with_compatible_encodings() -> None:
    portable = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert "$script:Utf8BomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $true" in portable
    assert portable.count("$script:Utf8NoBomEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $false") >= 2
    assert "WriteAllText((Join-Path $PackageRoot \"start.ps1\"), $startPs1, $script:Utf8BomEncoding)" in portable
    assert "WriteAllText((Join-Path $PackageRoot \"install.ps1\"), $installPs1, $script:Utf8BomEncoding)" in portable
    assert "WriteAllText((Join-Path $PackageRoot \".env\"), $content, $script:Utf8NoBomEncoding)" in portable
    assert "WriteAllLines($Path, [string[]]$lines, $script:Utf8NoBomEncoding)" in portable
    assert 'print(f"{key}={value}")' not in portable
    assert "print(f'{key}={value}')" in portable


@pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows PowerShell unavailable")
def test_release_tar_builder_preserves_batch_files(tmp_path: Path) -> None:
    source = tmp_path / "release" / "stage" / "snapshot"
    batch = source / "scripts" / "empty_recycle_bin.bat"
    destination = tmp_path / "release" / "artifacts" / "payload.tar.gz"
    batch.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    batch.write_text("@echo off\r\n", encoding="utf-8", newline="")

    script = Path(".release-local/publish-release.ps1").resolve()
    command = f'''
$ErrorActionPreference = "Stop"
$script:RepoRoot = {_ps_quote(Path.cwd())}
$ast = [System.Management.Automation.Language.Parser]::ParseFile({_ps_quote(script)}, [ref]$null, [ref]$null)
foreach ($name in @("Invoke-CheckedCommand", "New-TarGzArchive")) {{
    $fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }}, $true)
    Invoke-Expression $fn.Extent.Text
}}
New-TarGzArchive -SourceDir {_ps_quote(source)} -DestinationFile {_ps_quote(destination)}
'''
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    with tarfile.open(destination, "r:gz") as archive:
        assert "./scripts/empty_recycle_bin.bat" in archive.getnames()


def test_updated_frontend_build_uses_npm_without_legacy_script(monkeypatch, tmp_path: Path) -> None:
    front_root = tmp_path / "front"
    front_root.mkdir()
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, stdout="built", stderr="")

    monkeypatch.setattr(updater.shutil, "which", lambda name: "npm" if name == "npm" else None)
    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    assert updater._build_updated_frontend(tmp_path) == (True, "built")
    assert commands == [(["npm", "run", "build"], front_root)]


def test_updated_frontend_build_installs_dependencies_then_retries(monkeypatch, tmp_path: Path) -> None:
    front_root = tmp_path / "front"
    front_root.mkdir()
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 1 if len(commands) == 1 else 0, stdout="", stderr="")

    monkeypatch.setattr(updater.shutil, "which", lambda _name: "npm")
    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    assert updater._build_updated_frontend(tmp_path)[0] is True
    assert commands == [
        (["npm", "run", "build"], front_root),
        (["npm", "ci", "--no-audit", "--no-fund"], front_root),
        (["npm", "run", "build"], front_root),
    ]


def test_updated_frontend_build_reports_missing_npm(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "front").mkdir()
    monkeypatch.setattr(updater.shutil, "which", lambda _name: None)

    success, message = updater._build_updated_frontend(tmp_path)

    assert success is False
    assert "npm" in message


def test_updated_frontend_build_keeps_legacy_script_precedence(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "front").mkdir()
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_name = "build_web_frontend.bat" if os.name == "nt" else "build_web_frontend.sh"
    script_path = scripts_dir / script_name
    script_path.write_text("stub", encoding="utf-8")
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    assert updater._build_updated_frontend(tmp_path)[0] is True
    expected = [str(script_path.resolve())] if os.name == "nt" else ["bash", str(script_path.resolve())]
    assert commands == [(expected, tmp_path)]


def update_archive(tmp_path, *, version="3.1.0", additions=None, manifest_changes=None):
    contents = {
        "VERSION": version.encode(), "requirements.txt": b"aiohttp==3.11.0\n",
        "bot/main.py": b"print('new')\n", "front/dist/index.html": b"<html></html>",
        "front/dist/build-info.json": json.dumps({"version": version, "base_path": "/", "api_base_url": "", "root_base": True,
            "source_files": {"VERSION": hashlib.sha256(version.encode()).hexdigest()}}).encode(),
        ".distribution.json": json.dumps({"version": version, "packageKind": "installer", "platform": "windows-x64"}).encode(),
    }
    contents.update(additions or {})
    files = {p: hashlib.sha256(raw).hexdigest() for p, raw in contents.items() if not update_package.protected(p)}
    manifest = {
        "schema_version": 1, "update_protocol": 1, "version": version, "package_kind": "installer",
        "platform": "windows-x64", "architecture": "x64", "commit": "a" * 40, "dirty": False,
        "files": files, "dependencies": {"requirements_sha256": files["requirements.txt"]},
        "frontend": {"base_path": "/", "files": {p: h for p, h in files.items() if p.startswith("front/dist/")}},
        "migrations": {"backward_compatible": True},
    }
    manifest.update(manifest_changes or {})
    contents[update_package.MANIFEST] = json.dumps(manifest).encode()
    path = tmp_path / "payload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in contents.items():
            archive.writestr(name, raw)
    return path, manifest


@pytest.mark.parametrize("left,right,result", [
    ("3.10.0", "3.9.9", 1), ("v3.1.0", "3.1.0", 0), ("3.1.0-rc.2", "3.1.0-rc.10", -1),
    ("3.1.0", "3.1.0-beta", 1), ("3.1.0+build2", "3.1.0+build1", 0),
])
def test_update_version_comparison(left, right, result):
    assert update_package.compare_versions(left, right) == result


@pytest.mark.parametrize("version", ["offline", "3", "3.01.0", "3.1.0-01", "3.1.0-rc..1"])
def test_update_invalid_versions(version):
    with pytest.raises(ValueError):
        update_package.normalize_version(version)


def test_update_payload_versions_types_platforms_and_hashes(tmp_path):
    package, _ = update_archive(tmp_path)
    assert update_package.inspect_package(package, expected_version="v3.1.0")["version"] == "3.1.0"
    for kwargs in ({"expected_version": "3.2.0"}, {"current_version": "4.0.0"},
                   {"expected_kind": "portable"}, {"expected_platform": "linux-x64"}):
        with pytest.raises(ValueError):
            update_package.inspect_package(package, **kwargs)
    package, _ = update_archive(tmp_path, additions={"VERSION": b"3.2.0"})
    with pytest.raises(ValueError, match="不一致"):
        update_package.inspect_package(package)
    package, manifest = update_archive(tmp_path)
    manifest["files"]["bot/main.py"] = "0" * 64
    package, _ = update_archive(tmp_path, manifest_changes=manifest)
    with pytest.raises(ValueError, match="哈希不一致"):
        update_package.inspect_package(package)


@pytest.mark.parametrize("changes", [{"commit": ""}, {"dirty": "false"}, {"dependencies": None},
                                     {"architecture": []}, {"package_kind": []}])
def test_invalid_update_manifest_metadata_is_rejected(tmp_path, changes):
    package, _ = update_archive(tmp_path, manifest_changes=changes)
    with pytest.raises(ValueError):
        update_package.inspect_package(package)


@pytest.mark.parametrize("names", [
    ["bot/main.py", "BOT/MAIN.py"], ["bot", "bot/main.py"], ["bot/main.py", "BOT"],
    ["data/file."] , ["CON.txt"], ["C:/outside"], ["../outside"],
])
def test_archive_rejects_windows_aliases_and_conflicting_targets(tmp_path, names):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
    with pytest.raises(ValueError):
        with update_package.archive_entries(path):
            pass


def test_archive_rejects_tar_links(tmp_path):
    path = tmp_path / "links.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        item = tarfile.TarInfo("bot/link")
        item.type, item.linkname = tarfile.SYMTYPE, "../../outside"
        archive.addfile(item)
    with pytest.raises(ValueError, match="链接"):
        with update_package.archive_entries(path):
            pass


def test_payload_preserves_configuration_and_requires_ownership(tmp_path):
    package, manifest = update_archive(tmp_path, additions={".ENV": b"secret", "data/pi-home/.pi/agent/models.json": b"keys"})
    staging = tmp_path / "stage"
    update_package.inspect_package(package, staging_dir=staging)
    assert not (staging / ".ENV").exists()
    assert not (staging / "data").exists()
    install = tmp_path / "app"
    (install / "bot").mkdir(parents=True)
    target = install / "bot/main.py"
    target.write_text("my modification")
    with pytest.raises(ValueError, match="本地修改"):
        update_package.ownership_plan(install, manifest)
    baseline = {"files": {"bot/main.py": update_package.file_hash(target), "obsolete.py": hashlib.sha256(b"old").hexdigest()}}
    (install / update_package.MANIFEST).write_text(json.dumps(baseline))
    (install / "obsolete.py").write_bytes(b"old")
    files, deleted = update_package.ownership_plan(install, manifest)
    assert "bot/main.py" in files and deleted == ["obsolete.py"]
    target.write_text("changed after baseline")
    with pytest.raises(ValueError, match="本地修改"):
        update_package.ownership_plan(install, manifest)


def test_publish_only_rejects_stale_commit_and_dirty_payload(tmp_path):
    package, _ = update_archive(tmp_path)
    assert update_package.main(["verify", "--commit", "b" * 40, str(package)]) == 1
    package, _ = update_archive(tmp_path, manifest_changes={"dirty": True})
    assert update_package.main(["verify", "--require-clean", str(package)]) == 1


def test_owned_release_files_allow_next_source_update_despite_older_git_head(monkeypatch, tmp_path):
    _, manifest = update_archive(tmp_path)
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    (install / "bot").mkdir()
    target = install / "bot/main.py"
    target.write_text("previous release bytes")
    (install / update_package.MANIFEST).write_text(json.dumps({"files": {"bot/main.py": update_package.file_hash(target)}}))
    monkeypatch.setattr(update_package, "_git", lambda *args: "bot/main.py\0")
    assert "bot/main.py" in update_package.ownership_plan(install, manifest)[0]
    target.unlink()
    with pytest.raises(ValueError, match="本地修改"):
        update_package.ownership_plan(install, manifest)


def test_legacy_recovery_missing_material_preserves_target(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("only surviving copy")
    transaction = tmp_path / ".update-apply-legacy"
    transaction.mkdir()
    updater._append_update_journal(transaction / "journal.jsonl", {
        "event": "backup", "target_path": str(target), "relative_path": "app.py",
        "backup_path": str(transaction / "missing"),
    })
    with pytest.raises(RuntimeError, match="备份缺失"):
        updater._recover_interrupted_update_applications(tmp_path)
    assert target.read_text() == "only surviving copy"
    assert transaction.exists()


def test_legacy_recovery_preserves_manual_repair_when_ownership_is_unknown(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("manual repair")
    directory = tmp_path / ".update-apply-legacy"
    directory.mkdir()
    backup = directory / "backup-0000"
    backup.write_text("old version")
    updater._append_update_journal(directory / "journal.jsonl", {
        "event": "backup", "target_path": str(target), "relative_path": "app.py", "backup_path": str(backup),
    })
    with pytest.raises(RuntimeError, match="无法证明"):
        updater._recover_interrupted_update_applications(tmp_path)
    assert target.read_text() == "manual repair" and backup.read_text() == "old version"


def test_preparation_never_restores_legacy_files_in_a_running_installation(tmp_path):
    directory = tmp_path / ".update-apply-legacy"
    directory.mkdir()
    backup = directory / "backup-0000"
    backup.write_text("old version")
    target = tmp_path / "app.py"
    updater._append_update_journal(directory / "journal.jsonl", {
        "event": "backup", "target_path": str(target), "relative_path": "app.py", "backup_path": str(backup),
    })
    with pytest.raises(RuntimeError, match="recovery_required"):
        updater._assert_no_unfinished_legacy_transactions(tmp_path)
    assert not target.exists() and backup.exists()


def test_generated_caches_are_excluded_from_ownership_and_retirement(tmp_path):
    cache = "bot/__pycache__/main.cpython-312.pyc"
    package, manifest = update_archive(tmp_path, additions={cache: b"generated cache"})
    stage = tmp_path / "stage"
    update_package.inspect_package(package, staging_dir=stage)
    assert not (stage / cache).exists()
    installed = tmp_path / "app"
    installed.mkdir()
    (installed / update_package.MANIFEST).write_text(json.dumps({"files": {cache: "0" * 64}}))
    assert cache not in update_package.ownership_plan(installed, manifest)[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive filesystem contract")
def test_windows_case_only_rename_does_not_schedule_deletion(tmp_path):
    _, manifest = update_archive(tmp_path)
    root = tmp_path / "app"
    (root / "bot").mkdir(parents=True)
    target = root / "bot/Main.py"
    target.write_bytes(b"print('new')\n")
    (root / update_package.MANIFEST).write_text(json.dumps({"files": {"bot/Main.py": update_package.file_hash(target)}}))
    files, deleted = update_package.ownership_plan(root, manifest)
    assert "bot/main.py" in files and "bot/Main.py" not in deleted


def test_existing_parent_file_conflict_is_detected_during_preparation(tmp_path):
    _, manifest = update_archive(tmp_path)
    root = tmp_path / "app"
    root.mkdir()
    (root / "bot").write_text("local file")
    with pytest.raises(RuntimeError, match="父级不是目录"):
        update_package.ownership_plan(root, manifest)
    assert (root / "bot").read_text() == "local file"


def test_downloader_resumes_only_the_same_etag_and_range(monkeypatch, tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("VERSION", "3.1.0")
    payload = output.getvalue()
    split = len(payload) // 2
    requests = []

    class Response:
        def __init__(self, resumed):
            self.status = 206 if resumed else 200
            self.headers = {"ETag": '"immutable"', "Content-Length": str(len(payload) - split if resumed else len(payload))}
            if resumed:
                self.headers["Content-Range"] = f"bytes {split}-{len(payload)-1}/{len(payload)}"
            self.resumed, self.calls = resumed, 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            self.calls += 1
            if self.resumed:
                return payload[split:] if self.calls == 1 else b""
            if self.calls == 1:
                return payload[:split]
            raise OSError("connection dropped")

    class Opener:
        def open(self, request, **_):
            requests.append(request)
            return Response(len(requests) > 1)

    monkeypatch.setattr(updater, "_build_url_opener", Opener)
    monkeypatch.setattr(updater.time, "sleep", lambda _: None)
    target = tmp_path / "download.zip"
    updater._download_file("https://example.invalid/asset", target)
    assert target.read_bytes() == payload
    assert requests[1].get_header("Range") == f"bytes={split}-"
    assert requests[1].get_header("If-range") == '"immutable"'


def test_downloader_cancellation_is_not_retried(monkeypatch, tmp_path):
    class Cancelled(RuntimeError):
        pass

    def progress(_):
        raise Cancelled("cancelled")

    monkeypatch.setattr(updater, "_build_url_opener", lambda: None)
    with pytest.raises(Cancelled):
        updater._download_file("https://example.invalid", tmp_path / "update.zip", progress)


def test_tar_root_directory_is_accepted(tmp_path):
    package = tmp_path / "root.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        item = tarfile.TarInfo("./VERSION")
        item.size = 5
        archive.addfile(item, io.BytesIO(b"3.1.0"))
    with update_package.archive_entries(package) as entries:
        assert [item[0] for item in entries] == ["VERSION"]


def test_offline_payload_is_frozen_then_applied_and_restored_without_user_data(monkeypatch, tmp_path):
    from scripts.update_transaction import Transaction
    package, _ = update_archive(tmp_path, additions={".env": b"package defaults", ".web_announcements.json": b"{}"})
    root = tmp_path / "installation"
    root.mkdir()
    (root / "VERSION").write_text("3.0.0")
    (root / ".env").write_text("user secret")
    (root / ".web_announcements.json").write_text("user announcements")
    (root / update_package.MANIFEST).write_text(json.dumps({"files": {"VERSION": update_package.file_hash(root / "VERSION")}}))
    monkeypatch.setattr(updater, "detect_update_package_kind", lambda *args: "installer")
    job_dir = tmp_path / "state" / "jobs" / "job"
    prepared = updater.prepare_update_payload(root, package, job_dir, expected_version="3.1.0")
    assert Path(prepared["package_path"]).parent == job_dir
    assert (root / "VERSION").read_text() == "3.0.0"
    assert ".env" not in prepared["files"] and ".web_announcements.json" not in prepared["files"]
    package.unlink()
    assert Path(prepared["package_path"]).is_file()
    transaction = Transaction(root, job_dir / "transaction")
    transaction.apply(Path(prepared["staging_dir"]), prepared["files"], prepared["delete_paths"],
                      expected_hashes=prepared["original_hashes"])
    assert (root / "VERSION").read_text() == "3.1.0"
    transaction.recover()
    assert (root / "VERSION").read_text() == "3.0.0"
    assert (root / ".env").read_text() == "user secret"
    assert (root / ".web_announcements.json").read_text() == "user announcements"


def test_release_manifest_records_build_identity_and_only_named_pi_extensions(monkeypatch, tmp_path):
    package, _ = update_archive(tmp_path)
    stage = tmp_path / "stage"
    update_package.inspect_package(package, staging_dir=stage)
    extension = "data/pi-home/.pi/agent/extensions/tcb-cluster.ts"
    (stage / extension).parent.mkdir(parents=True)
    (stage / extension).write_text("bundled")
    (stage / "data/pi-home/.pi/agent/models.json").write_text("private")
    monkeypatch.setattr(update_package, "_git", lambda root, *args: "c" * 40 if args[0] == "rev-parse" else " M bot/main.py")
    manifest = update_package.create_manifest(stage, tmp_path, managed_data_files=[extension])
    assert manifest["commit"] == "c" * 40 and manifest["dirty"] is True
    assert extension in manifest["files"]
    assert "data/pi-home/.pi/agent/models.json" not in manifest["files"]
    assert manifest["frontend"]["files"]["front/dist/index.html"] == update_package.file_hash(stage / "front/dist/index.html")


def test_build_identity_rejects_new_commit_or_changed_dirty_contents(monkeypatch, tmp_path):
    data = {"commit": "a" * 40, "diff": "first edit"}
    def git(root, *args):
        return data["commit"] if args[0] == "rev-parse" else data["diff"] if args[0] == "diff" else " M bot/main.py"
    monkeypatch.setattr(update_package, "_git", git)
    identity = update_package.source_identity(tmp_path)
    monkeypatch.setenv("TCB_RELEASE_SOURCE_COMMIT", identity["commit"])
    monkeypatch.setenv("TCB_RELEASE_SOURCE_FINGERPRINT", identity["fingerprint"])
    data["diff"] = "second edit"
    with pytest.raises(ValueError, match="工作树发生变化"):
        update_package.verify_source_identity(tmp_path)
    data["diff"], data["commit"] = "first edit", "b" * 40
    with pytest.raises(ValueError, match="源码提交"):
        update_package.verify_source_identity(tmp_path)


def test_release_manifest_rejects_stale_frontend_source_snapshot(monkeypatch, tmp_path):
    package, _ = update_archive(tmp_path)
    stage = tmp_path / "stage"
    update_package.inspect_package(package, staging_dir=stage)
    info_path = stage / "front/dist/build-info.json"
    info = json.loads(info_path.read_text())
    info["source_files"]["VERSION"] = "0" * 64
    info_path.write_text(json.dumps(info))
    monkeypatch.setattr(update_package, "_git", lambda root, *args: "c" * 40 if args[0] == "rev-parse" else "")
    with pytest.raises(ValueError, match="前端构建后源码发生变化"):
        update_package.create_manifest(stage, tmp_path)
