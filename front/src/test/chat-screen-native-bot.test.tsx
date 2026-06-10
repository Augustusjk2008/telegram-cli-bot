import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

afterEach(() => {
  localStorage.clear();
});

test("pure native bot hides execution switch and sends native mode by default", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "native1",
    botMode: "cli",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\native1",
    avatarName: "avatar_01.png",
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
  });
  const sendMessage = vi.spyOn(client, "sendMessage");

  render(<ChatScreen botAlias="native1" client={client} />);

  const composer = await screen.findByPlaceholderText("输入消息");
  expect(screen.queryByRole("button", { name: "CLI" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "原生 agent" })).not.toBeInTheDocument();

  await user.type(composer, "hello");
  await user.click(screen.getByLabelText("发送"));

  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalled();
  });
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ executionMode: "native_agent" });
});
