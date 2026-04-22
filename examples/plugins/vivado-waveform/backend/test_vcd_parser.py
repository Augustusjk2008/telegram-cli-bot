from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from vcd_parser import parse_vcd


class VcdParserTest(unittest.TestCase):
    def _parse(self, content: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.vcd"
            path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
            return parse_vcd(path)

    def test_filters_task_and_function_scopes(self) -> None:
        parsed = self._parse(
            """
            $timescale 1ns $end
            $scope module top $end
            $var wire 1 ! top_sig $end
            $scope task helper $end
            $var reg 1 " task_tmp $end
            $upscope $end
            $scope function calc $end
            $var reg 1 # fn_tmp $end
            $upscope $end
            $upscope $end
            $enddefinitions $end
            #0
            0!
            0"
            1#
            #10
            1!
            1"
            0#
            """
        )

        labels = [track["label"] for track in parsed["tracks"]]
        self.assertEqual(labels, ["top.top_sig"])

    def test_preserves_scalar_edges_without_sampling(self) -> None:
        changes = ["#0", "0!"]
        for step in range(1, 24):
            changes.extend([f"#{step}", f"{step % 2}!"])

        parsed = self._parse(
            """
            $timescale 1ns $end
            $scope module top $end
            $var wire 1 ! clk $end
            $upscope $end
            $enddefinitions $end
            """
            + "\n"
            + "\n".join(changes)
        )

        track = parsed["tracks"][0]
        values = [segment["value"] for segment in track["segments"]]
        self.assertEqual(len(track["segments"]), 24)
        self.assertEqual(values[:8], ["0", "1", "0", "1", "0", "1", "0", "1"])
        self.assertNotIn("sampled", track)

    def test_default_zoom_increases_for_fast_scalar_signals(self) -> None:
        parsed = self._parse(
            """
            $timescale 1ps $end
            $scope module top $end
            $var wire 1 ! clk $end
            $upscope $end
            $enddefinitions $end
            #0
            0!
            #10000
            1!
            #20000
            0!
            #30000
            1!
            #40000
            0!
            #1637990000
            1!
            """
        )

        display = parsed["display"]
        self.assertGreaterEqual(display["defaultZoom"], 8)
        self.assertIn(display["defaultZoom"], display["zoomLevels"])


if __name__ == "__main__":
    unittest.main()
