import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TerminalTabsScreen } from "../screens/TerminalTabsScreen";
import type { PersistentTerminalSnapshot, TerminalActionsConfig } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";

const terminalSessionMock = vi.hoisted(() => ({
  create: vi.fn(),
}));

vi.mock("../services/terminalSession", () => ({
  createTerminalSession: terminalSessionMock.create,
}));

const snapshot = (): PersistentTerminalSnapshot => ({
  started: false,
  closed: false,
  cwd: "C:/workspace",
  ptyMode: null,
  connectionText: "未启动",
  lastSeq: 0,
});

const actionsConfig: TerminalActionsConfig = {
  schemaVersion: 1,
  actions: [
    {
      id: "new-terminal",
      label: "新开终端",
      icon: "Terminal",
      windowsCommand: "cmd",
      linuxCommand: "bash",
      macosCommand: "zsh",
      cwd: "",
      confirm: false,
      enabled: true,
    },
  ],
  configPath: "",
  exists: true,
  mtimeNs: "0",
  editable: false,
  errors: [],
  runtimePlatform: "windows",
};

beforeEach(() => {
  localStorage.clear();
  terminalSessionMock.create.mockReset();
});

test("没有打开终端时仍显示可新建终端的预设命令", async () => {
  const client = {
    getTerminalSession: vi.fn(async () => snapshot()),
    getTerminalActionsConfig: vi.fn(async () => actionsConfig),
    createTerminalSession: vi.fn(async () => snapshot()),
    closeTerminalSession: vi.fn(async () => ({ ...snapshot(), closed: true, connectionText: "终端已关闭" })),
  } as unknown as WebBotClient;

  render(
    <PersistentTerminalProvider client={client}>
      <TerminalTabsScreen
        authToken="token"
        botAlias="repo"
        client={client}
        isVisible
        preferredWorkingDir="C:/workspace"
      />
    </PersistentTerminalProvider>,
  );

  await waitFor(() => expect(client.getTerminalActionsConfig).toHaveBeenCalledWith("repo"));
  fireEvent.click(screen.getByRole("button", { name: "关闭终端 1" }));

  await waitFor(() => expect(screen.queryByRole("tab")).not.toBeInTheDocument());
  expect(await screen.findByRole("button", { name: "新开终端" })).toBeInTheDocument();
});

test("嵌入式终端把预设和聚焦按钮合并到终端标签栏", async () => {
  const client = {
    getTerminalSession: vi.fn(async () => snapshot()),
    getTerminalActionsConfig: vi.fn(async () => ({ ...actionsConfig, editable: true })),
    createTerminalSession: vi.fn(async () => snapshot()),
    closeTerminalSession: vi.fn(async () => ({ ...snapshot(), closed: true, connectionText: "终端已关闭" })),
  } as unknown as WebBotClient;

  render(
    <PersistentTerminalProvider client={client}>
      <TerminalTabsScreen
        authToken="token"
        botAlias="repo"
        client={client}
        isVisible
        preferredWorkingDir="C:/workspace"
        embedded
        onToggleFocus={vi.fn()}
      />
    </PersistentTerminalProvider>,
  );

  const toolbar = await screen.findByTestId("terminal-tabs-toolbar");
  expect(within(toolbar).getByRole("button", { name: "编辑快捷命令" })).toBeInTheDocument();
  expect(within(toolbar).getByRole("button", { name: "聚焦终端" })).toBeInTheDocument();
  expect(within(screen.getByRole("tablist", { name: "终端选项卡" })).queryByRole("button", { name: "聚焦终端" })).not.toBeInTheDocument();
  expect(screen.queryByText("未启动", { exact: true })).not.toBeInTheDocument();
});

test("切回终端标签时把该标签上次已渲染的恢复位置交给新 xterm", async () => {
  localStorage.setItem("web-terminal-tabs:v1", JSON.stringify([
    { id: "tab-a", ownerId: "owner-a", title: "终端 A", cwd: "C:/a", shell: "auto" },
    { id: "tab-b", ownerId: "owner-b", title: "终端 B", cwd: "C:/b", shell: "auto" },
  ]));
  terminalSessionMock.create.mockImplementation((_container: HTMLElement, options: {
    ownerId: string;
    onOpen?: () => void;
    onRecoveryState?: (state: { streamId: string; lastAppliedSequence: number }) => void;
  }) => ({
    term: {
      onWriteParsed: vi.fn(() => ({ dispose: vi.fn() })),
      onScroll: vi.fn(() => ({ dispose: vi.fn() })),
      scrollToBottom: vi.fn(),
      textarea: document.createElement("textarea"),
    },
    connect: vi.fn(() => {
      options.onRecoveryState?.({
        streamId: `stream-${options.ownerId}`,
        lastAppliedSequence: options.ownerId === "owner-a" ? 7 : 3,
      });
      options.onOpen?.();
    }),
    dispose: vi.fn(),
    fit: vi.fn(),
    focus: vi.fn(),
    getRecoveryState: vi.fn(),
    sendControl: vi.fn(),
    sendText: vi.fn(),
    setTheme: vi.fn(),
  }));
  const client = {
    getTerminalSession: vi.fn(async (ownerId: string) => ({
      ...snapshot(),
      started: true,
      cwd: ownerId === "owner-a" ? "C:/a" : "C:/b",
      ptyMode: true,
      connectionText: "运行中",
      lastSeq: ownerId === "owner-a" ? 7 : 3,
    })),
    getTerminalActionsConfig: vi.fn(async () => actionsConfig),
    closeTerminalSession: vi.fn(),
  } as unknown as WebBotClient;

  render(
    <PersistentTerminalProvider client={client}>
      <TerminalTabsScreen
        authToken="token"
        botAlias="repo"
        client={client}
        isVisible
        preferredWorkingDir="C:/workspace"
      />
    </PersistentTerminalProvider>,
  );

  await waitFor(() => expect(terminalSessionMock.create).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("tab", { name: "终端 B" }));
  await waitFor(() => expect(terminalSessionMock.create).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("tab", { name: "终端 A" }));
  await waitFor(() => expect(terminalSessionMock.create).toHaveBeenCalledTimes(3));

  expect(terminalSessionMock.create.mock.calls[2]?.[1]).toMatchObject({
    ownerId: "owner-a",
    previousRecoveryState: {
      streamId: "stream-owner-a",
      lastAppliedSequence: 7,
    },
  });
});
