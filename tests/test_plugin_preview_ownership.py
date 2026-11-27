import asyncio
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter

from bot.plugins.service import PluginService
from bot.plugins.view_sessions import PluginViewSessionRecord, PluginViewSessionStore


@pytest.mark.asyncio
async def test_isolated_csv_previews_release_independently_and_pdf_snapshots_share_artifacts(tmp_path):
    bundled = Path(__file__).resolve().parents[1] / "examples" / "plugins"
    installed = tmp_path / "plugins"
    for name in ("csv-preview", "pdf-preview"):
        shutil.copytree(bundled / name, installed / name)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "results.csv").write_text("channel,value\na,7\nb,12\n", encoding="utf-8")
    pdf = PdfWriter()
    for _ in range(2):
        pdf.add_blank_page(width=360, height=480)
    pdf.write(workspace / "manual.pdf")
    service = PluginService(tmp_path, installed, workspace_root_for=lambda _alias: workspace)

    async def open_file(filename, isolated):
        target = service.resolve_file_target(str(workspace / filename))
        assert target["kind"] == "plugin_view"
        return await service.open_view(
            bot_alias="main", plugin_id=target["pluginId"], view_id=target["viewId"],
            input_payload=target["input"], audit_context={}, isolated_session=isolated,
        )

    try:
        desktop, first, second = await asyncio.gather(*(open_file("results.csv", isolated) for isolated in (False, True, True)))
        assert len({item["sessionId"] for item in (desktop, first, second)}) == 3
        assert (await open_file("results.csv", False))["sessionId"] == desktop["sessionId"]
        await service.dispose_view(bot_alias="main", plugin_id="csv-preview", session_id=first["sessionId"])
        for surviving in (desktop, second):
            window = await service.get_view_window(
                bot_alias="main", plugin_id="csv-preview", session_id=surviving["sessionId"],
                request_payload={"offset": 1, "limit": 1}, audit_context={},
            )
            assert window["totalRows"] == 2 and len(window["rows"]) == 1
            await service.dispose_view(bot_alias="main", plugin_id="csv-preview", session_id=surviving["sessionId"])
        assert service.sessions.records() == []

        portrait = await open_file("manual.pdf", True)
        desktop_pdf = await open_file("manual.pdf", False)
        assert portrait["mode"] == "snapshot"
        artifact = portrait["payload"]["pdf"]["artifactId"]
        assert desktop_pdf["payload"]["pdf"]["artifactId"] == artifact
        assert service.get_artifact(bot_alias="main", artifact_id=artifact).path.read_bytes() == (workspace / "manual.pdf").read_bytes()
    finally:
        await service.shutdown()


def test_disposing_a_late_session_only_releases_the_owning_bot_and_plugin():
    store = PluginViewSessionStore()
    old = PluginViewSessionRecord(
        bot_alias="old", plugin_id="waveform", view_id="wave", session_id="wave-session-1", renderer="waveform",
        source_identity="source", source_fingerprint="version", resolved_input={}, opened_payload={},
    )
    current = replace(old, bot_alias="current")
    store.replace(old)
    store.replace(current)
    assert store.remove("current", "other-plugin", current.session_id) is None
    assert store.remove(old.bot_alias, old.plugin_id, old.session_id) is old
    assert store.get(current.bot_alias, current.plugin_id, current.session_id) is current
