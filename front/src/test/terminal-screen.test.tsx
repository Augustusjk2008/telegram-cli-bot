import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { TerminalScreen } from "../screens/TerminalScreen";

const createTerminalSessionMock = vi.hoisted(() => vi.fn());
const terminalEventHandlers = vi.hoisted(() => ({
  onWriteParsed: undefined as undefined | (() => void),
  onScroll: undefined as undefined | (() => void),
}));

const terminalSessionMock = vi.hoisted(() => ({
  sendControl: vi.fn(),
  sendText: vi.fn(),
  fit: vi.fn(),
  focus: vi.fn(),
  dispose: vi.fn(),
  scrollToBottom: vi.fn(),
}));

vi.mock("../services/terminalSession", () => ({
  createTerminalSession: createTerminalSessionMock.mockImplementation((_container: HTMLElement, options: { onOpen?: () => void }) => ({
    term: {
      onWriteParsed: vi.fn((handler: () => void) => {
        terminalEventHandlers.onWriteParsed = handler;
        return { dispose: vi.fn() };
      }),
      onScroll: vi.fn((handler: () => void) => {
        terminalEventHandlers.onScroll = handler;
        return { dispose: vi.fn() };
      }),
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
  createTerminalSessionMock.mockClear();
  terminalEventHandlers.onWriteParsed = undefined;
  terminalEventHandlers.onScroll = undefined;
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

test("uses a smaller terminal font and a viewport that supports bidirectional drag", async () => {
  render(
    <TerminalScreen
      authToken="123"
      botAlias="main"
      isVisible
      preferredWorkingDir="C:\\workspace\\demo"
    />,
  );

  const viewport = await screen.findByTestId("terminal-viewport");

  expect(viewport).toHaveStyle({
    overflow: "scroll",
    touchAction: "pan-x pan-y",
  });
  expect(createTerminalSessionMock).toHaveBeenCalledWith(
    expect.any(HTMLElement),
    expect.objectContaining({
      fontSize: 12,
      shell: "auto",
      themeName: "deep-space",
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("removes helper copy and lets the user close the terminal session", async () => {
  const user = userEvent.setup();

  render(
    <TerminalScreen
      authToken="123"
      botAlias="main"
      isVisible
      preferredWorkingDir="C:\\workspace\\demo"
    />,
  );

  expect(screen.queryByText(/手机优先：看输出为主/)).not.toBeInTheDocument();

  await user.click(await screen.findByRole("button", { name: "关闭终端" }));

  expect(terminalSessionMock.dispose).toHaveBeenCalledTimes(1);
  expect(screen.getByText("终端已关闭")).toBeInTheDocument();
});

test("shows a jump-to-latest action after scrolling away from terminal output bottom", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });

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

  await act(async () => {
    fireEvent.scroll(viewport);
  });

  expect(await screen.findByRole("button", { name: "回到最新输出" })).toBeInTheDocument();
});

test("coalesces follow-scroll work for bursty terminal output into one animation frame", async () => {
  const rafCallbacks: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
    rafCallbacks.push(callback);
    return rafCallbacks.length;
  }));

  render(
    <TerminalScreen
      authToken="123"
      botAlias="main"
      isVisible
      preferredWorkingDir="C:\\workspace\\demo"
    />,
  );

  await screen.findByTestId("terminal-viewport");

  terminalSessionMock.scrollToBottom.mockClear();

  act(() => {
    terminalEventHandlers.onWriteParsed?.();
    terminalEventHandlers.onWriteParsed?.();
    terminalEventHandlers.onWriteParsed?.();
  });

  expect(terminalSessionMock.scrollToBottom).not.toHaveBeenCalled();

  act(() => {
    const callbacks = rafCallbacks.splice(0);
    callbacks.forEach((callback) => callback(0));
  });

  expect(terminalSessionMock.scrollToBottom).toHaveBeenCalledTimes(1);
});
