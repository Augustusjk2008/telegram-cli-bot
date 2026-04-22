import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { GitScreen } from "../screens/GitScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  BotOverview,
  BotSummary,
  ChatMessage,
  ChatTraceDetails,
  CliParamsPayload,
  DirectoryListing,
  GitActionResult,
  GitOverview,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function buildRepoOverview(overrides: Partial<GitOverview> = {}): GitOverview {
  return {
    repoFound: true,
    canInit: false,
    workingDir: "C:\\workspace\\repo",
    repoPath: "C:\\workspace\\repo",
    repoName: "repo",
    currentBranch: "main",
    isClean: false,
    aheadCount: 1,
    behindCount: 0,
    changedFiles: [
      {
        path: "tracked.txt",
        status: "M ",
        staged: true,
        unstaged: false,
        untracked: false,
      },
      {
        path: "draft.txt",
        status: "??",
        staged: false,
        unstaged: false,
        untracked: true,
      },
    ],
    recentCommits: [
      {
        hash: "abcdef012345",
        shortHash: "abcdef0",
        authorName: "Web Bot",
        authoredAt: "2026-04-09 21:00:00 +0800",
        subject: "feat: initial commit",
      },
    ],
    ...overrides,
  };
}

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    login: async (): Promise<SessionState> => ({
      currentBotAlias: "main",
      currentPath: "C:\\workspace\\repo",
      isLoggedIn: true,
      username: "demo",
      role: "member",
      capabilities: ["terminal_exec", "admin_ops"],
    }),
    listBots: async (): Promise<BotSummary[]> => [],
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\repo",
    }),
    listMessages: async (): Promise<ChatMessage[]> => [],
    getMessageTrace: async (): Promise<ChatTraceDetails> => ({
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    }),
    sendMessage: async (): Promise<ChatMessage> => ({
      id: "assistant-1",
      role: "assistant",
      text: "ok",
      createdAt: new Date().toISOString(),
      state: "done",
    }),
    getCurrentPath: async () => "C:\\workspace\\repo",
    listFiles: async (): Promise<DirectoryListing> => ({
      workingDir: "C:\\workspace\\repo",
      entries: [],
    }),
    changeDirectory: async () => "C:\\workspace\\repo",
    createDirectory: async () => undefined,
    deletePath: async () => undefined,
    readFile: async () => ({
      content: "",
      mode: "head" as const,
      fileSizeBytes: 0,
      isFullContent: true,
    }),
    readFileFull: async () => ({
      content: "",
      mode: "cat" as const,
      fileSizeBytes: 0,
      isFullContent: true,
    }),
    uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => "已发送终止任务请求",
    restartService: async () => undefined,
    getGitProxySettings: async () => ({ port: "" }),
    updateGitProxySettings: async () => ({ port: "" }),
    updateBotWorkdir: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\repo",
      lastActiveText: "运行中",
    }),
    getCliParams: async (): Promise<CliParamsPayload> => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    updateCliParam: async (): Promise<CliParamsPayload> => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    resetCliParams: async (): Promise<CliParamsPayload> => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    getTunnelStatus: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    startTunnel: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    stopTunnel: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    restartTunnel: async (): Promise<TunnelSnapshot> => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    getGitOverview: async (): Promise<GitOverview> => buildRepoOverview(),
    initGitRepository: async (): Promise<GitOverview> => buildRepoOverview(),
    getGitDiff: async () => ({
      path: "tracked.txt",
      staged: false,
      diff: "@@ -1 +1 @@\n-before\n+after",
    }),
    stageGitPaths: async (): Promise<GitActionResult> => ({
      message: "已暂存",
      overview: buildRepoOverview(),
    }),
    unstageGitPaths: async (): Promise<GitActionResult> => ({
      message: "已取消暂存",
      overview: buildRepoOverview(),
    }),
    commitGitChanges: async (): Promise<GitActionResult> => ({
      message: "已提交",
      overview: buildRepoOverview(),
    }),
    fetchGitRemote: async (): Promise<GitActionResult> => ({
      message: "已抓取",
      overview: buildRepoOverview(),
    }),
    pullGitRemote: async (): Promise<GitActionResult> => ({
      message: "已拉取",
      overview: buildRepoOverview(),
    }),
    pushGitRemote: async (): Promise<GitActionResult> => ({
      message: "已推送",
      overview: buildRepoOverview(),
    }),
    stashGitChanges: async (): Promise<GitActionResult> => ({
      message: "已暂存工作区",
      overview: buildRepoOverview(),
    }),
    popGitStash: async (): Promise<GitActionResult> => ({
      message: "已恢复暂存",
      overview: buildRepoOverview(),
    }),
    listSystemScripts: async (): Promise<SystemScript[]> => [],
    runSystemScript: async (): Promise<SystemScriptResult> => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
    runSystemScriptStream: async (): Promise<SystemScriptResult> => ({
      scriptName: "demo",
      success: true,
      output: "ok",
    }),
    ...overrides,
  });
}

test("renders git repo summary and changed files", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  expect(await screen.findByText("repo")).toBeInTheDocument();
  expect(screen.getByText("当前分支")).toBeInTheDocument();
  expect(screen.getByText("tracked.txt")).toBeInTheDocument();
  expect(screen.getByText("feat: initial commit")).toBeInTheDocument();
});

test("renders full-width desktop IDE git layout regions without nested vertical scroll", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  const shell = await screen.findByTestId("git-desktop-shell");
  expect(shell).toHaveClass("space-y-3");
  expect(shell).not.toHaveClass("md:grid");
  const changesPanel = screen.getByTestId("git-changes-panel");
  const changesContent = screen.getByTestId("git-changes-content");
  expect(changesPanel).not.toHaveClass("overflow-hidden");
  expect(changesContent).not.toHaveClass("max-h-[72vh]", "overflow-y-auto");
  expect(screen.queryByTestId("git-diff-panel")).not.toBeInTheDocument();
  expect(screen.getByTestId("git-commit-panel")).toBeInTheDocument();
});

test("collapses changes and recent commits", async () => {
  const user = userEvent.setup();
  render(<GitScreen botAlias="main" client={createClient()} />);

  expect(await screen.findByText("tracked.txt")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "收起变更" }));
  expect(screen.queryByText("tracked.txt")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开变更" }));
  expect(await screen.findByText("tracked.txt")).toBeInTheDocument();

  expect(screen.getByText("feat: initial commit")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "收起最近提交" }));
  expect(screen.queryByText("feat: initial commit")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开最近提交" }));
  expect(screen.getByText("feat: initial commit")).toBeInTheDocument();
});

test("embedded git omits the page header chrome", async () => {
  render(<GitScreen botAlias="main" client={createClient()} embedded />);

  expect(await screen.findByText("当前分支")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Git" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "刷新" })).not.toBeInTheDocument();
});

test("shows init action when current directory is not a git repo", async () => {
  const user = userEvent.setup();
  const initSpy = async (): Promise<GitOverview> => buildRepoOverview();
  const client = createClient({
    getGitOverview: async (): Promise<GitOverview> => ({
      repoFound: false,
      canInit: true,
      workingDir: "C:\\workspace\\plain",
      repoPath: "",
      repoName: "",
      currentBranch: "",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    }),
    initGitRepository: initSpy,
  });

  render(<GitScreen botAlias="main" client={client} />);

  expect(await screen.findByText("当前目录不在 Git 仓库中")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "初始化 Git 仓库" }));
  expect(await screen.findByText("当前分支")).toBeInTheDocument();
});

test("stages all unstaged and untracked files from the commit panel", async () => {
  const user = userEvent.setup();
  const stageSpy = vi.fn(async () => ({
    message: "已暂存全部改动",
    overview: buildRepoOverview({
      changedFiles: [
        {
          path: "tracked.txt",
          status: "M ",
          staged: true,
          unstaged: false,
          untracked: false,
        },
        {
          path: "notes.md",
          status: "M ",
          staged: true,
          unstaged: false,
          untracked: false,
        },
        {
          path: "draft.txt",
          status: "A ",
          staged: true,
          unstaged: false,
          untracked: false,
        },
      ],
    }),
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        getGitOverview: async (): Promise<GitOverview> => buildRepoOverview({
          changedFiles: [
            {
              path: "tracked.txt",
              status: "M ",
              staged: true,
              unstaged: false,
              untracked: false,
            },
            {
              path: "notes.md",
              status: " M",
              staged: false,
              unstaged: true,
              untracked: false,
            },
            {
              path: "draft.txt",
              status: "??",
              staged: false,
              unstaged: false,
              untracked: true,
            },
          ],
        }),
        stageGitPaths: stageSpy,
      })}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "暂存全部" }));

  expect(stageSpy).toHaveBeenCalledWith("main", ["notes.md", "draft.txt"]);
  expect(await screen.findByText("已暂存全部改动")).toBeInTheDocument();
});

test("disables the stage-all button when there are no unstaged or untracked files", async () => {
  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        getGitOverview: async (): Promise<GitOverview> => buildRepoOverview({
          changedFiles: [
            {
              path: "tracked.txt",
              status: "M ",
              staged: true,
              unstaged: false,
              untracked: false,
            },
          ],
        }),
      })}
    />,
  );

  expect(await screen.findByRole("button", { name: "暂存全部" })).toBeDisabled();
});

test("renders compact icon actions in changed file rows", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  const row = await screen.findByTestId("git-change-row-tracked.txt");
  expect(within(row).getByText("tracked.txt")).toBeInTheDocument();
  expect(within(row).getByLabelText("取消暂存 tracked.txt")).toBeInTheDocument();
  expect(within(row).getByLabelText("在编辑器打开 tracked.txt")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "查看 Diff" })).not.toBeInTheDocument();
});

test("opens changed file diff in the editor instead of rendering diff in git", async () => {
  const user = userEvent.setup();
  const openDiff = vi.fn(async () => undefined);

  render(
    <GitScreen
      botAlias="main"
      client={createClient()}
      onOpenDiff={openDiff}
    />,
  );

  await user.click(await screen.findByLabelText("在编辑器打开 tracked.txt"));

  expect(openDiff).toHaveBeenCalledWith("tracked.txt", true);
  expect(screen.queryByTestId("git-diff-panel")).not.toBeInTheDocument();
  expect(screen.queryByTestId("git-inline-diff")).not.toBeInTheDocument();
});
