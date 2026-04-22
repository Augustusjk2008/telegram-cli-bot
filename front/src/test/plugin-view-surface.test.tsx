import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";

test("plugin view surface renders aligned zoomable waveform with time axis and bus tracks", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: "simple_counter.vcd",
        renderer: "waveform",
        mode: "snapshot",
        payload: {
          path: "waves/simple_counter.vcd",
          timescale: "1ns",
          startTime: 0,
          endTime: 120,
          display: {
            defaultZoom: 0.5,
            zoomLevels: [0.5, 1, 2],
            showTimeAxis: true,
            busStyle: "cross",
            labelWidth: 180,
            minWaveWidth: 600,
            pixelsPerTime: 10,
            axisHeight: 40,
            trackHeight: 60,
          },
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
            {
              signalId: "counter",
              label: "tb.counter",
              width: 4,
              segments: [
                { start: 0, end: 40, value: "0000" },
                { start: 40, end: 80, value: "0001" },
                { start: 80, end: 120, value: "0010" },
              ],
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getByText("simple_counter.vcd")).toBeInTheDocument();
  expect(screen.getByText("1ns")).toBeInTheDocument();
  expect(screen.getByText("时间轴")).toBeInTheDocument();
  expect(screen.getByText("tb.clk")).toBeInTheDocument();
  expect(screen.getByText("tb.counter")).toBeInTheDocument();
  expect(screen.getByTestId("waveform-time-axis")).toBeInTheDocument();
  expect(screen.getByTestId("waveform-grid")).toHaveStyle({ gridTemplateColumns: "180px 600px" });
  expect(screen.getAllByTestId("waveform-bus-transition").length).toBeGreaterThan(0);
  expect(document.querySelector("[stroke-dasharray]")).toBeNull();

  const timeAxis = screen.getByTestId("waveform-time-axis");
  const initialWidth = Number(timeAxis.getAttribute("width"));
  await user.click(screen.getByRole("button", { name: "放大横轴" }));
  expect(Number(timeAxis.getAttribute("width"))).toBeGreaterThan(initialWidth);
});

test("plugin view surface requests windows for session waveform views and only renders visible rows", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const querySpy = vi.spyOn(client, "queryPluginViewWindow");

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: "simple_counter.vcd",
        renderer: "waveform",
        mode: "session",
        sessionId: "session-1",
        summary: {
          path: "waves/simple_counter.vcd",
          timescale: "1ns",
          startTime: 0,
          endTime: 120,
          display: {
            defaultZoom: 1,
            zoomLevels: [1, 2],
            showTimeAxis: true,
            busStyle: "cross",
            labelWidth: 180,
            minWaveWidth: 840,
            pixelsPerTime: 10,
            axisHeight: 42,
            trackHeight: 64,
          },
          signals: Array.from({ length: 40 }, (_, index) => ({
            signalId: `tb.signal_${index}`,
            label: `tb.signal_${index}`,
            width: index % 4 === 0 ? 8 : 1,
            kind: index % 4 === 0 ? "bus" as const : "scalar" as const,
          })),
          defaultSignalIds: ["tb.signal_0", "tb.signal_1", "tb.signal_2", "tb.signal_3"],
        },
        initialWindow: {
          startTime: 0,
          endTime: 120,
          tracks: [
            {
              signalId: "tb.signal_0",
              label: "tb.signal_0",
              width: 8,
              segments: [
                { start: 0, end: 40, value: "0x0" },
                { start: 40, end: 120, value: "0x1" },
              ],
            },
            {
              signalId: "tb.signal_1",
              label: "tb.signal_1",
              width: 1,
              segments: [
                { start: 0, end: 60, value: "0" },
                { start: 60, end: 120, value: "1" },
              ],
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getByText("tb.signal_0")).toBeInTheDocument();
  expect(screen.queryByText("tb.signal_39")).toBeNull();

  await user.click(screen.getByRole("button", { name: "放大横轴" }));

  await waitFor(() => {
    expect(querySpy).toHaveBeenCalledWith(
      "main",
      "vivado-waveform",
      "session-1",
      expect.objectContaining({
        signalIds: expect.any(Array),
        pixelWidth: expect.any(Number),
      }),
      expect.any(AbortSignal),
    );
  });
});
