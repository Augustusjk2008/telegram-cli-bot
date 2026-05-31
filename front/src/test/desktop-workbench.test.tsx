import type { ReactElement } from "react";
import { fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { DebugProfile } from "../services/types";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DebugPane } from "../workbench/DebugPane";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import { buildWorkbenchSessionStorageKey } from "../workbench/workbenchSession";

function render(ui: ReactElement) {
  const client = ((ui.props as { client?: MockWebBotClient }).client) || new MockWebBotClient();
  return rtlRender(
    <PersistentTerminalProvider client={client}>
      {ui}
    </PersistentTerminalProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function expectDesktopTreeRowSelected(path: string, selected = true) {
  const row = document.querySelector(`[data-tree-path="${path}"]`);
  expect(row).not.toBeNull();
  expect(row).toHaveAttribute("data-selected", selected ? "true" : "false");
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

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

  await user.click(screen.getByRole("button", { name: "竖屏版" }));
  expect(onViewModeChange).toHaveBeenCalledWith("mobile");
});


test("desktop structureOnly file click never opens editor or reads full content", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFile = vi.spyOn(client, "readFile");
  const readFileFull = vi.spyOn(client, "readFileFull");

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      structureOnly
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "打开 README.md" }));

  await waitFor(() => {
    expectDesktopTreeRowSelected("README.md");
  });
  expect(readFile).not.toHaveBeenCalled();
  expect(readFileFull).not.toHaveBeenCalled();
  expect(screen.queryByTestId("desktop-pane-editor")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: /README\.md/ })).not.toBeInTheDocument();
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














test("desktop assistant bot with admin ops opens assistant ops from the activity rail", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "assistant1",
    botMode: "assistant",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\assistant1",
    avatarName: "avatar_01.png",
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="assistant1"
      botAvatarName="avatar_01.png"
      userAvatarName="avatar_01.png"
      client={client}
      sessionCapabilities={["admin_ops", "view_plugins"]}
      canViewAssistantOps
      themeName="deep-space"
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  const rail = await screen.findByTestId("desktop-workbench-activity-rail");
  const labels = within(rail)
    .getAllByRole("button")
    .map((button) => button.getAttribute("aria-label"));
  expect(labels).toEqual(["折叠侧边栏", "文件", "搜索", "大纲", "指南", "调试", "Git", "运维", "插件", "设置"]);

  await user.click(screen.getByRole("button", { name: "运维" }));

  expect(await screen.findByRole("heading", { name: "Assistant 运维台" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Proposal" })).toBeInTheDocument();
  expect(screen.getByTestId("desktop-pane-editor")).toHaveTextContent("Assistant 运维台");
  expect(screen.getByRole("button", { name: "运维" })).toHaveAttribute("aria-pressed", "true");

  await user.click(screen.getByRole("button", { name: "文件" }));
  expect(screen.queryByRole("heading", { name: "Assistant 运维台" })).not.toBeInTheDocument();
  expect(await screen.findByTestId("desktop-file-tree-scroll")).toBeInTheDocument();
});

test("file tree applies git status color and font weight to names", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "getGitTreeStatus").mockResolvedValue({
    repoFound: true,
    workingDir: "C:\\workspace",
    repoPath: "C:\\workspace",
    items: {
      "README.md": "modified",
      "package.json": "added",
      "docs": "ignored",
    },
  });

  render(
    <DesktopWorkbench
      authToken="123"
      botAlias="main"
      client={client}
      viewMode="desktop"
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
    />,
  );

  const modifiedButton = await screen.findByRole("button", { name: "打开 README.md" });
  const addedButton = await screen.findByRole("button", { name: "打开 package.json" });
  const ignoredButton = await screen.findByRole("button", { name: "展开 docs" });

  expect(within(modifiedButton).getByText("README.md")).toHaveClass("text-yellow-400", "font-semibold");
  expect(within(addedButton).getByText("package.json")).toHaveClass("text-emerald-500", "font-semibold");
  expect(within(ignoredButton).getByText("docs")).toHaveClass("text-[var(--muted)]", "font-semibold");
});

test("debug pane tolerates missing launch schema fields", () => {
  const profile = {
    specVersion: 1,
    providerId: "custom",
    providerLabel: "Custom Debug",
    configName: "custom",
    target: {},
    capabilities: {},
    launchSchema: {} as DebugProfile["launchSchema"],
    launchDefaults: {},
    program: "",
    cwd: "",
    miDebuggerPath: "",
    prepareCommand: "",
    stopAtEntry: true,
    setupCommands: [],
    remoteHost: "",
    remoteUser: "",
    remoteDir: "",
    remotePort: 0,
  } satisfies DebugProfile;

  expect(() => render(
    <DebugPane
      profile={profile}
      state={{
        phase: "idle",
        message: "",
        breakpoints: [],
        frames: [],
        scopes: [],
        variables: {},
        currentFrameId: "",
      }}
      prepareLogs={[]}
      launchForm={{}}
      onLaunchFormChange={() => {}}
      onLaunch={() => {}}
      onContinue={() => {}}
      onPause={() => {}}
      onNext={() => {}}
      onStepIn={() => {}}
      onStepOut={() => {}}
      onStop={() => {}}
      onSelectFrame={() => {}}
      onRequestVariables={() => {}}
    />,
  )).not.toThrow();
  expect(screen.getByTestId("debug-pane")).toHaveTextContent("Custom Debug");
});

test("desktop search inputs show a focus-within ring around icon and input", async () => {
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

  await user.click(screen.getByRole("button", { name: "搜索" }));
  expect(await screen.findByTestId("workspace-search-field")).toHaveClass(
    "focus-within:border-[var(--accent-outline)]",
    "focus-within:outline",
    "focus-within:outline-[var(--accent-outline)]",
  );

  fireEvent.keyDown(window, { key: "p", ctrlKey: true });
  expect(await screen.findByTestId("quick-open-search-field")).toHaveClass(
    "focus-within:border-[var(--accent-outline)]",
    "focus-within:outline",
    "focus-within:outline-[var(--accent-outline)]",
  );
});


