import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";
import { runPluginAction } from "../components/plugins/pluginActions";

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

test("plugin view surface renders document snapshot blocks", () => {
  render(
    <PluginViewSurface
      botAlias="main"
      client={new MockWebBotClient()}
      view={{
        pluginId: "docx-preview",
        viewId: "document",
        title: "roadmap.docx",
        renderer: "document",
        mode: "snapshot",
        payload: {
          path: "docs/roadmap.docx",
          title: "项目路线图",
          statsText: "4 段 · 1 表格",
          blocks: [
            {
              type: "heading",
              level: 1,
              runs: [{ text: "项目路线图" }],
            },
            {
              type: "paragraph",
              runs: [
                { text: "当前状态：" },
                { text: "进行中", bold: true },
                { text: "，需要补齐预览链路。" },
              ],
            },
            {
              type: "list_item",
              ordered: true,
              depth: 0,
              marker: "1.",
              runs: [{ text: "补 document renderer" }],
            },
            {
              type: "table",
              rows: [
                {
                  cells: [
                    { runs: [{ text: "阶段" }] },
                    { runs: [{ text: "状态" }] },
                  ],
                },
                {
                  cells: [
                    { runs: [{ text: "MVP" }] },
                    { runs: [{ text: "开发中", italic: true }] },
                  ],
                },
              ],
            },
          ],
        },
      }}
    />,
  );

  expect(screen.getByRole("heading", { level: 1, name: "项目路线图" })).toBeInTheDocument();
  expect(screen.getByText("4 段 · 1 表格")).toBeInTheDocument();
  expect(screen.getByText("进行中").tagName.toLowerCase()).toBe("strong");
  expect(screen.getByText("开发中").tagName.toLowerCase()).toBe("em");
  expect(screen.getByText("1.")).toBeInTheDocument();
  expect(screen.getByRole("table")).toBeInTheDocument();
});

test("plugin view surface renders hex snapshot views", () => {
  render(
    <PluginViewSurface
      botAlias="main"
      client={new MockWebBotClient()}
      view={{
        pluginId: "hex-preview",
        viewId: "hex",
        title: "firmware.bin",
        renderer: "hex",
        mode: "snapshot",
        payload: {
          path: "bin/firmware.bin",
          fileSizeBytes: 20,
          previewBytes: 16,
          bytesPerRow: 8,
          truncated: true,
          statsText: "20 B · preview 16 B",
          entropyBuckets: [
            { index: 0, startOffset: 0, endOffset: 8, entropy: 0.1 },
            { index: 1, startOffset: 8, endOffset: 16, entropy: 0.9 },
          ],
          rows: [
            { offset: 0, hex: ["00", "41", "42", "7F", "80", "FF", "20", "2E"], ascii: ".AB... ." },
            { offset: 8, hex: ["48", "65", "78", "21"], ascii: "Hex!" },
          ],
        },
      }}
    />,
  );

  expect(screen.getByTestId("hex-view")).toBeInTheDocument();
  expect(screen.getByText("00000000")).toBeInTheDocument();
  expect(screen.getByText("00 41 42 7F 80 FF 20 2E")).toBeInTheDocument();
  expect(screen.getByText(".AB... .")).toBeInTheDocument();
  expect(screen.getAllByTestId("hex-entropy-bucket")).toHaveLength(2);
  expect(screen.getByText("已截断")).toBeInTheDocument();
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

test("plugin view surface renders table snapshot views", () => {
  const client = new MockWebBotClient();
  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "timing-report",
        viewId: "timing-table",
        title: "timing.rpt",
        renderer: "table",
        mode: "snapshot",
        payload: {
          columns: [
            { id: "endpoint", title: "Endpoint" },
            { id: "slack", title: "Slack", kind: "number", align: "right" },
          ],
          rows: [
            { id: "path-1", cells: { endpoint: "rx_data", slack: -0.132 } },
            { id: "path-2", cells: { endpoint: "tx_data", slack: -0.081 } },
          ],
        },
      }}
    />,
  );

  expect(screen.getByText("Endpoint")).toBeInTheDocument();
  expect(screen.getByText("rx_data")).toBeInTheDocument();
  expect(screen.getByText("-0.132")).toBeInTheDocument();
});

test("plugin view surface ignores stale table window responses", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const requests: Array<{
    request: Record<string, unknown>;
    resolve: (payload: Record<string, unknown>) => void;
  }> = [];
  vi.spyOn(client, "queryPluginViewWindow").mockImplementation(
    async (_botAlias, _pluginId, _sessionId, request) =>
      await new Promise((resolve) => {
        requests.push({ request, resolve });
      }),
  );

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "timing-report",
        viewId: "timing-table",
        title: "timing.rpt",
        renderer: "table",
        mode: "session",
        sessionId: "timing-session-1",
        summary: {
          columns: [
            { id: "endpoint", title: "Endpoint" },
            { id: "slack", title: "Slack", kind: "number", align: "right", sortable: true },
          ],
          totalRows: 3,
          defaultPageSize: 2,
        },
        initialWindow: {
          offset: 0,
          limit: 2,
          totalRows: 3,
          rows: [
            { id: "path-1", cells: { endpoint: "rx_data", slack: -0.132 } },
            { id: "path-2", cells: { endpoint: "tx_data", slack: -0.081 } },
          ],
        },
      }}
    />,
  );

  await waitFor(() => {
    expect(requests).toHaveLength(1);
  });
  requests[0]?.resolve({
    offset: 0,
    limit: 2,
    totalRows: 3,
    rows: [
      { id: "path-1", cells: { endpoint: "rx_data", slack: -0.132 } },
      { id: "path-2", cells: { endpoint: "tx_data", slack: -0.081 } },
    ],
  });

  await user.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() => {
    expect(requests).toHaveLength(2);
  });
  await user.click(screen.getByRole("button", { name: "上一页" }));
  await waitFor(() => {
    expect(requests).toHaveLength(3);
  });

  requests[2]?.resolve({
    offset: 0,
    limit: 2,
    totalRows: 3,
    rows: [
      { id: "path-1", cells: { endpoint: "rx_data", slack: -0.132 } },
      { id: "path-2", cells: { endpoint: "tx_data", slack: -0.081 } },
    ],
  });
  await waitFor(() => {
    expect(screen.getByText("rx_data")).toBeInTheDocument();
  });

  requests[1]?.resolve({
    offset: 2,
    limit: 2,
    totalRows: 3,
    rows: [
      { id: "path-3", cells: { endpoint: "ctrl_state", slack: 0.014 } },
    ],
  });

  await waitFor(() => {
    expect(screen.getByText("rx_data")).toBeInTheDocument();
    expect(screen.queryByText("ctrl_state")).toBeNull();
  });
});

test("plugin view surface loads tree children on demand", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "rtl-hierarchy",
        viewId: "module-tree",
        title: "design.hier",
        renderer: "tree",
        mode: "session",
        sessionId: "tree-session-1",
        summary: {
          searchable: true,
        },
        initialWindow: {
          op: "children",
          nodeId: null,
          nodes: [
            { id: "top", label: "top", kind: "folder", hasChildren: true },
          ],
        },
      }}
    />,
  );

  await user.click(screen.getByRole("button", { name: "展开 top" }));
  expect(await screen.findByText("u_core")).toBeInTheDocument();
  expect(screen.getByText("u_mem")).toBeInTheDocument();
});

test("plugin view surface does not send tree search for empty query", async () => {
  const client = new MockWebBotClient();
  const querySpy = vi.spyOn(client, "queryPluginViewWindow");

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "repo-outline",
        viewId: "repo-tree",
        title: "仓库大纲",
        renderer: "tree",
        mode: "session",
        sessionId: "repo-tree-session-1",
        summary: {
          searchable: true,
          searchPlaceholder: "搜目录、文件、符号",
          statsText: "2 文件 · 1 符号",
        },
        initialWindow: {
          op: "children",
          nodeId: null,
          nodes: [{ id: "dir:bot", label: "bot", kind: "folder", hasChildren: true }],
        },
      }}
    />,
  );

  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(querySpy).not.toHaveBeenCalled();
});

test("plugin view surface shows local loading and ignores stale tree children responses", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const requests: Array<{
    request: Record<string, unknown>;
    resolve: (payload: Record<string, unknown>) => void;
  }> = [];
  vi.spyOn(client, "queryPluginViewWindow").mockImplementation(
    async (_botAlias, _pluginId, _sessionId, request) =>
      await new Promise((resolve) => {
        requests.push({ request, resolve });
      }),
  );

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "repo-outline",
        viewId: "repo-tree",
        title: "仓库大纲",
        renderer: "tree",
        mode: "session",
        sessionId: "repo-tree-session-2",
        summary: {
          searchable: true,
        },
        initialWindow: {
          op: "children",
          nodeId: null,
          nodes: [{ id: "dir:src", label: "src", kind: "folder", hasChildren: true }],
        },
      }}
    />,
  );

  await user.click(screen.getByRole("button", { name: "展开 src" }));
  expect(await screen.findAllByText("正在展开 src...")).toHaveLength(2);

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "api" } });
  await waitFor(() => {
    expect(requests).toHaveLength(2);
  });

  requests[1]?.resolve({
    op: "search",
    nodes: [{ id: "file:src/api.ts", label: "api.ts", kind: "file" }],
  });
  expect(await screen.findByText("api.ts")).toBeInTheDocument();

  requests[0]?.resolve({
    op: "children",
    nodeId: "dir:src",
    nodes: [{ id: "file:src/stale.ts", label: "stale.ts", kind: "file" }],
  });
  await waitFor(() => {
    expect(screen.queryByText("stale.ts")).toBeNull();
  });
});

test("plugin view surface ignores stale tree search responses", async () => {
  const client = new MockWebBotClient();
  const requests: Array<{
    request: Record<string, unknown>;
    resolve: (payload: Record<string, unknown>) => void;
  }> = [];
  vi.spyOn(client, "queryPluginViewWindow").mockImplementation(
    async (_botAlias, _pluginId, _sessionId, request) =>
      await new Promise((resolve) => {
        requests.push({ request, resolve });
      }),
  );

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "rtl-hierarchy",
        viewId: "module-tree",
        title: "design.hier",
        renderer: "tree",
        mode: "session",
        sessionId: "tree-session-2",
        summary: {
          searchable: true,
        },
        initialWindow: {
          op: "children",
          nodeId: null,
          nodes: [],
        },
      }}
    />,
  );

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "top" } });
  await waitFor(() => {
    expect(requests).toHaveLength(1);
  });

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "tb" } });
  await waitFor(() => {
    expect(requests).toHaveLength(2);
  });

  requests[1]?.resolve({
    op: "search",
    nodes: [{ id: "tb_uart", label: "tb_uart", kind: "symbol", hasChildren: false }],
  });
  await waitFor(() => {
    expect(screen.getByText("tb_uart")).toBeInTheDocument();
  });

  requests[0]?.resolve({
    op: "search",
    nodes: [{ id: "top", label: "top", kind: "folder", hasChildren: true }],
  });
  await waitFor(() => {
    expect(screen.getByText("tb_uart")).toBeInTheDocument();
    expect(screen.queryByText("top")).toBeNull();
  });
});

test("plugin view surface runs file and symbol primary actions", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const applyHostEffects = vi.fn();

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      onApplyHostEffects={applyHostEffects}
      view={{
        pluginId: "repo-outline",
        viewId: "repo-tree",
        title: "仓库大纲",
        renderer: "tree",
        mode: "snapshot",
        payload: {
          roots: [
            {
              id: "file:bot/web/api_service.py",
              label: "api_service.py",
              kind: "file",
              secondaryText: "bot/web",
              hasChildren: true,
              actions: [
                {
                  id: "open-file",
                  label: "打开文件",
                  target: "host",
                  location: "node",
                  hostAction: { type: "open_file", path: "bot/web/api_service.py" },
                },
              ],
              children: [
                {
                  id: "symbol:bot/web/api_service.py:run_cli_chat:184",
                  label: "run_cli_chat",
                  kind: "function",
                  secondaryText: "function · line 184",
                  actions: [
                    {
                      id: "jump-definition",
                      label: "跳到定义",
                      target: "host",
                      location: "node",
                      hostAction: { type: "open_file", path: "bot/web/api_service.py", line: 184 },
                    },
                  ],
                },
              ],
            },
          ],
        },
      }}
    />,
  );

  await user.click(screen.getByRole("button", { name: "打开文件 api_service.py" }));
  await user.click(screen.getByRole("button", { name: "展开 api_service.py" }));
  await user.click(screen.getByRole("button", { name: "跳到定义 run_cli_chat" }));

  expect(applyHostEffects).toHaveBeenNthCalledWith(1, [{ type: "open_file", path: "bot/web/api_service.py" }]);
  expect(applyHostEffects).toHaveBeenNthCalledWith(2, [{ type: "open_file", path: "bot/web/api_service.py", line: 184 }]);
});

test("plugin tree view renders only visible rows for large trees", () => {
  const client = new MockWebBotClient();

  render(
    <PluginViewSurface
      botAlias="main"
      client={client}
      view={{
        pluginId: "repo-outline",
        viewId: "repo-tree",
        title: "仓库大纲",
        renderer: "tree",
        mode: "snapshot",
        payload: {
          roots: Array.from({ length: 500 }, (_, index) => ({
            id: `node-${index}`,
            label: `node-${index}`,
            kind: "file",
          })),
        },
      }}
    />,
  );

  expect(screen.getAllByRole("button", { name: /^node-/ }).length).toBeLessThanOrEqual(100);
});

test("runPluginAction closes session before refreshing", async () => {
  const client = new MockWebBotClient();
  const closeSession = vi.fn();
  const refreshSession = vi.fn();
  vi.spyOn(client, "invokePluginAction").mockResolvedValue({
    message: "已删除",
    refresh: "session",
    closeSession: true,
  });

  await runPluginAction(
    { id: "delete-row", label: "删除", target: "plugin", location: "row" },
    {
      client,
      botAlias: "main",
      pluginId: "timing-report",
      viewId: "timing-table",
      title: "timing.rpt",
      sessionId: "session-1",
      inputPayload: { path: "reports/timing.rpt" },
      payload: { rowId: "path-1" },
      applyHostEffects: vi.fn(),
      closeSession,
      refreshSession,
      reopenView: vi.fn(),
      pushToast: vi.fn(),
    },
  );

  expect(closeSession).toHaveBeenCalledWith("timing-report", "session-1");
  expect(refreshSession).not.toHaveBeenCalled();
});
