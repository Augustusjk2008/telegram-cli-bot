import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
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
  GitBranchList,
  GitBranchResetResult,
  GitCommitGraphOptions,
  GitCommitGraphPayload,
  GitCommitMessageCliConfig,
  GitCommitMessageGenerateResult,
  GitIdentityConfig,
  GitOverview,
  GitResetMode,
  GitSmartCommitJob,
  SessionState,
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
        message: "feat: initial commit\n\nadd first repo snapshot",
      },
      {
        hash: "123456789abc",
        shortHash: "1234567",
        authorName: "Web Bot",
        authoredAt: "2026-04-08 21:00:00 +0800",
        subject: "docs: older commit",
        message: "docs: older commit",
      },
    ],
    ...overrides,
  };
}

function buildSmartCommitJob(overrides: Partial<GitSmartCommitJob> = {}): GitSmartCommitJob {
  return {
    jobId: "job-1",
    alias: "main",
    userId: 1001,
    status: "running",
    phase: "generating",
    message: "",
    error: "",
    overview: null,
    ...overrides,
  };
}

function buildCommitGraph(overrides: Partial<GitCommitGraphPayload> = {}): GitCommitGraphPayload {
  return {
    repoFound: true,
    scope: "all",
    nodes: [
      {
        hash: "abcdef012345",
        shortHash: "abcdef0",
        parents: ["123456789abc"],
        authorName: "Web Bot",
        authoredAt: "2026-04-09T21:00:00+08:00",
        subject: "feat: initial commit",
        refs: [
          { name: "HEAD", kind: "head", current: true },
          { name: "main", kind: "local_branch", current: true },
          { name: "v1.0.0", kind: "tag", current: false },
        ],
        graph: { column: 0, width: 2, edges: [{ from: 0, to: 0 }] },
        canReset: true,
      },
      {
        hash: "123456789abc",
        shortHash: "1234567",
        parents: [],
        authorName: "Web Bot",
        authoredAt: "2026-04-08T21:00:00+08:00",
        subject: "docs: older commit",
        refs: [{ name: "origin/main", kind: "remote_branch", current: false }],
        graph: { column: 1, width: 2, edges: [] },
        canReset: true,
      },
    ],
    hasMore: false,
    nextCursor: "",
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
    getGitProxySettings: async () => ({ address: "", port: "" }),
    updateGitProxySettings: async () => ({ address: "", port: "" }),
    getGitIdentityConfig: async (): Promise<GitIdentityConfig> => ({
      repoFound: true,
      repoPath: "C:\\workspace\\repo",
      global: { name: "Global User", email: "global@example.com" },
      local: { name: "", email: "" },
    }),
    updateGitIdentityConfig: async (_botAlias, input): Promise<GitIdentityConfig> => ({
      repoFound: true,
      repoPath: "C:\\workspace\\repo",
      global: input.scope === "global" ? { name: input.name, email: input.email } : { name: "Global User", email: "global@example.com" },
      local: input.scope === "local" ? { name: input.name, email: input.email } : { name: "", email: "" },
    }),
    getGitCommitMessageConfig: async (): Promise<GitCommitMessageCliConfig> => ({
      cliType: "codex",
      cliPath: "codex",
      params: {
        reasoning_effort: "high",
        extra_args: [],
      },
      defaults: {
        reasoning_effort: "medium",
        extra_args: [],
      },
      schema: {
        reasoning_effort: {
          type: "string",
          enum: ["high", "medium", "low"],
          description: "推理努力程度",
        },
        extra_args: {
          type: "string_list",
          description: "额外参数",
        },
      },
    }),
    updateGitCommitMessageConfig: async (_botAlias, input): Promise<GitCommitMessageCliConfig> => ({
      cliType: input.cliType || "codex",
      cliPath: input.cliPath || "codex",
      params: {
        reasoning_effort: "high",
        extra_args: [],
        ...(input.params || {}),
      },
      defaults: {
        reasoning_effort: "medium",
        extra_args: [],
      },
      schema: {
        reasoning_effort: {
          type: "string",
          enum: ["high", "medium", "low"],
          description: "推理努力程度",
        },
        extra_args: {
          type: "string_list",
          description: "额外参数",
        },
      },
    }),
    resetGitCommitMessageConfig: async (): Promise<GitCommitMessageCliConfig> => ({
      cliType: "codex",
      cliPath: "codex",
      params: {
        reasoning_effort: "medium",
        extra_args: [],
      },
      defaults: {
        reasoning_effort: "medium",
        extra_args: [],
      },
      schema: {
        reasoning_effort: {
          type: "string",
          enum: ["high", "medium", "low"],
          description: "推理努力程度",
        },
        extra_args: {
          type: "string_list",
          description: "额外参数",
        },
      },
    }),
    generateGitCommitMessage: async (): Promise<GitCommitMessageGenerateResult> => ({
      message: "feat(git): add generated commit message flow",
    }),
    startGitSmartCommit: async (): Promise<GitSmartCommitJob> => buildSmartCommitJob(),
    getActiveGitSmartCommit: async (): Promise<GitSmartCommitJob | null> => null,
    getGitSmartCommitJob: async (): Promise<GitSmartCommitJob> => buildSmartCommitJob(),
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
    getGitCommitGraph: async (_botAlias, options?: GitCommitGraphOptions): Promise<GitCommitGraphPayload> => buildCommitGraph({
      scope: options?.scope || "all",
    }),
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
    discardGitPaths: async (): Promise<GitActionResult> => ({
      message: "已丢弃所选文件改动",
      overview: buildRepoOverview({ changedFiles: [{ path: "draft.txt", status: "??", staged: false, unstaged: false, untracked: true }] }),
    }),
    discardAllGitChanges: async (): Promise<GitActionResult> => ({
      message: "已丢弃全部改动",
      overview: buildRepoOverview({ isClean: true, changedFiles: [] }),
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
    listGitBranches: async (): Promise<GitBranchList> => ({
      currentBranch: "main",
      branches: [
        {
          name: "main",
          current: true,
          upstream: "origin/main",
          shortHash: "abcdef0",
          subject: "feat: initial commit",
        },
      ],
    }),
    createGitBranch: async (_botAlias, name): Promise<GitBranchList> => ({
      currentBranch: "main",
      branches: [
        {
          name: "main",
          current: true,
          upstream: "origin/main",
          shortHash: "abcdef0",
          subject: "feat: initial commit",
        },
        {
          name,
          current: false,
          upstream: "",
          shortHash: "abcdef0",
          subject: "feat: initial commit",
        },
      ],
    }),
    switchGitBranch: async (_botAlias, name): Promise<GitBranchList> => ({
      currentBranch: name,
      branches: [
        {
          name,
          current: true,
          upstream: "",
          shortHash: "abcdef0",
          subject: "feat: initial commit",
        },
      ],
    }),
    resetGitBranch: async (_botAlias, commit): Promise<GitBranchResetResult> => ({
      message: "分支已重置",
      overview: buildRepoOverview({
        isClean: true,
        changedFiles: [],
        recentCommits: buildRepoOverview().recentCommits.filter((item) => item.hash === commit),
      }),
      branches: [
        {
          name: "main",
          current: true,
          upstream: "origin/main",
          shortHash: commit.slice(0, 7),
          subject: "docs: older commit",
        },
      ],
      currentBranch: "main",
      headCommit: commit,
    }),
    ...overrides,
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("renders git repo summary and changed files", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  expect(await screen.findByText("repo")).toBeInTheDocument();
  expect(screen.getAllByText("当前分支").length).toBeGreaterThan(0);
  expect(screen.getByText("tracked.txt")).toBeInTheDocument();
  expect(await screen.findByText(/abcdef0 - Web Bot/)).toBeInTheDocument();
  expect(screen.getAllByText("feat: initial commit").length).toBeGreaterThan(0);
});


test("renders commit graph rows, refs, and selected actions", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  const panel = await screen.findByTestId("git-version-tree-panel");

  expect(within(panel).getByText("提交图")).toBeInTheDocument();
  expect(await within(panel).findByTestId("git-commit-graph")).toBeInTheDocument();
  expect(within(panel).getAllByTestId(/^git-graph-row-/)).toHaveLength(2);
  expect(within(panel).getByTestId("git-graph-row-abcdef0")).toHaveAttribute("data-selected", "true");
  expect(within(panel).getByTestId("git-graph-row-1234567")).toHaveAttribute("data-selected", "false");
  expect(within(panel).getByTestId("git-graph-node-abcdef0")).toBeInTheDocument();
  expect(within(panel).getByTestId("git-graph-edge-abcdef0-0")).toBeInTheDocument();
  expect(within(panel).getByText(/abcdef0 - Web Bot/)).toBeInTheDocument();
  expect(within(panel).getAllByText("feat: initial commit").length).toBeGreaterThan(0);
  expect(within(panel).getByTestId("git-graph-ref-abcdef0-HEAD")).toBeInTheDocument();
  expect(within(panel).getByTestId("git-graph-ref-abcdef0-main")).toBeInTheDocument();
  expect(within(panel).getByTestId("git-graph-ref-abcdef0-v1.0.0")).toBeInTheDocument();
  expect(within(panel).getByTestId("git-version-tree-actions")).toBeInTheDocument();
  const graph = within(panel).getByTestId("git-commit-graph");
  expect(graph).toHaveClass("min-w-0");
  expect(graph).not.toHaveClass("min-w-[560px]");
});

test("commit graph keeps long subjects and branch refs inside row flow", async () => {
  const longSubject = "feat: keep an extremely long graph subject in one clipped line without overlapping next commit row";
  const longBranch = "feature/super-long-branch-name-that-should-wrap-or-shrink-within-the-row";
  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        getGitCommitGraph: async (): Promise<GitCommitGraphPayload> => buildCommitGraph({
          nodes: [
            {
              ...buildCommitGraph().nodes[0],
              subject: longSubject,
              refs: [
                { name: "HEAD", kind: "head", current: true },
                { name: longBranch, kind: "local_branch", current: true },
              ],
            },
            buildCommitGraph().nodes[1],
          ],
        }),
      })}
    />,
  );

  const row = await screen.findByTestId("git-graph-row-abcdef0");

  expect(within(row).getByTitle(longSubject)).toHaveClass("truncate");
  expect(within(row).getByTestId(`git-graph-ref-abcdef0-${longBranch}`)).toHaveClass("truncate");
  expect(row).toHaveClass("grid");
  expect(row).not.toHaveClass("absolute");
});

test("version tree scope switch reloads graph", async () => {
  const user = userEvent.setup();
  const getGitCommitGraph = vi.fn(async (_botAlias: string, options?: GitCommitGraphOptions): Promise<GitCommitGraphPayload> => buildCommitGraph({
    scope: options?.scope || "all",
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ getGitCommitGraph })}
    />,
  );

  await screen.findByTestId("git-version-tree-panel");
  await user.click(screen.getByRole("button", { name: "当前分支" }));

  expect(await screen.findByText(/abcdef0 - Web Bot/)).toBeInTheDocument();
  expect(getGitCommitGraph).toHaveBeenCalledWith("main", expect.objectContaining({ scope: "current", limit: 50 }));
});

test("version tree load more appends nodes", async () => {
  const user = userEvent.setup();
  const getGitCommitGraph = vi.fn(async (_botAlias: string, options?: GitCommitGraphOptions): Promise<GitCommitGraphPayload> => {
    if (options?.cursor === "page-2") {
      return buildCommitGraph({
        nodes: [
          {
            hash: "feedbeef0000",
            shortHash: "feedbee",
            parents: [],
            authorName: "Web Bot",
            authoredAt: "2026-04-07T21:00:00+08:00",
            subject: "chore: second page",
            refs: [],
            graph: { column: 0, width: 1, edges: [] },
          },
        ],
        hasMore: false,
        nextCursor: "",
      });
    }
    return buildCommitGraph({
      nodes: [buildCommitGraph().nodes[0]],
      hasMore: true,
      nextCursor: "page-2",
    });
  });

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ getGitCommitGraph })}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "加载更多" }));

  expect(await screen.findByText(/feedbee - Web Bot/)).toBeInTheDocument();
  expect(screen.getByText(/abcdef0 - Web Bot/)).toBeInTheDocument();
  expect(getGitCommitGraph).toHaveBeenCalledWith("main", expect.objectContaining({ cursor: "page-2" }));
});

test("version tree creates branch with selected node hash", async () => {
  const user = userEvent.setup();
  const createGitBranch = vi.fn(async (_botAlias: string, name: string): Promise<GitBranchList> => ({
    currentBranch: "main",
    branches: [
      {
        name,
        current: false,
        upstream: "",
        shortHash: "1234567",
        subject: "docs: older commit",
      },
    ],
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ createGitBranch })}
    />,
  );

  await user.click(await screen.findByText(/1234567 - Web Bot/));
  await user.type(screen.getByLabelText("从提交图新建分支名"), "feature/tree");
  await user.click(within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "新建分支" }));

  expect(createGitBranch).toHaveBeenCalledWith("main", "feature/tree", "123456789abc");
  expect(await screen.findByText("分支已从 1234567 创建")).toBeInTheDocument();
});

test("version tree resets with selected node hash and mode", async () => {
  const user = userEvent.setup();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  const resetGitBranch = vi.fn(async (_botAlias: string, commit: string, mode: GitResetMode): Promise<GitBranchResetResult> => ({
    message: "分支已重置",
    overview: buildRepoOverview({ isClean: true, changedFiles: [] }),
    branches: [
      {
        name: "main",
        current: true,
        upstream: "origin/main",
        shortHash: commit.slice(0, 7),
        subject: `reset ${mode}`,
      },
    ],
    currentBranch: "main",
    headCommit: commit,
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ resetGitBranch })}
    />,
  );

  await user.click(await screen.findByText(/1234567 - Web Bot/));
  await user.selectOptions(screen.getByLabelText("提交图重置模式"), "hard");
  await user.click(within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "重置到此提交" }));

  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("1234567"));
  expect(resetGitBranch).toHaveBeenCalledWith("main", "123456789abc", "hard");
  expect(await screen.findByText("分支已重置")).toBeInTheDocument();
});


test("creates branch from selected commit graph hash", async () => {
  const user = userEvent.setup();
  const createGitBranch = vi.fn(async (_botAlias: string, name: string): Promise<GitBranchList> => ({
    currentBranch: "main",
    branches: [
      {
        name,
        current: false,
        upstream: "",
        shortHash: "abcdef0",
        subject: "feat: initial commit",
      },
    ],
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ createGitBranch })}
    />,
  );

  await user.click(await screen.findByText(/abcdef0 - Web Bot/));
  await user.type(screen.getByLabelText("从提交图新建分支名"), "feature/from-commit");
  await user.click(within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "新建分支" }));

  expect(createGitBranch).toHaveBeenCalledWith("main", "feature/from-commit", "abcdef012345");
  expect(await screen.findByText("分支已从 abcdef0 创建")).toBeInTheDocument();
});


test("resets branch to selected commit graph hash after confirm", async () => {
  const user = userEvent.setup();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  const resetGitBranch = vi.fn(async (_botAlias: string, commit: string, mode: GitResetMode): Promise<GitBranchResetResult> => ({
    message: "分支已重置",
    overview: buildRepoOverview({
      currentBranch: "main",
      isClean: true,
      changedFiles: [],
      recentCommits: [
        {
          hash: commit,
          shortHash: commit.slice(0, 7),
          authorName: "Web Bot",
          authoredAt: "2026-04-09 21:00:00 +0800",
          subject: `reset ${mode}`,
          message: `reset ${mode}`,
        },
      ],
    }),
    branches: [
      {
        name: "main",
        current: true,
        upstream: "origin/main",
        shortHash: commit.slice(0, 7),
        subject: `reset ${mode}`,
      },
    ],
    currentBranch: "main",
    headCommit: commit,
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ resetGitBranch })}
    />,
  );

  await user.click(await screen.findByText(/abcdef0 - Web Bot/));
  await user.selectOptions(screen.getByLabelText("提交图重置模式"), "hard");
  await user.click(within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "重置到此提交" }));

  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("main"));
  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("abcdef0"));
  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("feat: initial commit"));
  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("hard"));
  expect(resetGitBranch).toHaveBeenCalledWith("main", "abcdef012345", "hard");
  expect(await screen.findByText("分支已重置")).toBeInTheDocument();
});


test("reset action disables commit operations while running", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  let resolveReset: ((value: GitBranchResetResult) => void) | null = null;
  const resetGitBranch = vi.fn((_botAlias: string, commit: string) => new Promise<GitBranchResetResult>((resolve) => {
    resolveReset = resolve;
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ resetGitBranch })}
    />,
  );

  await user.click(await screen.findByText(/abcdef0 - Web Bot/));
  const resetButton = within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "重置到此提交" });
  await user.type(screen.getByLabelText("从提交图新建分支名"), "feature/busy");
  const branchButton = within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "新建分支" });
  expect(branchButton).not.toBeDisabled();
  expect(await screen.findByTestId("git-version-tree-actions")).toBeInTheDocument();

  await user.click(resetButton);

  expect(resetButton).toBeDisabled();
  expect(branchButton).toBeDisabled();
  expect(screen.getByTestId("git-commit-graph")).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByLabelText("从提交图新建分支名")).toBeDisabled();
  expect(screen.getByLabelText("提交图重置模式")).toBeDisabled();
  expect(within(screen.getByTestId("git-version-tree-actions")).getByRole("button", { name: "重置到此提交" })).toBeDisabled();

  resolveReset?.({
    message: "分支已重置",
    overview: buildRepoOverview({ isClean: true, changedFiles: [] }),
    branches: [],
    currentBranch: "main",
    headCommit: "abcdef012345",
  });
  expect(await screen.findByText("分支已重置")).toBeInTheDocument();
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






test("git screen starts smart commit, polls phases, refreshes overview and clears textarea", async () => {
  const realSetTimeout = window.setTimeout.bind(window);
  vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler, timeout?: number, ...args: any[]) =>
    realSetTimeout(handler, timeout === 1000 ? 100 : timeout, ...args)) as typeof window.setTimeout);
  const generatedMessage = "feat(git): add generated commit message flow";
  const successOverview = buildRepoOverview({
    isClean: true,
    changedFiles: [],
    recentCommits: [
      {
        hash: "123456789abc",
        shortHash: "1234567",
        authorName: "Web Bot",
        authoredAt: "2026-05-21 23:17:00 +0800",
        subject: generatedMessage,
        message: generatedMessage,
      },
    ],
  });
  let overviewState = buildRepoOverview();
  let pollCount = 0;
  const getGitOverview = vi.fn(async (): Promise<GitOverview> => overviewState);
  const startGitSmartCommit = vi.fn(async (): Promise<GitSmartCommitJob> => buildSmartCommitJob());
  const getGitSmartCommitJob = vi.fn(async (): Promise<GitSmartCommitJob> => {
    pollCount += 1;
    if (pollCount === 1) {
      return buildSmartCommitJob({ phase: "generating", message: generatedMessage });
    }
    if (pollCount === 2) {
      return buildSmartCommitJob({ phase: "staging", message: generatedMessage });
    }
    if (pollCount === 3) {
      return buildSmartCommitJob({ phase: "committing", message: generatedMessage });
    }
    overviewState = successOverview;
    return buildSmartCommitJob({
      status: "succeeded",
      phase: "done",
      message: generatedMessage,
      overview: successOverview,
    });
  });

  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        getGitOverview,
        startGitSmartCommit,
        getGitSmartCommitJob,
      })}
    />,
  );

  await screen.findByTestId("git-commit-panel");
  const initialOverviewCalls = getGitOverview.mock.calls.length;
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("commit message"), "temporary");
  await user.click(screen.getByRole("button", { name: "智能提交" }));

  expect(startGitSmartCommit).toHaveBeenCalledWith("main");
  expect(within(screen.getByTestId("git-smart-commit-status")).getByText("生成说明...")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成 commit message" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "暂存全部" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "丢弃全部" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "提交更改" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "智能提交" })).toBeDisabled();
  expect(screen.getByLabelText("commit message")).toBeDisabled();

  expect(await within(await screen.findByTestId("git-smart-commit-status")).findByText("暂存中...")).toBeInTheDocument();
  expect(await within(await screen.findByTestId("git-smart-commit-status")).findByText("提交中...")).toBeInTheDocument();
  const smartStatus = await screen.findByTestId("git-smart-commit-status");
  expect(await within(smartStatus).findByText("智能提交完成 · 1234567")).toBeInTheDocument();
  expect(screen.getAllByText("智能提交完成 · 1234567").length).toBeGreaterThan(0);
  expect(screen.getByLabelText("commit message")).toHaveValue("");
  expect(getGitOverview.mock.calls.length).toBeGreaterThan(initialOverviewCalls);
  expect(getGitSmartCommitJob).toHaveBeenCalledTimes(4);
  expect(within(smartStatus).queryByText(generatedMessage)).not.toBeInTheDocument();
});






