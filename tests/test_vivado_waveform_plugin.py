from __future__ import annotations

from pathlib import Path

import pytest

from bot.plugins.service import PluginService


def test_fixture_vcd_contains_expected_signals() -> None:
    text = Path("tests/fixtures/vcd/simple_counter.vcd").read_text(encoding="utf-8")
    assert "$var wire 1 ! clk $end" in text
    assert "$var wire 1 \" rst_n $end" in text
    assert "$var wire 4 # counter $end" in text
    assert "b1011 #" in text


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
    for name in ("main.py", "vcd_parser.py"):
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
    view = await service.render_view(
        plugin_id="vivado-waveform",
        view_id="waveform",
        input_payload={"path": str(wave_dir / "simple_counter.vcd")},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert view["renderer"] == "waveform"
    assert view["payload"]["timescale"] == "1ns"
    labels = [item["label"] for item in view["payload"]["tracks"]]
    assert "tb.clk" in labels
    assert "tb.rst_n" in labels
    assert "tb.counter" in labels
    assert view["payload"]["endTime"] >= 120
    await service.shutdown()
