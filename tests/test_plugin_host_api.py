from __future__ import annotations

from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi, PluginHostContext, PluginHostPermissionError
from bot.plugins.models import PluginManifest, PluginPermissions, PluginRuntimeSpec


def _manifest(*, workspace_read: bool, workspace_list: bool = False) -> PluginManifest:
    runtime = PluginRuntimeSpec(
        runtime_type="python",
        entry="backend/main.py",
        protocol="jsonrpc-stdio",
        permissions=PluginPermissions(
            workspace_read=workspace_read,
            workspace_list=workspace_list,
            temp_artifacts=False,
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
            {"name": "App", "kind": "class", "line": 1},
            {"name": "run", "kind": "function", "line": 2},
        ],
    }


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
