import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { TerminalAction, TerminalActionsConfig } from "../services/types";
import { TerminalActionsBar } from "../terminal/TerminalActionsBar";
import { TerminalActionsConfigDialog } from "../terminal/TerminalActionsConfigDialog";
import { getTerminalActionIcon } from "../terminal/terminalActionIcons";

const actions: TerminalAction[] = [
  {
    id: "build",
    label: "构建",
    icon: "Hammer",
    windowsCommand: "npm run build",
    linuxCommand: "",
    macosCommand: "npm run build:mac",
    cwd: ".",
    confirm: false,
    enabled: true,
  },
  {
    id: "linux-only",
    label: "仅 Linux",
    icon: "Play",
    windowsCommand: "",
    linuxCommand: "echo linux",
    macosCommand: "",
    cwd: ".",
    confirm: false,
    enabled: true,
  },
  {
    id: "hidden",
    label: "隐藏",
    icon: "Play",
    windowsCommand: "echo hidden",
    linuxCommand: "",
    macosCommand: "",
    cwd: ".",
    confirm: false,
    enabled: false,
  },
];

const config: TerminalActionsConfig = {
  schemaVersion: 1,
  configPath: "C:/repo/scripts/terminal-actions.json",
  exists: true,
  mtimeNs: "123",
  editable: true,
  errors: [],
  runtimePlatform: "windows",
  actions: [actions[0]],
};

test("falls back to terminal icon for invalid icon names", () => {
  const Icon = getTerminalActionIcon("BadIcon");
  render(<Icon aria-label="icon" />);
  expect(screen.getByLabelText("icon")).toBeInTheDocument();
});

test("TerminalActionsBar renders enabled actions and edit button", async () => {
  const runAction = vi.fn();
  const edit = vi.fn();
  const user = userEvent.setup();

  render(
    <TerminalActionsBar
      actions={actions}
      runtimePlatform="windows"
      canEdit
      runningActionId=""
      onRunAction={runAction}
      onOpenConfig={edit}
    />,
  );

  expect(screen.getByRole("button", { name: "构建" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "仅 Linux" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "隐藏" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "构建" }));
  expect(runAction).toHaveBeenCalledWith(actions[0]);
  await user.click(screen.getByRole("button", { name: "编辑快捷命令" }));
  expect(edit).toHaveBeenCalled();
});

test("TerminalActionsConfigDialog edits and saves actions", async () => {
  const save = vi.fn();
  const user = userEvent.setup();

  render(<TerminalActionsConfigDialog config={config} saving={false} error="" onSave={save} onClose={vi.fn()} />);

  await user.clear(screen.getByLabelText("名称"));
  await user.type(screen.getByLabelText("名称"), "构建前端");
  await user.click(screen.getByRole("button", { name: "保存快捷命令" }));

  expect(save).toHaveBeenCalledWith({
    schemaVersion: 1,
    actions: [
      {
        id: "build",
        label: "构建前端",
        icon: "Hammer",
        windowsCommand: "npm run build",
        linuxCommand: "",
        macosCommand: "npm run build:mac",
        cwd: ".",
        confirm: false,
        enabled: true,
      },
    ],
  });
});

test("TerminalActionsConfigDialog escapes pane stacking contexts", () => {
  render(
    <div data-testid="stacked-pane" style={{ position: "relative", zIndex: 1, transform: "translateZ(0)" }}>
      <TerminalActionsConfigDialog config={config} saving={false} error="" onSave={vi.fn()} onClose={vi.fn()} />
    </div>,
  );

  expect(screen.getByRole("dialog", { name: "终端快捷命令" }).parentElement).toBe(document.body);
});

test("TerminalActionsConfigDialog shows icon picker and saves selected icon", async () => {
  const save = vi.fn();
  const user = userEvent.setup();

  render(<TerminalActionsConfigDialog config={config} saving={false} error="" onSave={save} onClose={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: "选择图标" }));
  expect(screen.getByRole("listbox", { name: "图标列表" })).toBeInTheDocument();
  expect(screen.getByText("关机")).toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: "关机" }));
  await user.click(screen.getByRole("button", { name: "保存快捷命令" }));

  expect(save).toHaveBeenCalledWith({
    schemaVersion: 1,
    actions: [
      {
        id: "build",
        label: "构建",
        icon: "PowerOff",
        windowsCommand: "npm run build",
        linuxCommand: "",
        macosCommand: "npm run build:mac",
        cwd: ".",
        confirm: false,
        enabled: true,
      },
    ],
  });
});

test("TerminalActionsConfigDialog can add an action", async () => {
  const save = vi.fn();
  const user = userEvent.setup();

  render(<TerminalActionsConfigDialog config={{ ...config, actions: [] }} saving={false} error="" onSave={save} onClose={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: "新增快捷命令" }));
  await user.clear(screen.getByLabelText("ID"));
  await user.type(screen.getByLabelText("ID"), "test");
  await user.clear(screen.getByLabelText("Windows 命令"));
  await user.type(screen.getByLabelText("Windows 命令"), "python -m pytest tests -q");
  await user.click(screen.getByRole("button", { name: "保存快捷命令" }));

  expect(save).toHaveBeenCalledWith({
    schemaVersion: 1,
    actions: [expect.objectContaining({ id: "test", windowsCommand: "python -m pytest tests -q" })],
  });
});

test("TerminalActionsBar uses macOS command then falls back to Linux", async () => {
  const runAction = vi.fn();
  const user = userEvent.setup();

  render(
    <TerminalActionsBar
      actions={actions}
      runtimePlatform="macos"
      canEdit={false}
      runningActionId=""
      onRunAction={runAction}
      onOpenConfig={vi.fn()}
    />,
  );

  const macAction = screen.getByRole("button", { name: "构建" });
  expect(macAction).toHaveAttribute("title", "npm run build:mac");
  expect(screen.getByRole("button", { name: "仅 Linux" })).toHaveAttribute("title", "echo linux");
  await user.click(screen.getByRole("button", { name: "仅 Linux" }));
  expect(runAction).toHaveBeenCalledWith(actions[1]);
});

test("TerminalActionsConfigDialog shows config parse errors", () => {
  render(
    <TerminalActionsConfigDialog
      config={{ ...config, errors: ["无法解析 JSON: Expecting property name"] }}
      saving={false}
      error=""
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  expect(screen.getByText(/无法解析 JSON/)).toBeInTheDocument();
});

test("TerminalActionsConfigDialog disables save for read-only config", () => {
  render(
    <TerminalActionsConfigDialog
      config={{ ...config, editable: false }}
      saving={false}
      error=""
      onSave={vi.fn()}
      onClose={vi.fn()}
    />,
  );

  expect(screen.getByRole("button", { name: "无保存权限" })).toBeDisabled();
});
