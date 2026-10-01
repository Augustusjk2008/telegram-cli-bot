from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "examples" / "plugins" / "vivado-waveform" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from log_parser import parse_vivado_log
from session_store import WaveformSessionStore
from vcd_parser import build_vcd_index, build_waveform_summary, inspect_waveform
from vcd_sidecar import build_or_load_sidecar


def _vcd(*, recorded_count: int = 13) -> str:
    declarations = [f"$var wire 1 {chr(33 + index)} sig{index} $end" for index in range(recorded_count)]
    declarations.append("$var wire 1 z never_recorded $end")
    values = [f"0{chr(33 + index)}" for index in range(recorded_count)]
    return "\n".join(
        [
            "$timescale 1 ns $end",
            "$scope module tb $end",
            *declarations,
            "$upscope $end",
            "$enddefinitions $end",
            "#0",
            *values,
            "#10",
            *[f"1{chr(33 + index)}" for index in range(recorded_count)],
            "",
        ]
    )


def test_summary_keeps_unrecorded_signals_and_builds_bounded_overview(tmp_path: Path) -> None:
    source = tmp_path / "sample.vcd"
    source.write_text(_vcd(), encoding="utf-8")

    index = build_vcd_index(source)
    summary = build_waveform_summary(index)

    assert len(summary["signals"]) == 14
    unrecorded = next(item for item in summary["signals"] if item["name"] == "never_recorded")
    assert unrecorded["recorded"] is False
    assert unrecorded["changeCount"] == 0
    assert summary["defaultSignalIds"] == [f"tb.sig{index}" for index in range(12)]
    assert len(summary["overview"]["bins"]) <= 256
    assert summary["indexStats"]["declaredSignalCount"] == 14
    assert summary["indexStats"]["recordedSignalCount"] == 13
    assert summary["indexStats"]["totalChangeCount"] == 26

    exact = inspect_waveform(index, time=index.end_time, signal_ids=["tb.sig0", "tb.never_recorded"])
    assert exact["values"] == [
        {"signalId": "tb.sig0", "value": "1", "recorded": True, "exact": True},
        {"signalId": "tb.never_recorded", "value": None, "recorded": False, "exact": True},
    ]
    before_first = inspect_waveform(index, time=-1, signal_ids=["tb.sig0"])
    assert before_first["values"][0]["value"] is None


def test_sidecar_uses_source_identity_and_reuses_index(tmp_path: Path) -> None:
    source = tmp_path / "sample.vcd"
    source.write_text(_vcd(recorded_count=1), encoding="utf-8")

    first = build_or_load_sidecar(source)
    first.close()
    second = build_or_load_sidecar(source)
    assert second.cache_hit is True
    assert second.index.index_cache_hit is True
    second.close()

    source.write_text(_vcd(recorded_count=2), encoding="utf-8")
    changed = build_or_load_sidecar(source)
    assert changed.cache_hit is False
    assert changed.index.source_identity["sha256"]
    changed.close()


def test_session_dispose_cleans_private_copy_and_expired_session_is_explicit(tmp_path: Path) -> None:
    source = tmp_path / "sample.vcd"
    source.write_text(_vcd(recorded_count=1), encoding="utf-8")
    private_dir = tmp_path / "vivado-waveform-private"
    private_dir.mkdir()
    private_copy = private_dir / "sample.vcd"
    private_copy.write_bytes(source.read_bytes())
    store = WaveformSessionStore()
    session_id, _index = store.open(
        private_copy,
        source_identity={"sourcePath": str(source), "mtimeNs": "1", "fileSize": private_copy.stat().st_size, "sha256": "test"},
        temporary_path=private_copy,
    )
    assert store.dispose(session_id) is True
    assert not private_copy.exists()
    with pytest.raises(ValueError, match="expired"):
        store.get_index(session_id)
    store.close_all()


def test_log_parser_keeps_explicit_times_and_missing_signal_warnings() -> None:
    result = parse_vivado_log(
        "\n".join(
            [
                "TEST_PASS tb_uart_rx_tolerance",
                "PASS: fast output [fast_out]",
                "WARNING: VCD pattern not found: /tb/dut/state_r",
                "ERROR: unexpected byte",
                "$finish called at time 12524050",
                "run: Time 12.5 elapsed",
                "THEORY: sampled data",
            ]
        )
    )
    assert result["testStatus"] == "fail"
    assert result["testName"] == "tb_uart_rx_tolerance"
    assert result["finishTime"] == 12524050
    assert result["elapsed"] == 12.5
    assert result["missingSignals"] == ["/tb/dut/state_r"]
    assert any(event["kind"] == "finish" and event["simTime"] == 12524050 for event in result["events"])
    assert any(event["kind"] == "pass" and event["tags"] == ["fast_out"] for event in result["events"])


def test_materialize_source_uses_host_stat_and_one_megabyte_ranges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    waveform_main = importlib.import_module("main")
    content = b"header\n#0\n0!\n"
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_host(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        if method == "host.workspace.stat":
            return {"path": "C:/workspace/sample.vcd", "exists": True, "isDir": False, "size": len(content), "mtimeNs": "42"}
        offset = int(params["offset"])
        chunk = content[offset : offset + int(params["length"])]
        return {
            "path": "C:/workspace/sample.vcd",
            "offset": offset,
            "length": len(chunk),
            "fileSizeBytes": len(content),
            "mtimeNs": "42",
            "contentBase64": base64.b64encode(chunk).decode("ascii"),
            "eof": offset + len(chunk) == len(content),
        }

    monkeypatch.setattr(waveform_main, "call_host", fake_host)
    temporary_path, identity, truncated = waveform_main._materialize_host_file("C:/workspace/sample.vcd")
    try:
        assert temporary_path.read_bytes() == content
        assert identity["sourcePath"] == "C:/workspace/sample.vcd"
        assert truncated is False
        assert calls[0][0] == "host.workspace.stat"
        assert all(call[0] == "host.workspace.read_range" or call[0] == "host.workspace.stat" for call in calls)
        assert all(int(call[1].get("length", 1)) <= 1024 * 1024 for call in calls[1:])
    finally:
        waveform_main._cleanup_temp_path(temporary_path)
