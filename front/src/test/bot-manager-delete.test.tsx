import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { ClusterModelTiersPanel } from "../components/ClusterModelTiersPanel";
import { BotListScreen } from "../screens/BotListScreen";
import { DesktopBotManagerScreen } from "../screens/DesktopBotManagerScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

test("bot list requires strong confirmation before deleting workspace", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const removeBot = vi.spyOn(client, "removeBot");

  render(<BotListScreen client={client} onSelect={vi.fn()} />);

  await user.click(await screen.findByRole("button", { name: "删除 team2" }));
  const dialog = await screen.findByRole("dialog", { name: "删除智能体 team2" });
  const historyCheckbox = within(dialog).getByLabelText("同时删除历史记录（包含所有子 agents）");
  await user.click(within(dialog).getByLabelText("同时删除工作区和所有记录"));
  expect(historyCheckbox).toBeChecked();
  expect(historyCheckbox).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "彻底删除" })).toBeDisabled();
  await user.type(within(dialog).getByLabelText("输入永久删除确认词"), "永久删除");
  await user.click(within(dialog).getByRole("button", { name: "彻底删除" }));

  expect(removeBot).toHaveBeenCalledWith("team2", { deleteHistory: true, deleteWorkspace: true });
});

test("bot list archives and restores a non-main bot", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const archiveBot = vi.spyOn(client, "archiveBot");
  const unarchiveBot = vi.spyOn(client, "unarchiveBot");

  render(<BotListScreen client={client} onSelect={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "归档 team2" }));
  await waitFor(() => expect(archiveBot).toHaveBeenCalledWith("team2"));
  await user.click(screen.getByRole("button", { name: "取消归档 team2" }));
  await waitFor(() => expect(unarchiveBot).toHaveBeenCalledWith("team2"));
});

test("cluster model tiers select a CLI and expose its parameter namespace", async () => {
  const user = userEvent.setup();
  const onTierConfigChange = vi.fn();
  const props = {
    value: { low: "", medium: "", high: "", professional: "" },
    reasoningEfforts: { low: "", medium: "", high: "", professional: "" },
    modelOptions: [],
    reasoningOptions: [],
    tierConfigs: {
      low: { cliType: "", cliPath: "", provider: "", model: "", reasoningEffort: "" },
      medium: { cliType: "", cliPath: "", provider: "", model: "", reasoningEffort: "" },
      high: { cliType: "", cliPath: "", provider: "", model: "", reasoningEffort: "" },
      professional: { cliType: "", cliPath: "", provider: "", model: "", reasoningEffort: "" },
    },
    inheritedCliType: "codex",
    cliParamsByType: {
      codex: { cliType: "codex", params: {}, defaults: {}, schema: { model: { type: "string", enum: ["codex-model"] } } },
      claude: { cliType: "claude", params: {}, defaults: {}, schema: { model: { type: "string", enum: ["claude-model"] } } },
    },
    onTierConfigChange,
    onChange: vi.fn(),
    onReasoningChange: vi.fn(),
  } as ComponentProps<typeof ClusterModelTiersPanel>;

  render(<ClusterModelTiersPanel {...props} />);
  await user.selectOptions(screen.getByLabelText("低档执行 CLI"), "claude");

  expect(onTierConfigChange).toHaveBeenCalledWith("low", expect.objectContaining({
    cliType: "claude",
    model: "",
    reasoningEffort: "",
  }));
  expect(screen.getByLabelText("低档模型")).toHaveValue("");
});
