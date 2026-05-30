from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from bot.plugins.service import PluginService


def _load_vcd_parser():
    parser_path = Path("examples/plugins/vivado-waveform/backend/vcd_parser.py")
    spec = importlib.util.spec_from_file_location("vivado_waveform_vcd_parser", parser_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vivado_waveform_initial_window_stays_within_budget(tmp_path: Path) -> None:
    wave_file = tmp_path / "simple_counter.vcd"
    wave_file.write_text(Path("tests/fixtures/vcd/simple_counter.vcd").read_text(encoding="utf-8"), encoding="utf-8")

    parser = _load_vcd_parser()
    index = parser.build_vcd_index(wave_file)
    summary = parser.build_waveform_summary(index, path=wave_file)
    window = parser.query_waveform_window(
        index,
        start_time=summary["startTime"],
        end_time=min(summary["endTime"], summary["startTime"] + 120),
        signal_ids=list(summary["defaultSignalIds"]),
        pixel_width=1200,
    )

    payload_bytes = len(json.dumps(window, ensure_ascii=False).encode("utf-8"))
    segment_count = sum(len(track["segments"]) for track in window["tracks"])

    assert payload_bytes < 250_000
    assert segment_count < 10_000


def test_vivado_waveform_lod_marks_dense_changes_instead_of_hiding_them(tmp_path: Path) -> None:
    lines = [
        "$timescale 1fs $end",
        "$scope module tb $end",
        "$var wire 1 ! clk $end",
        "$upscope $end",
        "$enddefinitions $end",
        "#0",
        "0!",
    ]
    for time in range(1, 201):
        lines.extend([f"#{time}", f"{time % 2}!"])
    wave_file = tmp_path / "dense.vcd"
    wave_file.write_text("\n".join(lines), encoding="utf-8")

    parser = _load_vcd_parser()
    index = parser.build_vcd_index(wave_file)
    window = parser.query_waveform_window(
        index,
        start_time=0,
        end_time=200,
        signal_ids=["tb.clk"],
        pixel_width=4,
        max_segments_per_track=4,
    )

    clk_track = window["tracks"][0]
    dense_segments = [segment for segment in clk_track["segments"] if segment.get("kind") == "dense"]
    assert dense_segments
    assert sum(int(segment.get("transitionCount", 0)) for segment in dense_segments) > 0
    assert all(segment["value"] == "mixed" for segment in dense_segments)


@pytest.mark.asyncio
async def test_vivado_waveform_plugin_renders_waveform_payload(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_dir = tmp_path / "home" / ".tcb" / "plugins"
    plugins_dir.mkdir(parents=True)
    source_plugin_dir = Path("examples/plugins/vivado-waveform")
    target_plugin_dir = plugins_dir / "vivado-waveform"
    target_plugin_dir.mkdir()
    (target_plugin_dir / "backend").mkdir()
    (target_plugin_dir / "plugin.json").write_text(
        source_plugin_dir.joinpath("plugin.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in ("main.py", "session_store.py", "vcd_parser.py", "vcd_sidecar.py"):
        (target_plugin_dir / "backend" / name).write_text(
            source_plugin_dir.joinpath("backend", name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    wave_dir = repo_root / "waves"
    wave_dir.mkdir()
    (wave_dir / "simple_counter.vcd").write_text(
        Path("tests/fixtures/vcd/simple_counter.vcd").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    service = PluginService(repo_root, plugins_root=plugins_dir)
    view = await service.open_view(
        bot_alias="main",
        plugin_id="vivado-waveform",
        view_id="waveform",
        input_payload={"path": str(wave_dir / "simple_counter.vcd")},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    window = await service.get_view_window(
        bot_alias="main",
        plugin_id="vivado-waveform",
        session_id=view["sessionId"],
        request_payload={
            "startTime": view["summary"]["startTime"],
            "endTime": view["summary"]["endTime"],
            "signalIds": list(view["summary"]["defaultSignalIds"]),
            "pixelWidth": 1200,
        },
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert view["renderer"] == "waveform"
    assert view["mode"] == "session"
    assert view["summary"]["timescale"] == "1ns"
    labels = [item["label"] for item in view["summary"]["signals"]]
    assert "tb.clk" in labels
    assert "tb.rst_n" in labels
    assert "tb.counter" in labels
    assert view["summary"]["endTime"] >= 120
    assert view["summary"]["display"]["busStyle"] == "cross"
    assert view["summary"]["display"]["showTimeAxis"] is True
    assert {track["label"] for track in window["tracks"]} >= {"tb.clk", "tb.rst_n", "tb.counter"}
    await service.shutdown()
