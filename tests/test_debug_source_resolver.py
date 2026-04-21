from __future__ import annotations

import json
from pathlib import Path

from bot.debug.models import DebugProfileV2, DebugSourceMap
from bot.debug.profile_loader import load_debug_profile_v2
from bot.debug.source_resolver import resolve_source

from tests.test_debug_profile_loader import _write_workspace


def _profile(root: Path) -> DebugProfileV2:
    _write_workspace(root)
    profile = load_debug_profile_v2(root)
    assert profile is not None
    return profile


def test_maps_remote_dir_to_workspace(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main(){}", encoding="utf-8")
    profile = _profile(tmp_path)

    result = resolve_source(tmp_path, profile, "/home/sast8/tmp/src/main.cpp", {"line": 4})

    assert result == {
        "path": str((tmp_path / "src" / "main.cpp").resolve()),
        "line": 4,
        "resolved": True,
        "reason": "source_map",
    }


def test_maps_configured_source_prefix(tmp_path: Path) -> None:
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "file.cpp").write_text("", encoding="utf-8")
    profile = _profile(tmp_path)
    profile = profile.with_source_maps([DebugSourceMap(remote="/build/src", local=str(tmp_path / "local"))])

    result = resolve_source(tmp_path, profile, "/build/src/file.cpp", {"line": 8})

    assert result["path"] == str((tmp_path / "local" / "file.cpp").resolve())
    assert result["resolved"] is True


def test_uses_compile_commands_file(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    src_dir = tmp_path / "real_src"
    src_dir.mkdir()
    source = src_dir / "worker.cpp"
    source.write_text("", encoding="utf-8")
    compile_commands = tmp_path / ".vscode" / "compile_commands.json"
    compile_commands.write_text(
        json.dumps([{"directory": str(src_dir), "file": "worker.cpp", "command": "g++ worker.cpp"}]),
        encoding="utf-8",
    )

    result = resolve_source(tmp_path, profile, "/remote/generated/worker.cpp", {"line": 5})

    assert result["path"] == str(source.resolve())
    assert result["reason"] == "compile_commands"


def test_unknown_frame_is_unresolved(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    result = resolve_source(tmp_path, profile, "??", {"line": 0})

    assert result == {"path": "", "line": 0, "resolved": False, "reason": "unknown_source"}
