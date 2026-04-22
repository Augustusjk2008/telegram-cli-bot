from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.plugins.registry import PluginRegistry
from bot.plugins.runtime import PluginRuntime


def _write_echo_plugin(root: Path) -> None:
    plugin_dir = root / "echo-wave"
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
        result = {"name": "echo-wave"}
    elif method == "plugin.render_view":
        result = {
            "renderer": "waveform",
            "title": "trace.vcd",
            "payload": {
                "path": request["params"]["input"]["path"],
                "timescale": "1ns",
                "startTime": 0,
                "endTime": 10,
                "tracks": [],
            },
        }
    elif method == "plugin.shutdown":
        result = {"ok": True}
    else:
        result = {"method": method}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\\n")
    sys.stdout.flush()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 1,
        "id": "echo-wave",
        "name": "Echo Wave",
        "version": "0.1.0",
        "description": "runtime test",
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
        },
        "views": [{"id": "waveform", "title": "波形预览", "renderer": "waveform"}],
        "fileHandlers": [],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_large_payload_plugin(root: Path) -> None:
    plugin_dir = root / "large-wave"
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text(
        """
import json
import sys

large_blob = "x" * 100_000

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "plugin.initialize":
        result = {"name": "large-wave"}
    elif method == "plugin.render_view":
        result = {
            "renderer": "waveform",
            "title": "large.vcd",
            "payload": {
                "path": request["params"]["input"]["path"],
                "timescale": "1ns",
                "startTime": 0,
                "endTime": 10,
                "tracks": [],
                "blob": large_blob,
            },
        }
    elif method == "plugin.shutdown":
        result = {"ok": True}
    else:
        result = {"method": method}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\\n")
    sys.stdout.flush()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 1,
        "id": "large-wave",
        "name": "Large Wave",
        "version": "0.1.0",
        "description": "large runtime test",
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
        },
        "views": [{"id": "waveform", "title": "波形预览", "renderer": "waveform"}],
        "fileHandlers": [],
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

SESSIONS = {}

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    params = request.get("params") or {}
    if method == "plugin.initialize":
        result = {"ok": True}
    elif method == "plugin.open_view":
        session_id = "session-1"
        SESSIONS[session_id] = True
        result = {
            "renderer": "waveform",
            "title": "demo.vcd",
            "mode": "session",
            "sessionId": session_id,
            "summary": {
                "path": params["input"]["path"],
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
            "tracks": [
                {
                    "signalId": "tb.clk",
                    "label": "tb.clk",
                    "width": 1,
                    "segments": [{"start": params["startTime"], "end": params["endTime"], "value": "1"}],
                }
            ],
        }
    elif method == "plugin.dispose_view":
        SESSIONS.pop(params["sessionId"], None)
        result = {"disposed": True}
    elif method == "plugin.shutdown":
        result = {"ok": True}
    else:
        result = {"method": method}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\\n")
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
        "description": "runtime session test",
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
        },
        "views": [
            {"id": "waveform", "title": "波形预览", "renderer": "waveform", "viewMode": "session", "dataProfile": "heavy"}
        ],
        "fileHandlers": [],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.asyncio
async def test_plugin_runtime_initializes_renders_and_shuts_down(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_echo_plugin(plugins_root)
    registry = PluginRegistry(plugins_root)
    manifest = registry.discover()["echo-wave"]

    runtime = PluginRuntime()
    result = await runtime.render_view(manifest, "waveform", {"path": "waves/trace.vcd"})

    assert result["renderer"] == "waveform"
    assert result["payload"]["path"] == "waves/trace.vcd"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_reads_large_jsonrpc_response_lines(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_large_payload_plugin(plugins_root)
    registry = PluginRegistry(plugins_root)
    manifest = registry.discover()["large-wave"]

    runtime = PluginRuntime()
    result = await runtime.render_view(manifest, "waveform", {"path": "waves/large.vcd"})

    assert result["renderer"] == "waveform"
    assert len(result["payload"]["blob"]) == 100_000
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_opens_session_queries_window_and_disposes(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_session_wave_plugin(plugins_root)
    manifest = PluginRegistry(plugins_root).discover()["session-wave"]

    runtime = PluginRuntime()
    opened = await runtime.open_view(manifest, "waveform", {"path": "waves/demo.vcd"})
    assert opened["mode"] == "session"
    assert opened["sessionId"]

    window = await runtime.get_view_window(
        manifest,
        opened["sessionId"],
        {"startTime": 0, "endTime": 40, "signalIds": ["tb.clk"], "pixelWidth": 1200},
    )
    assert [track["signalId"] for track in window["tracks"]] == ["tb.clk"]

    disposed = await runtime.dispose_view(manifest, opened["sessionId"])
    assert disposed["disposed"] is True
    await runtime.shutdown()
