import type { ComponentProps } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { TerminalScreen } from "../screens/TerminalScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";

const createTerminalSessionMock = vi.hoisted(() => vi.fn());
const terminalEventHandlers = vi.hoisted(() => ({
  onWriteParsed: undefined as undefined | (() => void),
  onScroll: undefined as undefined | (() => void),
}));
const resizeObserverMock = vi.hoisted(() => ({
  callback: undefined as undefined | ResizeObserverCallback,
}));

const terminalSessionMock = vi.hoisted(() => ({
  sendControl: vi.fn(),
  sendText: vi.fn(),
  fit: vi.fn(),
  focus: vi.fn(),
  dispose: vi.fn(),
  scrollToBottom: vi.fn(),
  setTheme: vi.fn(),
}));

vi.mock("../services/terminalSession", () => ({
  createTerminalSession: createTerminalSessionMock.mockImplementation((_container: HTMLElement, options: { onOpen?: () => void }) => ({
    ...(() => {
      const xtermRoot = document.createElement("div");
      xtermRoot.className = "xterm";
      const xtermViewport = document.createElement("div");
      xtermViewport.className = "xterm-viewport";
      const xtermScreen = document.createElement("div");
      xtermScreen.className = "xterm-screen";
      xtermRoot.appendChild(xtermViewport);
      xtermRoot.appendChild(xtermScreen);
      _container.appendChild(xtermRoot);
      return {};
    })(),
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
    setTheme: terminalSessionMock.setTheme,
  })),
}));

function buildScreen(
  client: MockWebBotClient,
  props: Partial<ComponentProps<typeof TerminalScreen>> = {},
) {
  return (
    <PersistentTerminalProvider client={client}>
      <TerminalScreen
        authToken="123"
        botAlias="main"
        client={client}
        isVisible
        preferredWorkingDir="C:\\workspace\\demo"
        {...props}
      />
    </PersistentTerminalProvider>
  );
}

function renderTerminalScreen(
  props: Partial<ComponentProps<typeof TerminalScreen>> = {},
  client = new MockWebBotClient(),
) {
  return {
    client,
    ...render(buildScreen(client, props)),
  };
}

async function rebuildTerminal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "重建终端" }));
  await screen.findByTestId("terminal-viewport");
}

beforeEach(() => {
  createTerminalSessionMock.mockClear();
  terminalEventHandlers.onWriteParsed = undefined;
  terminalEventHandlers.onScroll = undefined;
  resizeObserverMock.callback = undefined;
  terminalSessionMock.sendControl.mockReset();
  terminalSessionMock.sendText.mockReset();
  terminalSessionMock.fit.mockReset();
  terminalSessionMock.focus.mockReset();
  terminalSessionMock.dispose.mockReset();
  terminalSessionMock.scrollToBottom.mockReset();
  terminalSessionMock.setTheme.mockReset();
  localStorage.clear();
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
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        resizeObserverMock.callback = callback;
      }

      observe() {}

      unobserve() {}

      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("初次渲染不自动启动终端", () => {
  renderTerminalScreen();

  expect(screen.getByText("未启动终端")).toBeInTheDocument();
  expect(createTerminalSessionMock).not.toHaveBeenCalled();
});

test("disabled terminal blocks rebuild, close, shortcut controls and actions", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const rebuildSpy = vi.spyOn(client, "rebuildTerminalSession");
  const closeSpy = vi.spyOn(client, "closeTerminalSession");
  vi.spyOn(client, "getTerminalActionsConfig").mockResolvedValue({
    schemaVersion: 1,
    configPath: "scripts/terminal-actions.json",
    exists: true,
    editable: true,
    runtimePlatform: "windows",
    mtimeNs: "1",
    errors: [],
    actions: [
      {
        id: "build",
        label: "构建",
        icon: "Terminal",
        windowsCommand: "npm run build",
        linuxCommand: "",
        macosCommand: "",
        cwd: ".",
        confirm: false,
        enabled: true,
      },
    ],
  });

  renderTerminalScreen({ disabledReason: "你无权限使用此智能体终端" }, client);

  expect(await screen.findByText("你无权限使用此智能体终端")).toBeInTheDocument();
  const rebuildButton = screen.getByRole("button", { name: "重建终端" });
  const closeButton = screen.getByRole("button", { name: "关闭终端" });
  expect(rebuildButton).toBeDisabled();
  expect(closeButton).toBeDisabled();
  expect(screen.getByRole("button", { name: "Ctrl+C" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "构建" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "编辑快捷命令" })).not.toBeInTheDocument();

  await user.click(rebuildButton);
  await user.click(closeButton);
  await user.click(screen.getByRole("button", { name: "Ctrl+C" }));
  await user.click(screen.getByRole("button", { name: "构建" }));

  expect(rebuildSpy).not.toHaveBeenCalled();
  expect(closeSpy).not.toHaveBeenCalled();
  expect(terminalSessionMock.sendControl).not.toHaveBeenCalled();
});

test("shows mobile terminal controls in the shared terminal screen", async () => {
  const user = userEvent.setup();
  renderTerminalScreen();

  expect(await screen.findByRole("button", { name: "Ctrl+C" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Tab" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Esc" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "键盘" })).toBeInTheDocument();

  await rebuildTerminal(user);
  await user.click(screen.getByRole("button", { name: "Ctrl+C" }));
  expect(terminalSessionMock.sendControl).toHaveBeenCalledWith("\u0003");
});

test("uses a smaller terminal font and keeps scrolling inside xterm viewport", async () => {
  const user = userEvent.setup();
  renderTerminalScreen();
  await rebuildTerminal(user);

  const viewport = await screen.findByTestId("terminal-viewport");

  expect(viewport).toHaveStyle({
    overflow: "hidden",
    touchAction: "pan-x pan-y",
  });
  expect(createTerminalSessionMock).toHaveBeenCalledWith(
    expect.any(HTMLElement),
    expect.objectContaining({
      ownerId: expect.any(String),
      fromSeq: 0,
      fontSize: 12,
      themeName: "deep-space",
    }),
  );
});

test("lets the user close the terminal session", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const closeSpy = vi.spyOn(client, "closeTerminalSession");

  renderTerminalScreen({}, client);
  await rebuildTerminal(user);
  await user.click(await screen.findByRole("button", { name: "关闭终端" }));

  expect(closeSpy).toHaveBeenCalledTimes(1);
  expect(terminalSessionMock.dispose).toHaveBeenCalledTimes(1);
  expect(screen.getAllByText("终端已关闭")).toHaveLength(2);
});

test("shows a jump-to-latest action after scrolling away from terminal output bottom", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  const user = userEvent.setup();

  renderTerminalScreen();
  await rebuildTerminal(user);

  const viewport = await screen.findByTestId("terminal-viewport");
  const scrollTarget = viewport.querySelector(".xterm-viewport") as HTMLDivElement;
  Object.defineProperty(scrollTarget, "scrollTop", { value: 20, writable: true });
  Object.defineProperty(scrollTarget, "scrollHeight", { value: 500, writable: true });
  Object.defineProperty(scrollTarget, "clientHeight", { value: 200, writable: true });

  await act(async () => {
    terminalEventHandlers.onScroll?.();
  });

  expect(await screen.findByRole("button", { name: "回到最新输出" })).toBeInTheDocument();
});

test("coalesces follow-scroll work for bursty terminal output into one animation frame", async () => {
  const rafCallbacks: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
    rafCallbacks.push(callback);
    return rafCallbacks.length;
  }));
  const user = userEvent.setup();

  renderTerminalScreen();
  await rebuildTerminal(user);
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

test("refits the terminal when the viewport size changes without rebuilding the session", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  const user = userEvent.setup();

  renderTerminalScreen();
  await rebuildTerminal(user);

  const viewport = await screen.findByTestId("terminal-viewport");
  terminalSessionMock.fit.mockClear();

  Object.defineProperty(viewport, "clientWidth", { value: 960, configurable: true });
  Object.defineProperty(viewport, "clientHeight", { value: 480, configurable: true });

  act(() => {
    resizeObserverMock.callback?.([], {} as ResizeObserver);
  });

  expect(terminalSessionMock.fit).toHaveBeenCalledTimes(1);
});

test("theme change updates terminal without rebuilding the session", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const view = render(buildScreen(client, { themeName: "deep-space" }));

  await rebuildTerminal(user);
  await screen.findByTestId("terminal-viewport");
  createTerminalSessionMock.mockClear();
  terminalSessionMock.setTheme.mockClear();

  view.rerender(buildScreen(client, { themeName: "classic" }));

  await waitFor(() => {
    expect(terminalSessionMock.setTheme).toHaveBeenCalledWith("classic");
  });
  expect(createTerminalSessionMock).not.toHaveBeenCalled();
});
