from __future__ import annotations

import json
import zipfile
from pathlib import Path

from bot import updater


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

    logs: list[str] = []
    changed = updater._sync_runtime_announcements_from_package(
        package_path,
        [".web_announcements.json"],
        log_callback=logs.append,
    )

    saved = json.loads(runtime_content.read_text(encoding="utf-8"))
    assert changed is True
    assert [item["id"] for item in saved["items"]] == ["ann-old", "ann-new"]
    assert "已同步发布公告到本地公告中心。" in logs


def test_release_scripts_force_root_base_and_export_announcements() -> None:
    ps1 = Path(".release-local/publish-release.ps1").read_text(encoding="utf-8")
    sh = Path(".release-local/publish-release.sh").read_text(encoding="utf-8")
    portable = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert "function Invoke-ReleaseFrontBuild" in ps1
    assert 'SetEnvironmentVariable("TCB_FRONT_BUILD_ROOT_BASE", "1", "Process")' in ps1
    assert "Invoke-FrontDistAssetCheck" in ps1
    assert "Export-ReleaseAnnouncements -DestinationRoot $StageDir" in ps1

    assert "invoke_release_front_build" in sh
    assert "TCB_FRONT_BUILD_ROOT_BASE=1" in sh
    assert "invoke_front_dist_asset_check" in sh
    assert 'export_release_announcements "$stage_dir"' in sh

    assert "Export-ReleaseAnnouncements -DestinationRoot $DestinationRoot" in portable


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


def test_release_checks_run_complete_backend_tests_and_frontend_lint() -> None:
    ps1 = Path(".release-local/publish-release.ps1").read_text(encoding="utf-8")
    sh = Path(".release-local/publish-release.sh").read_text(encoding="utf-8")
    portable = Path(".release-local/portable-win/build-portable.ps1").read_text(encoding="utf-8")

    assert '"-m", "pytest",\n        "tests",\n        "examples/plugins",\n        "-q"' in ps1
    assert "tests/test_main_web.py" not in ps1
    assert '"run",\n        "test:gate"' in ps1
    assert '"run",\n        "lint"' in ps1

    assert '"$python_bin" -m pytest tests examples/plugins -q' in sh
    assert "tests/test_main_web.py" not in sh
    assert '"$npm_bin" run test:gate' in sh
    assert '"$npm_bin" run lint' in sh

    assert '"-m", "pytest",\n        "tests",\n        "examples/plugins",\n        "--ignore=tests/test_start_scripts.py",\n        "-q"' in portable
    assert "tests/test_main_web.py" not in portable
