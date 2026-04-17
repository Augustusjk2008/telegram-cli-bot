import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

test("desktop workbench shows four panes and persists collapse state", async () => {
  const user = userEvent.setup();
  const onViewModeChange = vi.fn();

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="bot-default.png"
      userAvatarName="user-default.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={onViewModeChange}
      onOpenBotSwitcher={() => {}}
    />,
  );

  expect(screen.getByTestId("desktop-pane-files")).toBeInTheDocument();
  expect(screen.getByTestId("desktop-pane-editor")).toBeInTheDocument();
  expect(screen.getByTestId("desktop-pane-terminal")).toBeInTheDocument();
  expect(screen.getByTestId("desktop-pane-chat")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "折叠左侧文件区" }));
  expect(screen.getByTestId("desktop-pane-files")).toHaveAttribute("data-collapsed", "true");
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"filesCollapsed\":true");

  await user.click(screen.getByRole("button", { name: "手机版" }));
  expect(onViewModeChange).toHaveBeenCalledWith("mobile");
});

test("desktop file clicks open tabs and sync rename and delete actions", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let entries = [
    { name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" },
  ];

  vi.spyOn(client, "listFiles").mockImplementation(async () => ({
    workingDir: "/workspace",
    entries,
  }));
  vi.spyOn(client, "readFileFull").mockImplementation(async (_botAlias, filename) => ({
    content: `FULL:${filename}`,
    mode: "cat",
    fileSizeBytes: 128,
    isFullContent: true,
    lastModifiedNs: 1,
  }));
  vi.spyOn(client, "renamePath").mockImplementation(async (_botAlias, path, newName) => {
    entries = entries.map((entry) => entry.name === path ? { ...entry, name: newName } : entry);
    return {
      oldPath: path,
      path: newName,
    };
  });
  vi.spyOn(client, "deletePath").mockImplementation(async (_botAlias, path) => {
    entries = entries.filter((entry) => entry.name !== path);
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="bot-default.png"
      userAvatarName="user-default.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  expect(await screen.findByRole("tab", { name: /README\.md/ })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重命名 README.md" }));
  await user.clear(screen.getByLabelText("文件名"));
  await user.type(screen.getByLabelText("文件名"), "README-renamed.md");
  await user.click(screen.getByRole("button", { name: "重命名" }));
  expect(await screen.findByRole("tab", { name: /README-renamed\.md/ })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "删除 README-renamed.md" }));
  await waitFor(() => {
    expect(screen.queryByRole("tab", { name: /README-renamed\.md/ })).not.toBeInTheDocument();
  });
});
