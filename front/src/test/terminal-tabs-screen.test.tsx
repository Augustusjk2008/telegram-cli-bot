import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TerminalTabsScreen } from "../screens/TerminalTabsScreen";
import type { PersistentTerminalSnapshot, TerminalActionsConfig } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";

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
