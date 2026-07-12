import { render, screen, waitFor, within } from "@testing-library/react";
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

test("desktop create panel submits unsafe bypass when explicitly checked", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const addBot = vi.spyOn(client, "addBot");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} canRunUnsafeCli />);

  await user.click(await screen.findByRole("button", { name: "新增智能体" }));
  const toggle = await screen.findByLabelText("新智能体默认绕过审批和沙箱");
  expect(toggle).not.toBeChecked();
  expect(toggle).not.toBeDisabled();

  await user.click(toggle);
  await user.type(screen.getByLabelText("新智能体别名"), "desktopunsafe");
  await user.clear(screen.getByLabelText("新智能体工作目录"));
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\desktopunsafe");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
      alias: "desktopunsafe",
      bypassApprovalAndSandbox: true,
    }));
  });
});

test("mock client stores unsafe bypass in new bot cli params", async () => {
  const client = new MockWebBotClient();

  expect((await client.getCliParams("main")).params.yolo).toBe(false);

  await client.addBot({
    alias: "unsafeparams",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\unsafeparams",
    bypassApprovalAndSandbox: true,
  });

  expect((await client.getCliParams("unsafeparams")).params.yolo).toBe(true);
});

test("mock client exposes max and ultra Codex reasoning efforts", async () => {
  const client = new MockWebBotClient();

  const payload = await client.getCliParams("main");

  expect(payload.schema.reasoning_effort?.enum).toEqual([
    "ultra",
    "max",
    "xhigh",
    "high",
    "medium",
    "low",
  ]);
});
