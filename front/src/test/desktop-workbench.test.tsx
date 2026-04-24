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
      sessionCapabilities={["view_plugins"]}
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

  await user.click(screen.getByRole("button", { name: "Git" }));
  expect(await screen.findByText("当前分支")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "调试" }));
  expect(await screen.findByTestId("debug-pane")).toBeInTheDocument();
  expect(screen.getByText("(gdb) Remote Debug")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开远端参数" }));
  expect(screen.getByLabelText("准备命令")).toHaveValue(".\\debug.bat");
  expect(screen.getByRole("toolbar", { name: "调试控制" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "启动调试" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "设置" }));
  expect(await screen.findByLabelText("工作目录")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "插件" }));
  expect(await screen.findByRole("button", { name: "刷新" })).toBeInTheDocument();
  expect(screen.getByText("Vivado Waveform")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "文件" }));
  expect(await screen.findByTestId("desktop-file-tree-scroll")).toBeInTheDocument();
});

test("embedded git opens changed file diffs as read-only editor tabs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const getGitDiff = vi.spyOn(client, "getGitDiff").mockResolvedValue({
    path: "bot/web/server.py",
    staged: true,
    diff: "diff --git a/bot/web/server.py b/bot/web/server.py\n@@ -1 +1 @@\n-old\n+new",
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

  await user.click(screen.getByRole("button", { name: "Git" }));
  await user.click(await screen.findByLabelText("在编辑器打开 bot/web/server.py"));

  expect(getGitDiff).toHaveBeenCalledWith("main", "bot/web/server.py", true);
  expect(await screen.findByRole("tab", { name: "server.py.diff" })).toBeInTheDocument();
  expect(screen.getByTestId("desktop-git-diff-viewer")).toHaveTextContent("+new");
  expect(screen.getByText("+new").closest('[data-diff-kind="add"]')).toHaveClass("text-emerald-700");
  expect(screen.getByText("-old").closest('[data-diff-kind="delete"]')).toHaveClass("text-red-700");
  expect(screen.queryByLabelText("文件内容")).not.toBeInTheDocument();
});

test("desktop workbench opens .vcd files as plugin waveform tabs", async () => {
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

  await user.click(await screen.findByRole("button", { name: "展开 waves" }));
  await user.click(await screen.findByRole("button", { name: "打开 waves/simple_counter.vcd" }));

  expect(await screen.findByRole("tab", { name: "simple_counter.vcd" })).toBeInTheDocument();
  expect(screen.getByTestId("desktop-plugin-view")).toBeInTheDocument();
  expect(screen.getByText("tb.clk")).toBeInTheDocument();
});

test("desktop workbench opens .rpt files as table plugin tabs and downloads artifacts", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const downloadArtifact = vi.spyOn(client, "downloadPluginArtifact").mockResolvedValue();

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

  await user.click(await screen.findByRole("button", { name: "展开 reports" }));
  await user.click(await screen.findByRole("button", { name: "打开 reports/timing.rpt" }));

  expect(await screen.findByRole("tab", { name: "timing.rpt" })).toBeInTheDocument();
  expect(screen.getByText("Endpoint")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "导出 CSV" }));
  await waitFor(() => {
    expect(downloadArtifact).toHaveBeenCalledWith("main", expect.stringMatching(/^artifact-/), "timing.csv");
  });
});

test("desktop workbench opens .hier files as tree plugin tabs and handles open-file effects", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFileFull = vi.spyOn(client, "readFileFull");

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

  await user.click(await screen.findByRole("button", { name: "展开 reports" }));
  await user.click(await screen.findByRole("button", { name: "打开 reports/design.hier" }));

  expect(await screen.findByRole("tab", { name: "design.hier" })).toBeInTheDocument();
  expect(screen.getByText("top")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开源码" }));
  await waitFor(() => {
    expect(readFileFull).toHaveBeenCalledWith("main", "src/index.ts");
  });
  expect(await screen.findByRole("tab", { name: "index.ts" })).toBeInTheDocument();
});

test("desktop plugin catalog actions can open another plugin view", async () => {
  const user = userEvent.setup();

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={new MockWebBotClient()}
      sessionCapabilities={["view_plugins"]}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(screen.getByRole("button", { name: "插件" }));
  await user.click(await screen.findByRole("button", { name: "展开 RTL Hierarchy" }));
  await user.click(await screen.findByRole("button", { name: "打开 Timing" }));

  expect(await screen.findByRole("tab", { name: "timing.rpt" })).toBeInTheDocument();
  expect(screen.getByText("Endpoint")).toBeInTheDocument();
});

test("desktop workbench opens repo outline from plugin catalog CTA", async () => {
  const user = userEvent.setup();

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={new MockWebBotClient()}
      sessionCapabilities={["view_plugins", "read_file_content"]}
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(screen.getByRole("button", { name: "插件" }));
  await user.click(await screen.findByRole("button", { name: "展开 Repo Outline" }));
  await user.click(await screen.findByRole("button", { name: "选择文件夹大纲" }));
  await user.click(await screen.findByRole("button", { name: "使用当前目录" }));

  expect(await screen.findByRole("tab", { name: "文件夹大纲" })).toBeInTheDocument();
  expect(screen.getByText("bot")).toBeInTheDocument();
});

test("desktop workbench creates a loading plugin tab before the waveform session resolves", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let resolveOpen: ((value: Awaited<ReturnType<typeof client.openPluginView>>) => void) | null = null;
  vi.spyOn(client, "openPluginView").mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveOpen = resolve;
      }),
  );

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

  await user.click(await screen.findByRole("button", { name: "展开 waves" }));
  await user.click(await screen.findByRole("button", { name: "打开 waves/simple_counter.vcd" }));

  expect(await screen.findByRole("tab", { name: "simple_counter.vcd" })).toBeInTheDocument();
  expect(screen.getByText("正在加载插件视图")).toBeInTheDocument();

  resolveOpen?.({
    pluginId: "vivado-waveform",
    viewId: "waveform",
    title: "simple_counter.vcd",
    renderer: "waveform",
    mode: "session",
    sessionId: "session-1",
    summary: {
      path: "waves/simple_counter.vcd",
      timescale: "1ns",
      startTime: 0,
      endTime: 120,
      display: {
        defaultZoom: 1,
        zoomLevels: [1, 2],
        showTimeAxis: true,
        busStyle: "cross",
        labelWidth: 220,
        minWaveWidth: 840,
        pixelsPerTime: 18,
        axisHeight: 42,
        trackHeight: 64,
      },
      signals: [
        { signalId: "tb.clk", label: "tb.clk", width: 1, kind: "scalar" },
      ],
      defaultSignalIds: ["tb.clk"],
    },
    initialWindow: {
      startTime: 0,
      endTime: 120,
      tracks: [
        {
          signalId: "tb.clk",
          label: "tb.clk",
          width: 1,
          segments: [
            { start: 0, end: 60, value: "0" },
            { start: 60, end: 120, value: "1" },
          ],
        },
      ],
    },
  });

  expect(await screen.findByTestId("desktop-plugin-view")).toBeInTheDocument();
  expect(screen.getByText("tb.clk")).toBeInTheDocument();
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

test("desktop chat file links reuse the workbench preview window", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" }],
  });
  vi.spyOn(client, "listMessages").mockResolvedValue([{
    id: "assistant-1",
    role: "assistant",
    text: "[查看 README](C:/workspace/README.md)",
    createdAt: new Date().toISOString(),
    state: "done",
  }]);
  const readFile = vi.spyOn(client, "readFile").mockResolvedValue({
    content: "# README\n\n桌面预览",
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

  fireEvent.click(await screen.findByRole("link", { name: "查看 README" }));

  await waitFor(() => {
    expect(readFile).toHaveBeenCalled();
  });
  expect(readFile.mock.calls[0]?.[0]).toBe("main");
  expect(String(readFile.mock.calls[0]?.[1] || "")).toMatch(/(^|[\\/])README\.md$/);
  expect(await screen.findByTestId("desktop-workbench-preview-window")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "在编辑器中打开" })).toBeInTheDocument();
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

  fireEvent.contextMenu(screen.getByRole("button", { name: "打开 README.md" }));
  await user.click(await screen.findByRole("button", { name: "改名" }));
  await user.clear(screen.getByLabelText("文件名"));
  await user.type(screen.getByLabelText("文件名"), "README-renamed.md");
  await user.click(screen.getByRole("button", { name: "重命名" }));
  expect(await screen.findByRole("tab", { name: /README-renamed\.md/ })).toBeInTheDocument();

  fireEvent.contextMenu(screen.getByRole("button", { name: "打开 README-renamed.md" }));
  await user.click(await screen.findByRole("button", { name: "删除" }));
  await waitFor(() => {
    expect(screen.queryByRole("tab", { name: /README-renamed\.md/ })).not.toBeInTheDocument();
  });
});

test("desktop file tree shows diff for modified files and uses the tighter menu radius", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" }],
  });
  vi.spyOn(client, "getGitTreeStatus").mockResolvedValue({
    repoFound: true,
    workingDir: "/workspace",
    repoPath: "/workspace",
    items: {
      "README.md": "modified",
    },
  });
  const getGitDiff = vi.spyOn(client, "getGitDiff").mockResolvedValue({
    path: "README.md",
    staged: false,
    diff: "@@ -1 +1 @@\n-before\n+after",
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

  await screen.findByRole("button", { name: "打开 README.md" });

  fireEvent.contextMenu(screen.getByRole("button", { name: "打开 README.md" }));
  const menu = await screen.findByRole("menu", { name: "文件树菜单" });
  expect(menu).toHaveClass("rounded-md");
  await user.click(await screen.findByRole("button", { name: "Diff" }));

  expect(getGitDiff).toHaveBeenCalledWith("main", "README.md", false);
  expect(await screen.findByRole("tab", { name: "README.md.diff" })).toBeInTheDocument();
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

test("desktop workbench refreshes file tree git decorations after an embedded git commit", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  vi.spyOn(client, "getCurrentPath").mockResolvedValue("/workspace");
  vi.spyOn(client, "changeDirectory").mockResolvedValue("/workspace");
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "/workspace",
    entries: [{ name: "README.md", isDir: false, size: 128, updatedAt: "2026-04-17T09:00:00Z" }],
  });
  const getGitTreeStatus = vi.spyOn(client, "getGitTreeStatus").mockImplementation(async (botAlias) => {
    const overview = await MockWebBotClient.prototype.getGitOverview.call(client, botAlias);
    return {
      repoFound: overview.repoFound,
      workingDir: overview.workingDir,
      repoPath: overview.repoPath,
      items: overview.isClean ? {} : { "README.md": "modified" },
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

  const readmeButton = await screen.findByRole("button", { name: "打开 README.md" });
  await waitFor(() => {
    expect(readmeButton).toHaveClass("text-yellow-400", "font-semibold");
  });

  await user.click(screen.getByRole("button", { name: "Git" }));
  await user.click(await screen.findByRole("button", { name: "提交更改" }));
  await user.click(await screen.findByRole("button", { name: "文件" }));

  await waitFor(() => {
    const nextButton = screen.getByRole("button", { name: "打开 README.md" });
    expect(nextButton).toHaveClass("text-[var(--text)]", "font-semibold");
    expect(nextButton).not.toHaveClass("text-yellow-400");
  });
  expect(document.querySelector("[data-git-decoration]")).toBeNull();
  expect(getGitTreeStatus.mock.calls.length).toBeGreaterThanOrEqual(2);
});
