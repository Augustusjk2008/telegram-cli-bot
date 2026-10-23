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

test("desktop manager opens the shared current-agent settings entry", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const openSettings = vi.fn();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onOpenBotSettings={openSettings} />);
  await user.click(await screen.findByRole("button", { name: "打开 team2 设置" }));
  expect(openSettings).toHaveBeenCalledWith("team2");
  expect(screen.queryByRole("heading", { name: "集群与子智能体" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存 CLI 配置" })).not.toBeInTheDocument();
});

test("desktop manager keeps the create panel and opens settings after creation", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const addBot = vi.spyOn(client, "addBot");
  const openSettings = vi.fn();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} onOpenBotSettings={openSettings} onBotCreated={openSettings} />);
  await user.type(await screen.findByLabelText("新智能体别名"), "desktop-settings");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));
  await waitFor(() => expect(addBot).toHaveBeenCalledWith(expect.objectContaining({ alias: "desktop-settings" })));
  expect(openSettings).toHaveBeenCalledWith("desktop-settings");
});

test("cluster model tiers configure model and reasoning independently", async () => {
  const user = userEvent.setup();
  const onReasoningChange = vi.fn();
  const props = {
    value: { low: "fast-model", medium: "", high: "" },
    reasoningEfforts: { low: "medium", medium: "", high: "" },
    modelOptions: ["fast-model", "strong-model"],
    reasoningOptions: ["ultra", "max", "xhigh", "high", "medium", "low"],
    onChange: vi.fn(),
    onReasoningChange,
  } as ComponentProps<typeof ClusterModelTiersPanel>;

  render(<ClusterModelTiersPanel {...props} />);
  expect(screen.getByLabelText("低档模型")).toHaveValue("fast-model");
  await user.selectOptions(screen.getByLabelText("低档思考深度"), "ultra");
  expect(onReasoningChange).toHaveBeenCalledWith({ low: "ultra", medium: "", high: "" });
});
