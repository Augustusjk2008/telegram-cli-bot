import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

test("desktop workbench restores persisted pane sizes from storage", () => {
  localStorage.setItem(
    "web-workbench-pane-state",
    JSON.stringify({
      filesCollapsed: false,
      editorCollapsed: false,
      terminalCollapsed: false,
      chatCollapsed: false,
      filesWidthPx: 360,
      chatWidthPx: 420,
      editorHeightPx: 460,
    }),
  );

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="bot-default.png"
      userAvatarName="user-default.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "360px 8px minmax(0, 1fr) 8px 420px",
  });
  expect(screen.getByTestId("desktop-workbench-center-rows")).toHaveStyle({
    gridTemplateRows: "460px 8px minmax(160px, 1fr)",
  });
});

test("desktop workbench updates pane sizes when separators are dragged", () => {
  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="bot-default.png"
      userAvatarName="user-default.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  const leftSeparator = screen.getByRole("separator", { name: "调整文件区宽度" });
  fireEvent.pointerDown(leftSeparator, { clientX: 320, pointerId: 1 });
  fireEvent.pointerMove(window, { clientX: 380, pointerId: 1 });
  fireEvent.pointerUp(window, { clientX: 380, pointerId: 1 });

  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "380px 8px minmax(0, 1fr) 8px 384px",
  });

  const centerSeparator = screen.getByRole("separator", { name: "调整编辑器高度" });
  fireEvent.pointerDown(centerSeparator, { clientY: 420, pointerId: 2 });
  fireEvent.pointerMove(window, { clientY: 500, pointerId: 2 });
  fireEvent.pointerUp(window, { clientY: 500, pointerId: 2 });

  expect(screen.getByTestId("desktop-workbench-center-rows")).toHaveStyle({
    gridTemplateRows: "500px 8px minmax(160px, 1fr)",
  });
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"filesWidthPx\":380");
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"editorHeightPx\":500");
});

test("desktop workbench clamps invalid stored pane sizes and restores them after collapse", async () => {
  const user = userEvent.setup();

  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function () {
    const testId = (this as HTMLElement).getAttribute("data-testid");
    if (testId === "desktop-workbench-columns") {
      return {
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1200,
        bottom: 800,
        width: 1200,
        height: 800,
        toJSON() {
          return {};
        },
      };
    }

    if (testId === "desktop-workbench-center-rows") {
      return {
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1000,
        bottom: 700,
        width: 1000,
        height: 700,
        toJSON() {
          return {};
        },
      };
    }

    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 1000,
      bottom: 700,
      width: 1000,
      height: 700,
      toJSON() {
        return {};
      },
    };
  });

  localStorage.setItem(
    "web-workbench-pane-state",
    JSON.stringify({
      filesCollapsed: false,
      editorCollapsed: false,
      terminalCollapsed: false,
      chatCollapsed: false,
      filesWidthPx: 900,
      chatWidthPx: 700,
      editorHeightPx: 80,
    }),
  );

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="bot-default.png"
      userAvatarName="user-default.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await waitFor(() => {
    expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
      gridTemplateColumns: "420px 8px minmax(0, 1fr) 8px 260px",
    });
  });
  expect(screen.getByTestId("desktop-workbench-center-rows")).toHaveStyle({
    gridTemplateRows: "220px 8px minmax(160px, 1fr)",
  });

  await user.click(screen.getByRole("button", { name: "折叠左侧文件区" }));
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "72px 8px minmax(0, 1fr) 8px 260px",
  });

  await user.click(screen.getByRole("button", { name: "展开左侧文件区" }));
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "420px 8px minmax(0, 1fr) 8px 260px",
  });

  expect(screen.getByTestId("desktop-pane-files")).not.toHaveClass("rounded-2xl");
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
