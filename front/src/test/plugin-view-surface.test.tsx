import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";

test("plugin view surface renders waveform metadata and tracks", () => {
  render(
    <PluginViewSurface
      view={{
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: "simple_counter.vcd",
        renderer: "waveform",
        payload: {
          path: "waves/simple_counter.vcd",
          timescale: "1ns",
          startTime: 0,
          endTime: 20,
          tracks: [
            {
              signalId: "clk",
              label: "tb.clk",
              width: 1,
              segments: [
                { start: 0, end: 5, value: "0" },
                { start: 5, end: 10, value: "1" },
              ],
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getByText("simple_counter.vcd")).toBeInTheDocument();
  expect(screen.getByText("1ns")).toBeInTheDocument();
  expect(screen.getByText("tb.clk")).toBeInTheDocument();
});
