from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.plugins.service import PluginService


def _write_wave_plugin(root: Path) -> None:
    plugin_dir = root / "vivado-waveform"
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "plugin.initialize":
        result = {"ok": True}
    elif method == "plugin.render_view":
        result = {
            "renderer": "waveform",
            "title": "trace.vcd",
            "payload": {
                "path": request["params"]["input"]["path"],
                "timescale": "1ns",
                "startTime": 0,
                "endTime": 20,
                "tracks": [{"signalId": "clk", "label": "tb.clk", "width": 1, "segments": []}],
            },
        }
    else:
        result = {"ok": True}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\\n")
    sys.stdout.flush()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 1,
        "id": "vivado-waveform",
        "name": "Vivado Waveform",
        "version": "0.1.0",
        "description": "wave plugin",
        "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
        "views": [{"id": "waveform", "title": "波形预览", "renderer": "waveform"}],
        "fileHandlers": [{"id": "wave-vcd", "label": "VCD 波形预览", "extensions": [".vcd"], "viewId": "waveform"}],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_session_wave_plugin(root: Path) -> None:
    plugin_dir = root / "session-wave"
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text(
        """
import json
import sys
from pathlib import Path

counter = 0

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    params = request.get("params") or {}
    if method == "plugin.initialize":
        result = {"ok": True}
    elif method == "plugin.open_view":
        counter += 1
        path = Path(params["input"]["path"]).resolve()
        result = {
            "renderer": "waveform",
            "title": path.name,
            "mode": "session",
            "sessionId": f"session-{counter}",
            "summary": {
                "path": str(path),
                "timescale": "1ns",
                "startTime": 0,
                "endTime": 120,
                "signals": [{"signalId": "tb.clk", "label": "tb.clk", "width": 1, "kind": "scalar"}],
                "defaultSignalIds": ["tb.clk"],
            },
            "initialWindow": {"startTime": 0, "endTime": 40, "tracks": []},
        }
    elif method == "plugin.get_view_window":
        result = {
            "startTime": params["startTime"],
            "endTime": params["endTime"],
            "tracks": [{"signalId": "tb.clk", "label": "tb.clk", "width": 1, "segments": []}],
        }
    elif method == "plugin.dispose_view":
        result = {"disposed": True}
    else:
        result = {"ok": True}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}, ensure_ascii=False) + "\\n")
    sys.stdout.flush()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 1,
        "id": "session-wave",
        "name": "Session Wave",
        "version": "0.1.0",
        "description": "session wave plugin",
        "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
        "views": [{"id": "waveform", "title": "波形预览", "renderer": "waveform", "viewMode": "session", "dataProfile": "heavy"}],
        "fileHandlers": [{"id": "wave-vcd", "label": "VCD 波形预览", "extensions": [".vcd"], "viewId": "waveform"}],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.asyncio
async def test_plugin_service_resolves_vcd_and_writes_audit(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_wave_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    listed = service.list_plugins()
    assert listed[0]["id"] == "vivado-waveform"

    target = service.resolve_file_target("waves/demo.vcd")
    assert target["kind"] == "plugin_view"
    payload = await service.render_view(
        plugin_id="vivado-waveform",
        view_id="waveform",
        input_payload={"path": "waves/demo.vcd"},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    assert payload["renderer"] == "waveform"
    audit_files = list((repo_root / ".plugins" / "audit").glob("*.jsonl"))
    assert audit_files
    await service.shutdown()


def test_plugin_service_defaults_to_tcb_plugins_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    expected = tmp_path / "home" / ".tcb" / "plugins"
    monkeypatch.setattr("bot.plugins.service.default_plugins_root", lambda: expected)

    service = PluginService(repo_root)

    assert service.plugins_root == expected


@pytest.mark.asyncio
async def test_plugin_service_reuses_cached_session_until_source_changes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    wave_file = repo_root / "waves" / "demo.vcd"
    wave_file.parent.mkdir()
    wave_file.write_text("$enddefinitions $end\n#0\n", encoding="utf-8")

    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_session_wave_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    reopened = await service.open_view(
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert reopened["sessionId"] == opened["sessionId"]

    wave_file.write_text("$enddefinitions $end\n#0\n1!\n", encoding="utf-8")
    refreshed = await service.open_view(
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    window = await service.get_view_window(
        plugin_id="session-wave",
        session_id=refreshed["sessionId"],
        request_payload={"startTime": 0, "endTime": 20, "signalIds": ["tb.clk"], "pixelWidth": 800},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert refreshed["sessionId"] != opened["sessionId"]
    assert window["tracks"][0]["signalId"] == "tb.clk"

    audit_file = next((repo_root / ".plugins" / "audit").glob("*.jsonl"))
    records = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    assert {record["event"] for record in records} >= {"open_view", "query_window"}
    assert all(record["payload_bytes"] > 0 for record in records if record["event"] in {"open_view", "query_window"})
    await service.shutdown()
