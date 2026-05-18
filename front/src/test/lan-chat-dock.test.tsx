import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { LanChatDock } from "../workbench/LanChatDock";

test("lan chat dock opens list and then floating group window", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(<LanChatDock client={client} visible />);

  await user.click(await screen.findByRole("button", { name: /成员聊天/ }));
  expect(await screen.findByRole("dialog", { name: "联机聊天列表" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /群聊/ }));
  expect(await screen.findByRole("dialog", { name: /群聊/ })).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "大家好");
  await user.click(screen.getByRole("button", { name: "发送消息" }));

  await waitFor(() => {
    expect(within(screen.getByRole("dialog", { name: /群聊/ })).getByText("大家好")).toBeInTheDocument();
  });
});

test("lan chat dock shows unread count and opens private chat from online user", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.sendLanChatMessage("group:default", "未读消息");

  render(<LanChatDock client={client} visible />);

  await waitFor(() => {
    expect(screen.getByRole("button", { name: /成员聊天/ })).toHaveTextContent("1");
  });
  await user.click(screen.getByRole("button", { name: /成员聊天/ }));
  await user.click(await screen.findByRole("button", { name: /Bob/ }));

  expect(await screen.findByRole("dialog", { name: /Bob/ })).toBeInTheDocument();
});
