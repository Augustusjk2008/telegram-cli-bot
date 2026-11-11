import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { PluginsScreen } from "../screens/PluginsScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { PluginInstallBatchItem } from "../services/types";

function installedPlugin(overrides: Partial<PluginInstallBatchItem>): PluginInstallBatchItem {
  return {
    id: "sample",
    schemaVersion: 2,
    name: "Sample",
    version: "0.1.0",
    description: "",
    views: [],
    fileHandlers: [],
    catalogActions: [],
    runtime: {
      type: "python",
      entry: "main.py",
      protocol: "jsonrpc-stdio",
      permissions: { workspaceRead: true, workspaceList: false, workspaceWrite: false, tempArtifacts: false },
    },
    installOutcome: "installed",
    previousVersion: null,
    ...overrides,
  };
}

test("a directory install ends with a dialog counting new and upgraded plugins", async () => {
  const client = new MockWebBotClient();
  const install = vi.spyOn(client, "installPluginsFromPath").mockResolvedValue({
    sourcePath: "/srv/plugins",
    discovered: 3,
    installed: [
      installedPlugin({ id: "csv", name: "CSV Preview", version: "0.2.0", installOutcome: "upgraded", previousVersion: "0.1.0" }),
      installedPlugin({ id: "pdf", name: "PDF Preview" }),
      installedPlugin({ id: "hex", name: "Hex Preview", installOutcome: "reinstalled", previousVersion: "0.1.0" }),
    ],
  });
  render(<PluginsScreen client={client} embedded />);

  const installButton = screen.getByRole("button", { name: "安装插件" });
  await waitFor(() => expect(installButton).toBeEnabled());
  fireEvent.click(installButton);
  const picker = await screen.findByRole("dialog", { name: "选择插件目录（递归查找 plugin.json）" });
  const useDirectory = within(picker).getByRole("button", { name: "使用当前目录" });
  await waitFor(() => expect(useDirectory).toBeEnabled());
  fireEvent.click(useDirectory);

  const result = await screen.findByRole("dialog", { name: "插件安装完成" });
  expect(install).toHaveBeenCalledWith(expect.any(String), { force: true, allowDevSourcePath: true });
  expect(result).toHaveAccessibleDescription("新安装 1 个，升级 1 个，重新安装 1 个");
  const rows = within(within(result).getByRole("list", { name: "插件安装明细" })).getAllByRole("listitem");
  expect(rows.map((row) => row.textContent)).toEqual([
    "CSV Previewv0.1.0 → v0.2.0升级",
    "PDF Previewv0.1.0新安装",
    "Hex Previewv0.1.0重新安装",
  ]);

  fireEvent.click(within(result).getByRole("button", { name: "确定" }));
  expect(screen.queryByRole("dialog", { name: "插件安装完成" })).not.toBeInTheDocument();
});
