import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";
import { MockWebBotClient } from "../services/mockWebBotClient";

describe("WaveformView", () => {
  it("shows the signal tree, defaults only default signals, and searches without loading all signals", async () => {
    const user = userEvent.setup();
    const client = new MockWebBotClient();
    const query = vi.spyOn(client, "queryPluginViewWindow");
    const view = await client.openPluginView("main", "vivado-waveform", "waveform", { path: "waves/sample.vcd" });
    render(<PluginViewSurface botAlias="main" client={client} view={view} />);

    expect(screen.getByTestId("waveform-signal-navigator")).toBeInTheDocument();
    expect(screen.getByText("信号 (182)")).toBeInTheDocument();
    expect(screen.getByLabelText("加载 tb.clk")).toBeChecked();
    expect(screen.getByLabelText("加载 tb.counter")).toBeChecked();
    expect(screen.getByLabelText("加载 tb.dut.signal_001")).not.toBeChecked();

    await user.type(screen.getByLabelText("搜索信号"), "signal_001");
    expect(screen.getByText("signal_001")).toBeInTheDocument();
    expect(screen.queryByText("signal_002")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("加载 tb.dut.signal_001"));

    await waitFor(() => {
      const waveformRequests = query.mock.calls.filter(([, , , request]) => request && !(request as { op?: string }).op);
      expect(waveformRequests.at(-1)?.[3]).toMatchObject({ signalIds: expect.arrayContaining(["tb.dut.signal_001"]) });
    });
  });

  it("supports fit controls, cursor measurement, exact inspect, bus hex and status warnings", async () => {
    const user = userEvent.setup();
    const client = new MockWebBotClient();
    const hostEffects: unknown[] = [];
    const view = await client.openPluginView("main", "vivado-waveform", "waveform", { path: "waves/sample.vcd" });
    render(<PluginViewSurface botAlias="main" client={client} view={view} onApplyHostEffects={(effects) => { hostEffects.push(...effects); }} />);

    expect(screen.getByTestId("waveform-status-panel")).toHaveTextContent("PASS");
    expect(screen.getByTestId("waveform-status-panel")).toHaveTextContent("未记录信号");
    expect(screen.getByLabelText("tb.counter 显示进制")).toHaveValue("unsigned-hex");

    await user.click(screen.getByRole("button", { name: "适应选中" }));
    await user.click(screen.getByRole("button", { name: "适应全部" }));
    const stage = screen.getByTestId("waveform-stage");
    fireEvent.mouseMove(stage, { clientX: 260, clientY: 100 });
    fireEvent.click(stage, { clientX: 260, clientY: 100 });
    expect(screen.getByTestId("waveform-cursor")).toBeInTheDocument();
    fireEvent.click(stage, { clientX: 340, clientY: 100 });
    expect(screen.getAllByText(/Δt/).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "精确查询" }));
    const inspect = await screen.findByTestId("waveform-inspect-panel");
    expect(inspect).toHaveTextContent("tb.counter");
    await user.click(within(inspect).getAllByRole("button", { name: "复制" })[0]);
    expect(hostEffects).toEqual(expect.arrayContaining([expect.objectContaining({ type: "copy_text" })]));

    await user.click(screen.getByRole("button", { name: /pass TEST_PASS/ }));
    expect(screen.getByTestId("waveform-cursor")).toBeInTheDocument();
    expect(hostEffects).toEqual(expect.arrayContaining([expect.objectContaining({ type: "open_file", line: 12 })]));
  });
});
