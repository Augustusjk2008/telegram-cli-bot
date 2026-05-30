import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PluginsScreen } from "../screens/PluginsScreen";

function expectNoStructuralCard(element: HTMLElement) {
  expect(element).not.toHaveClass("rounded-lg");
  expect(element).not.toHaveClass("rounded-xl");
  expect(element).not.toHaveClass("border");
  expect(element).not.toHaveClass("bg-[var(--surface)]");
}

test("plugins screen toggles plugin enabled state and saves schema config", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateSpy = vi.spyOn(client, "updatePlugin");

  render(<PluginsScreen client={client} botAlias="main" />);

  expect((await screen.findAllByText("Vivado Waveform")).length).toBeGreaterThan(0);
  expect(screen.queryByLabelText("默认页大小")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "禁用 Vivado Waveform" }));

  await waitFor(() => {
    expect(updateSpy).toHaveBeenCalledWith("vivado-waveform", { enabled: false });
  });
  expect(await screen.findByText(/已禁用/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "展开 Timing Report" }));
  const timingPageSize = screen.getByLabelText("默认页大小");
  await user.clear(timingPageSize);
  await user.type(timingPageSize, "200");
  await user.click(screen.getByRole("button", { name: "保存 Timing Report 设置" }));

  await waitFor(() => {
    expect(updateSpy).toHaveBeenCalledWith("timing-report", { config: { defaultPageSize: 200 } });
  });
});


test("plugins screen opens folder picker before installing plugin", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const installSpy = vi.spyOn(client, "installPlugin");

  render(<PluginsScreen client={client} botAlias="main" />);

  expect((await screen.findAllByText("Vivado Waveform")).length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "安装插件" }));
  expect(await screen.findByRole("dialog", { name: "选择含 plugin.json 的插件根目录" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "使用当前目录" }));

  await waitFor(() => {
    expect(installSpy).toHaveBeenCalledWith({
      allowDevSourcePath: true,
      force: true,
      sourcePath: expect.any(String),
    });
  });
});



