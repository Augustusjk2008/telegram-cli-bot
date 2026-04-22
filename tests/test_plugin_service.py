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
