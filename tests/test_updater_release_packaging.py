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
