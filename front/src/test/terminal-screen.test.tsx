import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { TerminalScreen } from "../screens/TerminalScreen";

const terminalSessionMock = vi.hoisted(() => ({
  sendControl: vi.fn(),
  sendText: vi.fn(),
  fit: vi.fn(),
  focus: vi.fn(),
  dispose: vi.fn(),
  scrollToBottom: vi.fn(),
}));

vi.mock("../services/terminalSession", () => ({
  createTerminalSession: vi.fn((_container: HTMLElement, options: { onOpen?: () => void }) => ({
    term: {
      onWriteParsed: vi.fn(() => ({ dispose: vi.fn() })),
      onScroll: vi.fn(() => ({ dispose: vi.fn() })),
      scrollToBottom: terminalSessionMock.scrollToBottom,
      textarea: document.createElement("textarea"),
    },
    connect: vi.fn(() => options.onOpen?.()),
    dispose: terminalSessionMock.dispose,
    fit: terminalSessionMock.fit,
    focus: terminalSessionMock.focus,
    sendControl: terminalSessionMock.sendControl,
    sendText: terminalSessionMock.sendText,
  })),
}));

beforeEach(() => {
  terminalSessionMock.sendControl.mockReset();
  terminalSessionMock.sendText.mockReset();
  terminalSessionMock.fit.mockReset();
  terminalSessionMock.focus.mockReset();
  terminalSessionMock.dispose.mockReset();
  terminalSessionMock.scrollToBottom.mockReset();
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("pointer: coarse"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

test("shows mobile terminal controls in the shared terminal screen", async () => {
  const user = userEvent.setup();

  render(
    <TerminalScreen
      authToken="123"
      botAlias="main"
      isVisible
      preferredWorkingDir="C:\\workspace\\demo"
    />,
  );

  expect(await screen.findByRole("button", { name: "Ctrl+C" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Tab" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Esc" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "键盘" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Ctrl+C" }));
  expect(terminalSessionMock.sendControl).toHaveBeenCalledWith("\u0003");
});

test("shows a jump-to-latest action after scrolling away from terminal output bottom", async () => {
  render(
    <TerminalScreen
      authToken="123"
      botAlias="main"
      isVisible
      preferredWorkingDir="C:\\workspace\\demo"
    />,
  );

  const viewport = await screen.findByTestId("terminal-viewport");
  Object.defineProperty(viewport, "scrollTop", { value: 20, writable: true });
  Object.defineProperty(viewport, "scrollHeight", { value: 500, writable: true });
  Object.defineProperty(viewport, "clientHeight", { value: 200, writable: true });

  fireEvent.scroll(viewport);

  expect(screen.getByRole("button", { name: "回到最新输出" })).toBeInTheDocument();
});
