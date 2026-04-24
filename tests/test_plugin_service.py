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


def _write_timing_report_plugin(root: Path) -> None:
    plugin_dir = root / "timing-report"
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text(
        """
import json
import sys
from pathlib import Path

sessions = {}
next_request_id = 9000
session_counter = 0


def emit(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\\n")
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


def build_rows(offset, limit):
    rows = []
    for index in range(offset, min(offset + limit, 5)):
        row_id = f"path-{index + 1}"
        rows.append(
            {
                "id": row_id,
                "cells": {"path": row_id, "slack": f"{0.1 * (index + 1):.1f}"},
                "actions": [{"id": "export-row", "label": "导出行", "target": "plugin", "location": "row"}],
            }
        )
    return rows


for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    params = request.get("params") or {}
    context = params.get("context") or {}
    if method == "plugin.initialize":
        emit({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}})
    elif method == "plugin.open_view":
        session_counter += 1
        session_id = f"{context['host']['botAlias']}-session-{session_counter}"
        path = str(Path(params["input"]["path"]).resolve())
        sessions[session_id] = path
        emit(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "renderer": "table",
                    "title": Path(path).name,
                    "mode": "session",
                    "sessionId": session_id,
                    "summary": {
                        "path": path,
                        "columns": [
                            {"id": "path", "title": "Path"},
                            {"id": "slack", "title": "Slack", "sortable": True},
                        ],
                        "defaultPageSize": context["plugin"]["config"].get("defaultPageSize", 100),
                    },
                    "initialWindow": {"rows": build_rows(0, 2), "totalRows": 5},
                },
            }
        )
    elif method == "plugin.get_view_window":
        offset = int(params.get("offset") or 0)
        limit = int(params.get("limit") or 2)
        emit(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "rows": build_rows(offset, limit),
                    "totalRows": 5,
                    "appliedSort": params.get("sort") or {},
                },
            }
        )
    elif method == "plugin.invoke_action":
        path = sessions.get(str(params.get("sessionId") or "")) or str(Path(params["payload"]["path"]).resolve())
        report_response = call_host("host.workspace.read_text", {"path": path, "encoding": "utf-8"})
        if report_response.get("error"):
            emit({"jsonrpc": "2.0", "id": request["id"], "error": report_response["error"]})
            continue
        export_response = call_host(
            "host.temp.write_artifact",
            {
                "filename": "timing.csv",
                "text": report_response["result"]["content"],
                "encoding": "utf-8",
            },
        )
        if export_response.get("error"):
            emit({"jsonrpc": "2.0", "id": request["id"], "error": export_response["error"]})
            continue
        emit(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "message": "已导出",
                    "refresh": "session",
                    "hostEffects": [
                        {
                            "type": "download_artifact",
                            "artifactId": export_response["result"]["artifactId"],
                            "filename": "timing.csv",
                        }
                    ],
                },
            }
        )
    elif method == "plugin.dispose_view":
        sessions.pop(str(params.get("sessionId") or ""), None)
        emit({"jsonrpc": "2.0", "id": request["id"], "result": {"disposed": True}})
    elif method == "plugin.shutdown":
        emit({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}})
    else:
        emit({"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}})
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 2,
        "id": "timing-report",
        "name": "Timing Report",
        "version": "0.2.0",
        "description": "table plugin",
        "config": {"defaultPageSize": 100},
        "runtime": {
            "type": "python",
            "entry": "backend/main.py",
            "protocol": "jsonrpc-stdio",
            "permissions": {"workspaceRead": True, "tempArtifacts": True},
        },
        "configSchema": {
            "title": "Timing Settings",
            "sections": [
                {
                    "id": "display",
                    "fields": [
                        {"key": "defaultPageSize", "label": "每页", "type": "integer", "default": 100, "minimum": 10}
                    ],
                }
            ],
        },
        "views": [{"id": "timing-table", "title": "Timing Paths", "renderer": "table", "viewMode": "session", "dataProfile": "heavy"}],
        "fileHandlers": [{"id": "timing-rpt", "label": "Timing 报告", "extensions": [".rpt"], "viewId": "timing-table"}],
        "catalogActions": [{"id": "export-all", "label": "导出 CSV", "target": "plugin", "location": "catalog"}],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_minimal_plugin(root: Path, plugin_id: str, *, name: str) -> None:
    plugin_dir = root / plugin_id
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text("print('plugin')\n", encoding="utf-8")
    cache_dir = plugin_dir / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "main.cpython-312.pyc").write_bytes(b"pyc")
    manifest = {
        "schemaVersion": 1,
        "id": plugin_id,
        "name": name,
        "version": "0.1.0",
        "description": "install test plugin",
        "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
        "views": [],
        "fileHandlers": [],
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
        bot_alias="main",
        plugin_id="vivado-waveform",
        view_id="waveform",
        input_payload={"path": "waves/demo.vcd"},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    assert payload["renderer"] == "waveform"
    audit_files = list((repo_root / ".plugins" / "audit").glob("*.jsonl"))
    assert audit_files
    await service.shutdown()


@pytest.mark.asyncio
async def test_plugin_service_updates_plugin_enabled_state_and_config(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_wave_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    updated = await service.update_plugin("vivado-waveform", enabled=False, config={"lodEnabled": False})

    manifest_path = plugins_root / "vivado-waveform" / "plugin.json"
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert updated["enabled"] is False
    assert updated["config"]["lodEnabled"] is False
    assert saved["enabled"] is False
    assert saved["config"]["lodEnabled"] is False
    assert service.resolve_file_target("waves/demo.vcd") == {"kind": "file"}
    with pytest.raises(KeyError, match="禁用"):
        await service.render_view(
            bot_alias="main",
            plugin_id="vivado-waveform",
            view_id="waveform",
            input_payload={"path": "waves/demo.vcd"},
            audit_context={"account_id": "member_1", "bot_alias": "main"},
        )
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
        bot_alias="main",
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    reopened = await service.open_view(
        bot_alias="main",
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert reopened["sessionId"] == opened["sessionId"]

    wave_file.write_text("$enddefinitions $end\n#0\n1!\n", encoding="utf-8")
    refreshed = await service.open_view(
        bot_alias="main",
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    window = await service.get_view_window(
        bot_alias="main",
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


@pytest.mark.asyncio
async def test_plugin_service_passes_generic_window_payload_for_non_waveform_session(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    report = repo_root / "reports" / "timing.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("slack,path-1\n", encoding="utf-8")
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_timing_report_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="timing-report",
        view_id="timing-table",
        input_payload={"path": str(report)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    payload = await service.get_view_window(
        bot_alias="main",
        plugin_id="timing-report",
        session_id=opened["sessionId"],
        request_payload={"offset": 0, "limit": 2, "sort": {"columnId": "slack", "direction": "asc"}},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert opened["renderer"] == "table"
    assert payload["rows"][0]["id"] == "path-1"
    assert payload["appliedSort"]["columnId"] == "slack"
    await service.shutdown()


@pytest.mark.asyncio
async def test_plugin_service_scopes_session_cache_by_bot_alias(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    report = repo_root / "reports" / "timing.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("slack,path-1\n", encoding="utf-8")
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_timing_report_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    main_opened = await service.open_view(
        bot_alias="main",
        plugin_id="timing-report",
        view_id="timing-table",
        input_payload={"path": str(report)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    lab_opened = await service.open_view(
        bot_alias="lab",
        plugin_id="timing-report",
        view_id="timing-table",
        input_payload={"path": str(report)},
        audit_context={"account_id": "member_2", "bot_alias": "lab"},
    )

    assert main_opened["sessionId"].startswith("main-session-")
    assert lab_opened["sessionId"].startswith("lab-session-")
    assert main_opened["sessionId"] != lab_opened["sessionId"]
    await service.shutdown()


@pytest.mark.asyncio
async def test_plugin_service_invokes_action_and_reads_bot_scoped_artifact(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    report = repo_root / "reports" / "timing.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("path,slack\npath-1,0.1\n", encoding="utf-8")
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_timing_report_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    opened = await service.open_view(
        bot_alias="main",
        plugin_id="timing-report",
        view_id="timing-table",
        input_payload={"path": str(report)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    result = await service.invoke_action(
        bot_alias="main",
        plugin_id="timing-report",
        view_id="timing-table",
        session_id=opened["sessionId"],
        action_id="export-all",
        payload={"path": str(report)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    effect = result["hostEffects"][0]
    artifact = service.get_artifact(bot_alias="main", artifact_id=effect["artifactId"])

    assert result["refresh"] == "session"
    assert effect["type"] == "download_artifact"
    assert artifact.filename == "timing.csv"
    assert artifact.path.read_text(encoding="utf-8") == "path,slack\npath-1,0.1\n"
    with pytest.raises(KeyError, match="未知插件产物"):
        service.get_artifact(bot_alias="lab", artifact_id=effect["artifactId"])
    await service.shutdown()


@pytest.mark.asyncio
async def test_update_plugin_reloads_only_target_plugin_sessions(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    report = repo_root / "reports" / "timing.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("path,slack\npath-1,0.1\n", encoding="utf-8")
    wave_file = repo_root / "waves" / "demo.vcd"
    wave_file.parent.mkdir(exist_ok=True)
    wave_file.write_text("$enddefinitions $end\n#0\n", encoding="utf-8")
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_timing_report_plugin(plugins_root)
    _write_session_wave_plugin(plugins_root)

    service = PluginService(repo_root, plugins_root=plugins_root)
    timing_opened = await service.open_view(
        bot_alias="main",
        plugin_id="timing-report",
        view_id="timing-table",
        input_payload={"path": str(report)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    wave_opened = await service.open_view(
        bot_alias="main",
        plugin_id="session-wave",
        view_id="waveform",
        input_payload={"path": str(wave_file)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    updated = await service.update_plugin("timing-report", config={"defaultPageSize": 200})

    assert updated["config"]["defaultPageSize"] == 200
    with pytest.raises(KeyError, match="未知插件会话"):
        await service.get_view_window(
            bot_alias="main",
            plugin_id="timing-report",
            session_id=timing_opened["sessionId"],
            request_payload={"offset": 0, "limit": 2},
            audit_context={"account_id": "member_1", "bot_alias": "main"},
        )
    wave_window = await service.get_view_window(
        bot_alias="main",
        plugin_id="session-wave",
        session_id=wave_opened["sessionId"],
        request_payload={"startTime": 0, "endTime": 20, "signalIds": ["tb.clk"], "pixelWidth": 800},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert wave_window["tracks"][0]["signalId"] == "tb.clk"
    await service.shutdown()


@pytest.mark.asyncio
async def test_plugin_service_lists_installable_plugins_and_installs_folder(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    source_plugins_root = repo_root / "examples" / "plugins"
    source_plugins_root.mkdir(parents=True)
    _write_minimal_plugin(source_plugins_root, "fresh-plugin", name="Fresh Plugin")

    service = PluginService(repo_root, plugins_root=plugins_root, source_plugins_root=source_plugins_root)

    installable = service.list_installable_plugins()
    assert installable == [
        {
            "id": "fresh-plugin",
            "pluginId": "fresh-plugin",
            "name": "Fresh Plugin",
            "version": "0.1.0",
            "description": "install test plugin",
            "installed": False,
        }
    ]

    installed = await service.install_plugin(source_path=source_plugins_root / "fresh-plugin")

    assert installed["id"] == "fresh-plugin"
    assert (plugins_root / "fresh-plugin" / "plugin.json").exists()
    assert not (plugins_root / "fresh-plugin" / "__pycache__").exists()
    assert service.list_installable_plugins()[0]["installed"] is True
    await service.shutdown()
