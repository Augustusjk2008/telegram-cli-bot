from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from bot import updater


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
