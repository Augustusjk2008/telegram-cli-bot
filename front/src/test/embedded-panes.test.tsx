import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { TerminalScreen } from "../screens/TerminalScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

vi.mock("../services/terminalSession", () => ({
  createTerminalSession: vi.fn((_container: HTMLElement, options: { onOpen?: () => void }) => ({
    term: {
      onWriteParsed: vi.fn(() => ({ dispose: vi.fn() })),
      onScroll: vi.fn(() => ({ dispose: vi.fn() })),
      scrollToBottom: vi.fn(),
      textarea: document.createElement("textarea"),
    },
    connect: vi.fn(() => options.onOpen?.()),
    dispose: vi.fn(),
    fit: vi.fn(),
    focus: vi.fn(),
    sendControl: vi.fn(),
    sendText: vi.fn(),
  })),
}));

test("embedded chat hides immersive controls but keeps the composer", async () => {
  render(
    <ChatScreen
      botAlias="main"
      botAvatarName="bot-default.png"
      userAvatarName="user-default.png"
      client={new MockWebBotClient()}
      isVisible
      embedded
    />,
  );

  expect(await screen.findByPlaceholderText("输入消息")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "进入沉浸模式" })).not.toBeInTheDocument();
});

test("embedded terminal hides the mobile control pad but keeps the terminal root", async () => {
  render(
    <TerminalScreen
      authToken="123"
      botAlias="main"
      client={new MockWebBotClient()}
      isVisible
      preferredWorkingDir="C:\\workspace\\demo"
      themeName="deep-space"
      embedded
    />,
  );

  expect(await screen.findByTestId("terminal-screen-root")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Ctrl+C" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "进入沉浸模式" })).not.toBeInTheDocument();
});
