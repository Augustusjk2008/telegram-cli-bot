import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PluginsScreen } from "../screens/PluginsScreen";

test("plugins screen toggles plugin enabled state and saves schema config", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateSpy = vi.spyOn(client, "updatePlugin");

  render(<PluginsScreen client={client} botAlias="main" />);

  expect(await screen.findByText("Vivado Waveform")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "禁用 Vivado Waveform" }));

  await waitFor(() => {
    expect(updateSpy).toHaveBeenCalledWith("vivado-waveform", { enabled: false });
  });
  expect(await screen.findByText(/已禁用/)).toBeInTheDocument();

  const timingPageSize = screen.getByLabelText("默认页大小");
  await user.clear(timingPageSize);
  await user.type(timingPageSize, "200");
  await user.click(screen.getByRole("button", { name: "保存 Timing Report 设置" }));

  await waitFor(() => {
    expect(updateSpy).toHaveBeenCalledWith("timing-report", { config: { defaultPageSize: 200 } });
  });
});

test("plugins screen shows primary open button for utility plugins", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const openSpy = vi.spyOn(client, "openPluginView");

  render(<PluginsScreen client={client} botAlias="main" />);

  await user.click(await screen.findByRole("button", { name: "打开仓库大纲" }));

  await waitFor(() => {
    expect(openSpy).toHaveBeenCalledWith("main", "repo-outline", "repo-tree", {});
  });
});
