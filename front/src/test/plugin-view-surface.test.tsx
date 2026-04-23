import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
            zoomLevels: [0.1, 0.5, 1, 2],
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
  expect(screen.getByTestId("waveform-scroll")).toContainElement(screen.getByTestId("waveform-time-axis"));
  expect(screen.getByTestId("waveform-grid")).toHaveStyle({ gridTemplateColumns: "180px 600px" });
  expect(screen.getAllByTestId("waveform-bus-transition").length).toBeGreaterThan(0);
  expect(document.querySelector("[stroke-dasharray]")).toBeNull();

  const timeAxis = screen.getByTestId("waveform-time-axis");
  const initialWidth = Number(timeAxis.getAttribute("width"));
  expect(screen.getByText("横轴 50%")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "缩小横轴" }));
  expect(screen.getByText("横轴 10%")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "放大横轴" }));
  expect(screen.getByText("横轴 50%")).toBeInTheDocument();
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

test("plugin view surface uses the full summary range for session waveform timelines", () => {
  const client = new MockWebBotClient();
  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: "long.vcd",
        renderer: "waveform",
        mode: "session",
        sessionId: "session-2",
        summary: {
          path: "waves/long.vcd",
          timescale: "1us",
          startTime: 0,
          endTime: 1600,
          display: {
            defaultZoom: 1,
            zoomLevels: [1],
            showTimeAxis: true,
            busStyle: "cross",
            labelWidth: 180,
            minWaveWidth: 800,
            pixelsPerTime: 1,
            axisHeight: 42,
            trackHeight: 64,
          },
          signals: [{ signalId: "tb.clk", label: "tb.clk", width: 1, kind: "scalar" }],
          defaultSignalIds: ["tb.clk"],
        },
        initialWindow: {
          startTime: 0,
          endTime: 120,
          tracks: [
            { signalId: "tb.clk", label: "tb.clk", width: 1, segments: [{ start: 0, end: 120, value: "0" }] },
          ],
        },
      }}
    />,
  );

  expect(within(screen.getByTestId("waveform-time-axis")).getByText("1600")).toBeInTheDocument();
});

test("plugin view surface queries the horizontally visible time window", async () => {
  const client = new MockWebBotClient();
  const querySpy = vi.spyOn(client, "queryPluginViewWindow");
  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: "long.vcd",
        renderer: "waveform",
        mode: "session",
        sessionId: "session-3",
        summary: {
          path: "waves/long.vcd",
          timescale: "1us",
          startTime: 0,
          endTime: 1600,
          display: {
            defaultZoom: 1,
            zoomLevels: [1],
            showTimeAxis: true,
            busStyle: "cross",
            labelWidth: 180,
            minWaveWidth: 800,
            pixelsPerTime: 1,
            axisHeight: 42,
            trackHeight: 64,
          },
          signals: [{ signalId: "tb.clk", label: "tb.clk", width: 1, kind: "scalar" }],
          defaultSignalIds: ["tb.clk"],
        },
        initialWindow: {
          startTime: 0,
          endTime: 120,
          tracks: [
            { signalId: "tb.clk", label: "tb.clk", width: 1, segments: [{ start: 0, end: 120, value: "0" }] },
          ],
        },
      }}
    />,
  );

  const scroller = screen.getByTestId("waveform-scroll");
  Object.defineProperty(scroller, "clientWidth", { configurable: true, value: 400 });
  fireEvent.scroll(scroller, { target: { scrollLeft: 800, scrollTop: 0 } });

  await waitFor(() => {
    expect(querySpy).toHaveBeenCalledWith(
      "main",
      "vivado-waveform",
      "session-3",
      expect.objectContaining({ startTime: expect.any(Number), endTime: expect.any(Number) }),
      expect.any(AbortSignal),
    );
    expect(querySpy.mock.calls.some((call) => Number(call[3].startTime) >= 790)).toBe(true);
  });
});

test("plugin view surface renders dense LOD segments as activity bands with labels above the band", () => {
  const client = new MockWebBotClient();
  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: "dense.vcd",
        renderer: "waveform",
        mode: "snapshot",
        payload: {
          path: "waves/dense.vcd",
          timescale: "1ns",
          startTime: 0,
          endTime: 40,
          display: {
            defaultZoom: 1,
            zoomLevels: [1],
            showTimeAxis: true,
            busStyle: "cross",
            labelWidth: 180,
            minWaveWidth: 400,
            pixelsPerTime: 10,
            axisHeight: 42,
            trackHeight: 64,
          },
          tracks: [
            {
              signalId: "clk",
              label: "tb.clk",
              width: 1,
              segments: [
                { start: 0, end: 40, value: "mixed", kind: "dense", transitionCount: 40 },
              ],
            },
            {
              signalId: "bus",
              label: "tb.bus",
              width: 8,
              segments: [
                { start: 0, end: 40, value: "mixed", kind: "dense", transitionCount: 40 },
              ],
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getAllByTestId("waveform-dense-segment")).toHaveLength(2);
  const changeLabels = screen.getAllByText("40 changes");
  expect(changeLabels).toHaveLength(2);
  changeLabels.forEach((label) => {
    expect(label).toHaveAttribute("text-anchor", "middle");
    expect(Number(label.getAttribute("y"))).toBeLessThan(20);
  });
});
