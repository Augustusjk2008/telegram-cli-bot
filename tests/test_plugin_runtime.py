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
