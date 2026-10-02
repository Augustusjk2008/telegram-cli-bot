from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.registry import PluginRegistry
from bot.plugins.runtime import PluginRuntime
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_RUN_PLUGINS
from bot.web.server import WebApiServer


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/svg-pptx"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="white"/><text x="30" y="60">Original</text></svg>'
STUB_CORE = '''
def inspect_svg(source, config=None):
    return {"width": 640, "height": 360, "textCount": 1, "layerCount": 1, "warnings": [], "errors": []}
def export_pptx(source, config=None):
    return b"worker-export", inspect_svg(source, config)
'''


@pytest.fixture
def converter_available():
    assert (PLUGIN / "backend/converter.py").is_file()
    missing = [name for name in ("pptx", "resvg_py", "PIL", "tinycss2", "cssselect2", "defusedxml")
               if importlib.util.find_spec(name) is None]
    if missing:
        pytest.skip("converter dependencies unavailable: " + ", ".join(missing))


@asynccontextmanager
async def copied_plugin(tmp_path, *, config=None, limits=None, core=None, missing=False):
    plugin_dir = tmp_path / "installed plugins/svg-pptx"
    shutil.copytree(PLUGIN, plugin_dir, ignore=shutil.ignore_patterns("__pycache__"))
    if core is not None:
        (plugin_dir / "backend/converter.py").write_text(core, encoding="utf-8")
    if core is not None or missing:
        worker = plugin_dir / "backend/worker.py"
        override = "importlib.util.find_spec = lambda _: None" if missing else "DEPENDENCIES = {}"
        worker.write_text(worker.read_text(encoding="utf-8").replace(
            'if __name__ == "__main__":', override + '\n\nif __name__ == "__main__":'), encoding="utf-8")
    manifest_path = plugin_dir / "plugin.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["config"].update(config or {})
    if limits is not None:
        raw["runtime"]["limits"] = limits
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "sample.svg"
    source.write_bytes(SVG)
    artifacts = ArtifactStore(tmp_path)
    audit = []
    runtime = PluginRuntime(
        workspace_root_for=lambda _: workspace,
        host_api=PluginHostApi(artifacts), audit_hook=audit.append,
    )
    try:
        yield SimpleNamespace(
            root=plugin_dir, workspace=workspace, source=source, artifacts=artifacts,
            audit=audit, runtime=runtime, manifest=load_plugin_manifest(manifest_path),
        )
    finally:
        await runtime.shutdown()


async def open_svg(plugin, path="sample.svg"):
    return await plugin.runtime.open_view("main", plugin.manifest, "svg-pptx", {"path": path})


async def export_svg(plugin, view):
    return await plugin.runtime.invoke_action(
        "main", plugin.manifest, view_id="svg-pptx", session_id=view["sessionId"],
        action_id="export-pptx", payload={},
    )


@pytest.mark.asyncio
async def test_copied_plugin_rereads_svg_and_downloads_editable_slide(tmp_path, converter_available):
    async with copied_plugin(tmp_path) as plugin:
        resolution = PluginRegistry(plugin.root.parent).resolve_file_handler("sample.SVG")
        assert (resolution.plugin_id, resolution.view_id) == ("svg-pptx", "svg-pptx")
        plugin.source.write_bytes((plugin.root / "samples/sample.svg").read_bytes())
        opened = await open_svg(plugin)
        assert opened["summary"]["actions"][0]["disabled"] is False
        assert opened["initialWindow"]["rows"][0]["cells"]["textCount"] > 1
        plugin.source.write_bytes(SVG.replace(b"Original", "Fresh 中文".encode("utf-8")))
        exported = await export_svg(plugin, opened)
        effect, = exported["hostEffects"]
        assert effect["type"] == "download_artifact"
        record = plugin.artifacts.get(bot_alias="main", artifact_id=effect["artifactId"])
        assert record.filename == effect["filename"] == "sample.pptx"
        assert record.content_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        with ZipFile(record.path) as archive:
            slides = [name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
            assert slides == ["ppt/slides/slide1.xml"]
            slide = ET.fromstring(archive.read(slides[0]))
            text = "".join(slide.itertext())
            assert "Fresh 中文" in text and "Original" not in text
            assert slide.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}txBody") is not None
        host_calls = [event["host_api_method"] for event in plugin.audit if event["event"] == "host_api"]
        assert host_calls.count("host.workspace.read_bytes") == 2
        assert host_calls.count("host.temp.write_artifact") == 1

        # Exercise the real download handler without opening a listening socket.
        auth = AuthContext(user_id=1, token_used=True, capabilities={CAP_RUN_PLUGINS})
        manager = SimpleNamespace(
            main_profile=SimpleNamespace(alias="main"),
            managed_profiles={"other": SimpleNamespace(alias="other")},
            plugin_service=SimpleNamespace(get_artifact=plugin.artifacts.get),
        )
        server = SimpleNamespace(
            manager=manager, _with_capability=AsyncMock(return_value=auth),
            _manager_alias=lambda request: request.match_info["alias"],
        )
        request = make_mocked_request("GET", "/api/bots/main/plugins/artifacts/" + record.artifact_id,
                                      match_info={"alias": "main", "artifact_id": record.artifact_id})
        response = await WebApiServer.download_plugin_artifact(server, request)
        assert isinstance(response, web.FileResponse) and response._path == record.path
        assert response.headers["Content-Type"] == record.content_type
        assert response.headers["Content-Disposition"] == 'attachment; filename="sample.pptx"'
        other = make_mocked_request("GET", "/api/bots/other/plugins/artifacts/" + record.artifact_id,
                                    match_info={"alias": "other", "artifact_id": record.artifact_id})
        with pytest.raises(WebApiError) as caught:
            await WebApiServer.download_plugin_artifact(server, other)
        assert caught.value.code == "plugin_artifact_not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["https://example.invalid/image.png", "file:///C:/outside.png"])
async def test_external_resource_disables_export_even_after_source_changes(tmp_path, converter_available, resource):
    async with copied_plugin(tmp_path) as plugin:
        initial = await open_svg(plugin)
        assert initial["summary"]["actions"][0]["disabled"] is False
        plugin.source.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">'
            f'<image href="{resource}" width="100" height="100"/></svg>', encoding="utf-8")
        exported = await export_svg(plugin, initial)
        assert exported["message"] and not exported.get("hostEffects")
        reopened = await open_svg(plugin)
        assert reopened["summary"]["actions"][0]["disabled"] is True
        assert reopened["initialWindow"]["rows"][0]["cells"]["errors"]
        assert not plugin.artifacts._records


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["not-installed", "import-failure"])
async def test_missing_dependencies_keep_view_open_with_exact_host_install_command(tmp_path, failure):
    core = "raise ModuleNotFoundError(\"No module named 'PIL'\", name='PIL')" if failure == "import-failure" else None
    async with copied_plugin(tmp_path, missing=failure == "not-installed", core=core) as plugin:
        opened = await open_svg(plugin)
        assert opened["renderer"] == "table" and opened["mode"] == "session"
        errors = opened["initialWindow"]["rows"][0]["cells"]["errors"]
        assert "缺少转换依赖" in errors
        assert f'"{sys.executable}" -m pip install -r "{plugin.root / "requirements.txt"}"' in errors
        assert opened["summary"]["actions"][0]["disabled"] is True
        exported = await export_svg(plugin, opened)
        assert "缺少转换依赖" in exported["message"] and not exported.get("hostEffects")
        assert not plugin.artifacts._records


@pytest.mark.asyncio
@pytest.mark.parametrize("limits", [{"maxSourceBytes": 10}, {"readBytes": 10}])
async def test_source_limits_reject_before_read_or_worker_launch(tmp_path, limits):
    # A failing converter proves that a worker cannot be needed for oversized input.
    kwargs = {"config": limits} if "maxSourceBytes" in limits else {"limits": limits}
    async with copied_plugin(tmp_path, core="raise AssertionError('worker launched')", **kwargs) as plugin:
        opened = await open_svg(plugin)
        assert opened["summary"]["actions"][0]["disabled"] is True
        assert "文件超过限制" in opened["initialWindow"]["rows"][0]["cells"]["errors"]
        assert [event["host_api_method"] for event in plugin.audit if event["event"] == "host_api"] == ["host.workspace.stat"]


@pytest.mark.asyncio
async def test_host_artifact_count_limit_is_reported_without_an_extra_download(tmp_path):
    async with copied_plugin(tmp_path, core=STUB_CORE, limits={"artifactCount": 1}) as plugin:
        opened = await open_svg(plugin)
        first = await export_svg(plugin, opened)
        assert first["hostEffects"][0]["type"] == "download_artifact"
        second = await export_svg(plugin, opened)
        assert "产物数量" in second["message"] and not second.get("hostEffects")
        assert len(plugin.artifacts._records) == 1


@pytest.mark.asyncio
async def test_artifact_byte_limit_is_passed_to_worker(tmp_path):
    async with copied_plugin(tmp_path, core=STUB_CORE, limits={"artifactBytes": 8}) as plugin:
        opened = await open_svg(plugin)
        result = await export_svg(plugin, opened)
        assert "宿主限额" in result["message"] and not result.get("hostEffects")
        assert not plugin.artifacts._records


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["inspect", "export"])
async def test_timed_out_worker_leaves_plugin_runtime_responsive(tmp_path, operation):
    core = STUB_CORE + f'''\nimport time
def {"inspect_svg" if operation == "inspect" else "export_pptx"}(source, config=None):
    time.sleep(30)
'''
    async with copied_plugin(tmp_path, core=core, config={"conversionTimeoutSeconds": 1}) as plugin:
        opened = await open_svg(plugin)
        if operation == "inspect":
            assert "转换超时: 1s" in opened["initialWindow"]["rows"][0]["cells"]["errors"]
            assert opened["summary"]["actions"][0]["disabled"] is True
        else:
            result = await export_svg(plugin, opened)
            assert "转换超时: 1s" in result["message"] and not result.get("hostEffects")
        assert plugin.runtime.active_process_count() == 1
        window = await plugin.runtime.get_view_window("main", plugin.manifest, opened["sessionId"], {})
        assert window["totalRows"] == 1
        assert not plugin.artifacts._records


def test_runner_uses_host_python_and_clamps_timeout_and_render_size(monkeypatch):
    spec = importlib.util.spec_from_file_location("tested_svg_pptx_runner", PLUGIN / "backend/worker_runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    launch = Mock(side_effect=subprocess.TimeoutExpired("worker", 45))
    monkeypatch.setattr(runner.subprocess, "run", launch)
    result = runner.run_worker("inspect", SVG)
    assert "45s" in result["error"]
    assert launch.call_args.args[0] == [sys.executable, str(PLUGIN / "backend/worker.py")]
    assert launch.call_args.kwargs["timeout"] == 45
    runner.run_worker("inspect", SVG, {"conversionTimeoutSeconds": 999, "renderMaxSide": 9999})
    payload = json.loads(launch.call_args.kwargs["input"])
    assert launch.call_args.kwargs["timeout"] == 55
    assert payload["config"]["renderMaxSide"] == 4096


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"maxTextBoxes": 1}, {"maxLayers": 1}])
async def test_converter_count_limits_disable_export(tmp_path, converter_available, config):
    async with copied_plugin(tmp_path, config=config) as plugin:
        plugin.source.write_bytes((plugin.root / "samples/sample.svg").read_bytes())
        opened = await open_svg(plugin)
        assert opened["summary"]["actions"][0]["disabled"] is True
        assert opened["initialWindow"]["rows"][0]["cells"]["errors"]
        result = await export_svg(plugin, opened)
        assert result["message"] and not result.get("hostEffects")
        assert not plugin.artifacts._records
