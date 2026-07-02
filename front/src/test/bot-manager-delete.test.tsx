import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
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

test("desktop bulk delete does not expose workspace delete", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);

  await user.click(await screen.findByLabelText("选择 team2"));
  await user.click(screen.getByRole("button", { name: "批量删除" }));

  const dialog = await screen.findByRole("dialog", { name: "批量删除 1 个智能体" });
  expect(within(dialog).getByLabelText("同时删除历史记录（包含所有子 agents）")).toBeInTheDocument();
  expect(within(dialog).queryByLabelText("同时删除工作区和所有记录")).not.toBeInTheDocument();
  expect(within(dialog).getByText("彻底删除工作区请逐个操作。")).toBeInTheDocument();
});
