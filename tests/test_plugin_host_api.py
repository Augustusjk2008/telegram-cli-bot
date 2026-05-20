from __future__ import annotations

from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi, PluginHostContext, PluginHostPermissionError
from bot.plugins.models import PluginManifest, PluginPermissions, PluginRuntimeSpec


def _manifest(
    *,
    workspace_read: bool,
    workspace_list: bool = False,
    temp_artifacts: bool = False,
) -> PluginManifest:
    runtime = PluginRuntimeSpec(
        runtime_type="python",
        entry="backend/main.py",
        protocol="jsonrpc-stdio",
        permissions=PluginPermissions(
            workspace_read=workspace_read,
            workspace_list=workspace_list,
            temp_artifacts=temp_artifacts,
        ),
    )
    return PluginManifest(
        root=Path("."),
        plugin_id="repo-outline",
        schema_version=2,
        name="Repo Outline",
        version="0.1.0",
        description="",
        enabled=True,
        config={},
        runtime=runtime,
        views=(),
        file_handlers=(),
    )


@pytest.mark.asyncio
async def test_host_workspace_outline_returns_file_symbols(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "app.py").write_text(
        "class App:\n    def run(self):\n        return True\n",
        encoding="utf-8",
    )
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=workspace,
    )

    result = await api.dispatch(
        context,
        _manifest(workspace_read=True),
        "host.workspace.outline",
        {"path": "src/app.py"},
    )

    assert result == {
        "path": "src/app.py",
        "items": [
            {
                "name": "App",
                "kind": "class",
                "line": 1,
                "level": 1,
                "children": [
                    {"name": "run", "kind": "method", "line": 2, "level": 2, "children": []},
                ],
            },
        ],
    }


@pytest.mark.asyncio
async def test_host_workspace_outline_accepts_backslash_relative_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=workspace,
    )

    result = await api.dispatch(
        context,
        _manifest(workspace_read=True),
        "host.workspace.outline",
        {"path": r"src\app.py"},
    )

    assert result["path"] == "src/app.py"
    assert result["items"] == [{"name": "run", "kind": "function", "line": 1, "level": 1, "children": []}]


@pytest.mark.asyncio
async def test_host_workspace_read_text_accepts_backslash_relative_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "app.py").write_text("content\n", encoding="utf-8")
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=workspace,
    )

    result = await api.dispatch(
        context,
        _manifest(workspace_read=True),
        "host.workspace.read_text",
        {"path": r"src\app.py"},
    )

    assert result["content"] == "content\n"


@pytest.mark.asyncio
async def test_host_workspace_list_dir_accepts_backslash_relative_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src" / "pkg").mkdir(parents=True)
    (workspace / "src" / "pkg" / "app.py").write_text("content\n", encoding="utf-8")
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=workspace,
    )

    result = await api.dispatch(
        context,
        _manifest(workspace_read=False, workspace_list=True),
        "host.workspace.list_dir",
        {"path": r"src\pkg"},
    )

    assert [item["name"] for item in result["entries"]] == ["app.py"]


@pytest.mark.asyncio
async def test_host_workspace_path_rejects_backslash_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "outside.py").write_text("def leak():\n    return True\n", encoding="utf-8")
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=workspace,
    )

    with pytest.raises(ValueError, match="路径越界"):
        await api.dispatch(
            context,
            _manifest(workspace_read=True),
            "host.workspace.read_text",
            {"path": r"..\outside.py"},
        )


@pytest.mark.asyncio
async def test_host_workspace_outline_requires_workspace_read(tmp_path: Path) -> None:
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=tmp_path,
    )

    with pytest.raises(PluginHostPermissionError, match="workspaceRead"):
        await api.dispatch(
            context,
            _manifest(workspace_read=False),
            "host.workspace.outline",
            {"path": "src/app.py"},
        )


@pytest.mark.asyncio
async def test_host_workspace_outline_rejects_out_of_workspace_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def run():\n    return True\n", encoding="utf-8")
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="repo-outline",
        workspace_root=workspace,
    )

    with pytest.raises(ValueError, match="路径越界"):
        await api.dispatch(
            context,
            _manifest(workspace_read=True),
            "host.workspace.outline",
            {"path": str(outside)},
        )


@pytest.mark.asyncio
async def test_host_api_write_artifact_records_content_type(tmp_path: Path) -> None:
    api = PluginHostApi(ArtifactStore(tmp_path / ".artifacts"))
    context = PluginHostContext(
        bot_alias="main",
        plugin_id="docx-preview",
        workspace_root=tmp_path,
    )

    result = await api.dispatch(
        context,
        _manifest(workspace_read=False, temp_artifacts=True),
        "host.temp.write_artifact",
        {
            "filename": "image1.png",
            "contentBase64": "iVBORw0KGgo=",
            "contentType": "image/png",
        },
    )
    record = api.artifacts.get(bot_alias="main", artifact_id=result["artifactId"])

    assert result["contentType"] == "image/png"
    assert record.content_type == "image/png"
    assert record.filename == "image1.png"
