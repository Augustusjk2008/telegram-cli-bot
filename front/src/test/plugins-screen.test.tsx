import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { PluginsScreen } from "../screens/PluginsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

test("plugins screen lists plugins and can refresh plugin registry", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const listPluginsSpy = vi.spyOn(client, "listPlugins");

  render(<PluginsScreen client={client} />);

  expect(await screen.findByRole("heading", { name: "插件" })).toBeInTheDocument();
  expect(screen.getByText("管理本机插件，刷新后重新扫描 ~/.tcb/plugins。")).toBeInTheDocument();
  expect(screen.queryByText("查看已安装插件和支持格式。")).not.toBeInTheDocument();
  expect(screen.queryByText("打开匹配文件会自动进入对应插件视图。")).not.toBeInTheDocument();
  expect(screen.getByText("Vivado Waveform")).toBeInTheDocument();
  expect(screen.getByText("视图 波形预览")).toBeInTheDocument();
  expect(screen.getByText("支持 .vcd")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "刷新" }));
  expect(listPluginsSpy).toHaveBeenLastCalledWith(true);
});
