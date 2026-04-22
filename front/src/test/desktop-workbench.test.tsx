import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import { WorkbenchStatusBar } from "../workbench/WorkbenchStatusBar";

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
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
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

  await user.click(screen.getByRole("button", { name: "折叠侧边栏" }));
  expect(screen.getByTestId("desktop-pane-files")).toHaveAttribute("data-collapsed", "true");
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"sidebarCollapsed\":true");

  await user.click(screen.getByRole("button", { name: "手机版" }));
  expect(onViewModeChange).toHaveBeenCalledWith("mobile");
});

test("desktop titlebar layout controls toggle visible panes", async () => {
  const user = userEvent.setup();

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  expect(screen.getByRole("group", { name: "布局开关" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "隐藏底部终端" }));
  expect(screen.getByTestId("desktop-pane-terminal")).toHaveAttribute("data-collapsed", "true");
  expect(screen.queryByRole("separator", { name: "调整编辑器高度" })).not.toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-center-rows")).toHaveStyle({
    gridTemplateRows: "minmax(0, 1fr) 0px 0px",
  });
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"terminalCollapsed\":true");

  await user.click(screen.getByRole("button", { name: "隐藏右侧聊天" }));
  expect(screen.getByTestId("desktop-pane-chat")).toHaveAttribute("data-collapsed", "true");
  expect(screen.queryByRole("separator", { name: "调整聊天区宽度" })).not.toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "320px 8px minmax(0, 1fr) 0px 0px",
  });
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"chatCollapsed\":true");

  await user.click(screen.getByRole("button", { name: "隐藏左侧栏" }));
  expect(screen.getByTestId("desktop-pane-files")).toHaveAttribute("data-collapsed", "true");
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "48px 8px minmax(0, 1fr) 0px 0px",
  });
});

test("desktop workbench shows the status bar and uses the left rail to switch sidebar content", async () => {
  const user = userEvent.setup();

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  expect(screen.getByTestId("desktop-workbench-titlebar")).toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-activity-rail")).toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-statusbar")).toBeInTheDocument();
  expect(screen.getByText("AI 等待中")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "折叠编辑区" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "折叠右侧聊天区" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "AI 助手" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Git" }));
  expect(await screen.findByText("当前分支")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "调试" }));
  expect(await screen.findByTestId("debug-pane")).toBeInTheDocument();
  expect(screen.getByText("(gdb) Remote Debug")).toBeInTheDocument();
  expect(screen.queryByLabelText("准备命令")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开远端参数" }));
  expect(screen.getByLabelText("准备命令")).toHaveValue(".\\debug.bat");
  expect(screen.getByRole("toolbar", { name: "调试控制" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "启动调试" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "设置" }));
  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "文件" }));
  expect(await screen.findByTestId("desktop-file-tree-scroll")).toBeInTheDocument();
});

test("desktop debug pane uses generic unsupported C++ message", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getDebugProfile").mockResolvedValue(null);

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(screen.getByRole("button", { name: "调试" }));

  expect(await screen.findByText("当前工作目录不支持 C++ 调试")).toBeInTheDocument();
  expect(screen.queryByText("当前工作目录不支持 MB_DDF 调试")).not.toBeInTheDocument();
});

test("status bar shows debug phase alongside terminal and AI state", () => {
  render(
    <WorkbenchStatusBar
      activeFilePath="src/main.cpp"
      fileDirty={false}
      terminalStatus={{ connected: true, connectionText: "终端已连接", currentCwd: "C:\\workspace" }}
      chatStatus={{ state: "idle", processing: false }}
      debugStatus={{ phase: "paused", connectionText: "调试已暂停", targetText: "192.168.1.29:1234" }}
      restoreState="clean"
      viewMode="desktop"
    />,
  );

  expect(screen.getByText("调试已暂停")).toBeInTheDocument();
  expect(screen.getByText("192.168.1.29:1234")).toBeInTheDocument();
});

test("desktop workbench keeps chat session actions visible in the embedded chat pane", async () => {
  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  expect(await screen.findByRole("button", { name: "系统功能" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重置会话" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "终止任务" })).toBeInTheDocument();
});

test("desktop workbench resolves a single definition target and opens that file", async () => {
  const client = new MockWebBotClient();
  const resolveDefinition = vi.spyOn(client, "resolveWorkspaceDefinition").mockResolvedValue({
    items: [
      {
        path: "src/service.py",
        line: 12,
        matchKind: "workspace_search",
        confidence: 0.78,
      },
    ],
  });

  const readFileFull = vi.spyOn(client, "readFileFull").mockImplementation(async (_botAlias, path) => ({
    content: path === "app.py"
      ? "from service import run\nrun()\n"
      : "def run():\n    return 1\n",
    mode: "cat",
    fileSizeBytes: 64,
    isFullContent: true,
    lastModifiedNs: "1",
  }));

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => {
    if (path === "/workspace/src") {
      return {
        workingDir: "/workspace/src",
        entries: [{ name: "service.py", isDir: false, size: 64, updatedAt: "2026-04-22T10:00:00Z" }],
      };
    }
    return {
      workingDir: "/workspace",
      entries: [
        { name: "app.py", isDir: false, size: 64, updatedAt: "2026-04-22T10:00:00Z" },
        { name: "src", isDir: true, updatedAt: "2026-04-22T10:00:00Z" },
      ],
    };
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await userEvent.click(await screen.findByRole("button", { name: "打开 app.py" }));

  const editor = await screen.findByLabelText("文件内容");
  (editor as HTMLTextAreaElement).setSelectionRange(25, 25);
  fireEvent.click(editor, { button: 0, ctrlKey: true });

  await waitFor(() => {
    expect(resolveDefinition).toHaveBeenCalledWith("main", {
      path: "app.py",
      line: 2,
      column: 2,
      symbol: "run",
    });
  });
  await waitFor(() => {
    expect(readFileFull).toHaveBeenCalledWith("main", "src/service.py");
  });
  expect(await screen.findByRole("tab", { name: "service.py" })).toHaveAttribute("aria-selected", "true");
});

test("desktop workbench shows a picker when multiple definition targets are returned", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "resolveWorkspaceDefinition").mockResolvedValue({
    items: [
      {
        path: "src/service.py",
        line: 12,
        matchKind: "workspace_search",
        confidence: 0.78,
      },
      {
        path: "src/helpers.py",
        line: 4,
        matchKind: "workspace_search",
        confidence: 0.52,
      },
    ],
  });

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "app.py", isDir: false, size: 64, updatedAt: "2026-04-22T10:00:00Z" }],
  });
  vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "from service import run\nrun()\n",
    mode: "cat",
    fileSizeBytes: 64,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await userEvent.click(await screen.findByRole("button", { name: "打开 app.py" }));

  const editor = await screen.findByLabelText("文件内容");
  (editor as HTMLTextAreaElement).setSelectionRange(25, 25);
  fireEvent.click(editor, { button: 0, ctrlKey: true });

  expect(await screen.findByTestId("desktop-definition-picker")).toBeInTheDocument();
  expect(screen.getByText("src/service.py")).toBeInTheDocument();
  expect(screen.getByText("src/helpers.py")).toBeInTheDocument();
});

test("focused panes maximize into the available workbench area", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" }],
  });
  vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "README",
    mode: "cat",
    fileSizeBytes: 128,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  const columns = screen.getByTestId("desktop-workbench-columns");
  const centerRows = screen.getByTestId("desktop-workbench-center-rows");

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));
  await user.click(await screen.findByRole("button", { name: "聚焦编辑器" }));

  expect(screen.getByTestId("desktop-workbench-root")).toHaveAttribute("data-focused-pane", "editor");
  expect(columns).toHaveStyle({
    gridTemplateColumns: "0px 0px minmax(0, 1fr) 0px 0px",
  });
  expect(centerRows).toHaveStyle({
    gridTemplateRows: "minmax(0, 1fr) 0px 0px",
  });

  await user.click(screen.getByRole("button", { name: "退出聚焦编辑器" }));

  expect(screen.getByTestId("desktop-workbench-root")).toHaveAttribute("data-focused-pane", "none");
  expect(columns).toHaveStyle({
    gridTemplateColumns: "320px 8px minmax(0, 1fr) 8px 384px",
  });
  expect(centerRows).toHaveStyle({
    gridTemplateRows: "420px 8px minmax(160px, 1fr)",
  });
});

test("desktop workbench restores persisted pane sizes from storage", () => {
  localStorage.setItem(
    "web-workbench-pane-state",
    JSON.stringify({
      sidebarCollapsed: false,
      sidebarView: "files",
      sidebarWidthPx: 360,
      chatWidthPx: 420,
      editorHeightPx: 460,
    }),
  );

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
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
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
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
  expect(localStorage.getItem("web-workbench-pane-state")).toContain("\"sidebarWidthPx\":380");
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
      sidebarCollapsed: false,
      sidebarView: "files",
      sidebarWidthPx: 900,
      chatWidthPx: 700,
      editorHeightPx: 80,
    }),
  );

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={new MockWebBotClient()}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await waitFor(() => {
    expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
      gridTemplateColumns: "440px 8px minmax(0, 1fr) 8px 260px",
    });
  });
  expect(screen.getByTestId("desktop-workbench-center-rows")).toHaveStyle({
    gridTemplateRows: "220px 8px minmax(160px, 1fr)",
  });

  await user.click(screen.getByRole("button", { name: "折叠侧边栏" }));
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "48px 8px minmax(0, 1fr) 8px 260px",
  });

  await user.click(screen.getByRole("button", { name: "展开侧边栏" }));
  expect(screen.getByTestId("desktop-workbench-columns")).toHaveStyle({
    gridTemplateColumns: "440px 8px minmax(0, 1fr) 8px 260px",
  });

  expect(screen.getByTestId("desktop-pane-files")).not.toHaveClass("rounded-2xl");
});

test("desktop preview dialog defaults to a page-sized maximized window", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: 1600,
  });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    writable: true,
    value: 1200,
  });

  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function () {
    const testId = (this as HTMLElement).getAttribute("data-testid");
    if (testId === "desktop-workbench-columns") {
      return {
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1400,
        bottom: 820,
        width: 1400,
        height: 820,
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
        right: 900,
        bottom: 620,
        width: 900,
        height: 620,
        toJSON() {
          return {};
        },
      };
    }
    if (testId === "desktop-pane-editor") {
      return {
        x: 240,
        y: 170,
        top: 170,
        left: 240,
        right: 1060,
        bottom: 710,
        width: 820,
        height: 540,
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

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [
      { name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" },
    ],
  });
  vi.spyOn(client, "readFile").mockResolvedValue({
    content: "preview content",
    mode: "head",
    fileSizeBytes: 128,
    isFullContent: false,
    lastModifiedNs: "1",
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "预览 README.md" }));

  const previewWindow = await screen.findByTestId("desktop-workbench-preview-window");
  expect(previewWindow).toHaveStyle({
    left: "12px",
    top: "12px",
    width: "1576px",
    height: "1176px",
  });

  const dragHandle = screen.getByTestId("desktop-preview-drag-handle");
  fireEvent.pointerDown(dragHandle, { pointerId: 1, button: 0, clientX: 320, clientY: 220 });
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 380, clientY: 280 });
  fireEvent.pointerUp(window, { pointerId: 1, clientX: 380, clientY: 280 });

  expect(previewWindow).toHaveStyle({
    left: "12px",
    top: "12px",
  });
});

test("desktop file clicks open tabs and sync rename and delete actions", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let entries = [
    { name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" },
  ];

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => ({
    workingDir: "/workspace",
    entries: !path || path === "/workspace" ? entries : [],
  }));
  vi.spyOn(client, "readFileFull").mockImplementation(async (_botAlias, filename) => ({
    content: `FULL:${filename}`,
    mode: "cat",
    fileSizeBytes: 128,
    isFullContent: true,
    lastModifiedNs: "1",
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
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
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

test("desktop file tree loads file content on the first click", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockImplementation(async (_botAlias, path) => ({
    workingDir: "/workspace",
    entries: !path || path === "/workspace"
      ? [{ name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" }]
      : [],
  }));
  vi.spyOn(client, "readFileFull").mockResolvedValue({
    content: "FIRST_CLICK_CONTENT",
    mode: "cat",
    fileSizeBytes: 128,
    isFullContent: true,
    lastModifiedNs: "1",
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));

  await waitFor(() => {
    expect(screen.getByText("FIRST_CLICK_CONTENT")).toBeInTheDocument();
  });
  expect(client.readFileFull).toHaveBeenCalledTimes(1);
});
