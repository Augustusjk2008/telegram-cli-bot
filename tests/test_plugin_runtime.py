from __future__ import annotations

import asyncio
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


def _write_hanging_plugin(root: Path) -> None:
    plugin_dir = root / "hanging-wave"
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
        result = {"name": "hanging-wave"}
    elif method == "plugin.shutdown":
        result = {"ok": True}
    elif method == "plugin.render_view":
        continue
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
        "id": "hanging-wave",
        "name": "Hanging Wave",
        "version": "0.1.0",
        "description": "timeout runtime test",
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


def _write_host_call_plugin(root: Path, *, plugin_id: str, permissions: dict[str, bool]) -> None:
    plugin_dir = root / plugin_id
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text(
        """
import json
import sys

next_request_id = 9000


def emit(message):
    sys.stdout.write(json.dumps(message) + "\\n")
    sys.stdout.flush()


def call_host(method, params):
    global next_request_id
    request_id = next_request_id
    next_request_id += 1
    emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        message = json.loads(line)
        if int(message.get("id") or 0) == request_id and "method" not in message:
            return message


for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "plugin.initialize":
        emit({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}})
    elif method == "plugin.render_view":
        response = call_host("host.workspace.read_text", {"path": "reports/timing.rpt", "encoding": "utf-8"})
        if response.get("error"):
            emit({"jsonrpc": "2.0", "id": request["id"], "error": response["error"]})
        else:
            content = response["result"]["content"].strip()
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "renderer": "table",
                        "title": "timing.rpt",
                        "payload": {
                            "columns": [{"id": "path", "title": "Path"}],
                            "rows": [{"id": content, "cells": {"path": content}}],
                        },
                    },
                }
            )
    elif method == "plugin.shutdown":
        emit({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}})
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 2,
        "id": plugin_id,
        "name": plugin_id,
        "version": "0.1.0",
        "description": "host api runtime test",
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
            "permissions": permissions,
        },
        "views": [{"id": "timing-table", "title": "Timing", "renderer": "table"}],
        "fileHandlers": [],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_unicode_plugin(root: Path) -> None:
    plugin_dir = root / "unicode-tree"
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
            "renderer": "table",
            "title": "文件夹大纲",
            "payload": {
                "columns": [{"id": "label", "title": "标签"}],
                "rows": [{"id": "row-1", "cells": {"label": "中文节点"}}],
            },
        }
    elif method == "plugin.shutdown":
        result = {"ok": True}
    else:
        result = {"ok": True}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}, ensure_ascii=False) + "\\n")
    sys.stdout.flush()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 2,
        "id": "unicode-tree",
        "name": "Unicode Tree",
        "version": "0.1.0",
        "description": "unicode runtime test",
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
            "permissions": {},
        },
        "views": [{"id": "tree", "title": "树", "renderer": "table"}],
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
    result = await runtime.render_view("main", manifest, "waveform", {"path": "waves/trace.vcd"})

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
    result = await runtime.render_view("main", manifest, "waveform", {"path": "waves/large.vcd"})

    assert result["renderer"] == "waveform"
    assert len(result["payload"]["blob"]) == 100_000
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_times_out_and_stops_unresponsive_plugin(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_hanging_plugin(plugins_root)
    manifest = PluginRegistry(plugins_root).discover()["hanging-wave"]

    runtime = PluginRuntime(call_timeout_seconds=0.1)
    with pytest.raises(RuntimeError, match="插件响应超时"):
        await runtime.render_view("main", manifest, "waveform", {"path": "waves/hang.vcd"})

    assert ("main", "hanging-wave") not in runtime._processes
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_opens_session_queries_window_and_disposes(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_session_wave_plugin(plugins_root)
    manifest = PluginRegistry(plugins_root).discover()["session-wave"]

    runtime = PluginRuntime()
    opened = await runtime.open_view("main", manifest, "waveform", {"path": "waves/demo.vcd"})
    assert opened["mode"] == "session"
    assert opened["sessionId"]

    window = await runtime.get_view_window(
        "main",
        manifest,
        opened["sessionId"],
        {"startTime": 0, "endTime": 40, "signalIds": ["tb.clk"], "pixelWidth": 1200},
    )
    assert [track["signalId"] for track in window["tracks"]] == ["tb.clk"]

    disposed = await runtime.dispose_view("main", manifest, opened["sessionId"])
    assert disposed["disposed"] is True
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_handles_plugin_initiated_host_read_text(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    report = repo_root / "reports" / "timing.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("path-1\n", encoding="utf-8")
    plugins_root = tmp_path / "plugins"
    _write_host_call_plugin(plugins_root, plugin_id="timing-report", permissions={"workspaceRead": True})
    manifest = PluginRegistry(plugins_root).discover()["timing-report"]

    runtime = PluginRuntime(workspace_root_for=lambda _alias: repo_root)
    result = await runtime.render_view("main", manifest, "timing-table", {"path": "reports/timing.rpt"})

    assert result["payload"]["rows"][0]["id"] == "path-1"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_rejects_host_call_without_permission(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    report = repo_root / "reports" / "timing.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("path-1\n", encoding="utf-8")
    plugins_root = tmp_path / "plugins"
    _write_host_call_plugin(plugins_root, plugin_id="denied-report", permissions={})
    manifest = PluginRegistry(plugins_root).discover()["denied-report"]

    runtime = PluginRuntime(workspace_root_for=lambda _alias: repo_root)
    with pytest.raises(RuntimeError, match="permission_denied"):
        await runtime.render_view("main", manifest, "timing-table", {"path": "reports/timing.rpt"})
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_scopes_processes_by_bot_alias(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_echo_plugin(plugins_root)
    manifest = PluginRegistry(plugins_root).discover()["echo-wave"]

    runtime = PluginRuntime(workspace_root_for=lambda _alias: tmp_path)
    await runtime.render_view("main", manifest, "waveform", {"path": "waves/a.vcd"})
    await runtime.render_view("lab", manifest, "waveform", {"path": "waves/a.vcd"})

    assert ("main", "echo-wave") in runtime._processes
    assert ("lab", "echo-wave") in runtime._processes
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_plugin_runtime_forces_utf8_stdio_for_child_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugins_root = tmp_path / "plugins"
    _write_unicode_plugin(plugins_root)
    manifest = PluginRegistry(plugins_root).discover()["unicode-tree"]
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    runtime = PluginRuntime(workspace_root_for=lambda _alias: tmp_path)
    result = await runtime.render_view("main", manifest, "tree", {"path": "demo"})

    assert result["title"] == "文件夹大纲"
    assert result["payload"]["rows"][0]["cells"]["label"] == "中文节点"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_stops_idle_plugin_processes(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_echo_plugin(plugins_root)
    manifest = PluginRegistry(plugins_root).discover()["echo-wave"]
    runtime = PluginRuntime(call_timeout_seconds=2.0, idle_timeout_seconds=0.01)

    await runtime.render_view("main", manifest, "waveform", {"path": "demo.txt"})
    assert runtime.active_process_count() == 1

    await asyncio.sleep(0.03)
    stopped = await runtime.evict_idle_processes()

    assert stopped == 1
    assert runtime.active_process_count() == 0
    await runtime.shutdown()
