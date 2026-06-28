from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.debug.models import DebugProfile
from bot.debug.providers.registry import DebugProviderRegistry
from bot.debug.service import DebugService, _Runtime


def _make_profile(workspace: Path, *, remote_dir: str = "") -> DebugProfile:
    return DebugProfile(
        kind="test",
        workspace=str(workspace),
        config_name="test",
        program="",
        cwd=str(workspace),
        mi_mode="gdb",
        mi_debugger_path="",
        compile_commands=None,
        prepare_command=r".\debug.bat",
        stop_at_entry=True,
        setup_commands=[],
        remote_host="",
        remote_user="",
        remote_dir=remote_dir,
        remote_port=0,
    )


def test_resolve_frame_source_returns_raw_when_runtime_unbound():
    service = DebugService(SimpleNamespace(), provider_registry=DebugProviderRegistry([]))
    runtime = _Runtime()

    result = service._resolve_frame_source(runtime, "src/main.c", 17)

    assert result == {"path": "src/main.c", "line": 17, "resolved": True, "reason": "raw"}


def test_resolve_frame_source_uses_workspace_resolution(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_file = workspace / "src" / "main.c"
    source_file.parent.mkdir()
    source_file.write_text("int main() { return 0; }\n", encoding="utf-8")

    service = DebugService(SimpleNamespace(), provider_registry=DebugProviderRegistry([]))
    runtime = _Runtime(workspace=workspace, profile=_make_profile(workspace))

    result = service._resolve_frame_source(runtime, "src/main.c", 12, {"line": 12})

    assert result["resolved"] is True
    assert result["reason"] == "workspace_relative"
    assert Path(result["path"]) == source_file.resolve()
    assert result["line"] == 12
