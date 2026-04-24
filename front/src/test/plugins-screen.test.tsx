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

test("plugins screen lets repo outline pick a folder before opening", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const openSpy = vi.spyOn(client, "openPluginView");

  render(<PluginsScreen client={client} botAlias="main" />);

  expect(screen.queryByRole("button", { name: "选择文件夹大纲" })).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "展开 Repo Outline" }));
  await user.click(await screen.findByRole("button", { name: "选择文件夹大纲" }));
  expect(await screen.findByRole("dialog", { name: "选择要生成大纲的文件夹" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "使用当前目录" }));

  await waitFor(() => {
    expect(openSpy).toHaveBeenCalledWith("main", "repo-outline", "repo-tree", {
      path: expect.any(String),
    });
  });
});

test("plugins screen opens folder picker before installing plugin", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const installSpy = vi.spyOn(client, "installPlugin");

  render(<PluginsScreen client={client} botAlias="main" />);

  await screen.findByText("Vivado Waveform");
  await user.click(screen.getByRole("button", { name: "安装插件" }));
  expect(await screen.findByRole("dialog", { name: "选择插件目录" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "使用当前目录" }));

  await waitFor(() => {
    expect(installSpy).toHaveBeenCalledWith({
      sourcePath: expect.any(String),
    });
  });
});
