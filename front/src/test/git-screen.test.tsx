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
  GitCommitMessageCliConfig,
  GitCommitMessageGenerateResult,
  GitIdentityConfig,
  GitOverview,
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
    ...overrides,
  });
}

test("renders git repo summary and changed files", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  expect(await screen.findByText("repo")).toBeInTheDocument();
  expect(screen.getByText("当前分支")).toBeInTheDocument();
  expect(screen.getByText("tracked.txt")).toBeInTheDocument();
  expect(screen.getByText("feat: initial commit")).toBeInTheDocument();
  expect(screen.getByText("feat: initial commit")).toHaveAttribute(
    "title",
    "feat: initial commit\n\nadd first repo snapshot",
  );
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

test("git screen saves global and local author identity", async () => {
  const user = userEvent.setup();
  const updateGitIdentityConfig = vi.fn(async (_botAlias, input) => ({
    repoFound: true,
    repoPath: "C:\\workspace\\repo",
    global: input.scope === "global" ? { name: input.name, email: input.email } : { name: "Global User", email: "global@example.com" },
    local: input.scope === "local" ? { name: input.name, email: input.email } : { name: "", email: "" },
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ updateGitIdentityConfig })}
    />,
  );

  await screen.findByTestId("git-identity-panel");
  const nameInput = screen.getByLabelText("Git 用户名");
  const emailInput = screen.getByLabelText("Git 邮箱");
  expect(nameInput).toHaveValue("Global User");
  expect(emailInput).toHaveValue("global@example.com");

  await user.clear(nameInput);
  await user.type(nameInput, "Local User");
  await user.clear(emailInput);
  await user.type(emailInput, "local@example.com");
  await user.click(screen.getByRole("button", { name: "当前仓库" }));
  expect(nameInput).toHaveValue("");

  await user.type(nameInput, "Local User");
  await user.type(emailInput, "local@example.com");
  await user.click(screen.getByRole("button", { name: "保存 Git 用户" }));

  expect(updateGitIdentityConfig).toHaveBeenCalledWith("main", {
    scope: "local",
    name: "Local User",
    email: "local@example.com",
  });
  expect(await screen.findByText("当前仓库 Git 用户已保存")).toBeInTheDocument();
});

test("git identity panel disables local scope outside a repository", async () => {
  render(
    <GitScreen
      botAlias="main"
      client={createClient({
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
        getGitIdentityConfig: async (): Promise<GitIdentityConfig> => ({
          repoFound: false,
          repoPath: "",
          global: { name: "", email: "" },
          local: { name: "", email: "" },
        }),
      })}
    />,
  );

  expect(await screen.findByRole("button", { name: "当前仓库" })).toBeDisabled();
  expect(screen.getByText("当前目录无仓库，仅可保存全局配置")).toBeInTheDocument();
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

test("discards a single changed file", async () => {
  const user = userEvent.setup();
  const discardSpy = vi.fn(async () => ({
    message: "已丢弃所选文件改动",
    overview: buildRepoOverview({
      changedFiles: [
        {
          path: "draft.txt",
          status: "??",
          staged: false,
          unstaged: false,
          untracked: true,
        },
      ],
    }),
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        discardGitPaths: discardSpy,
      })}
    />,
  );

  await user.click(await screen.findByLabelText("丢弃 tracked.txt"));

  expect(discardSpy).toHaveBeenCalledWith("main", ["tracked.txt"]);
  expect(await screen.findByText("已丢弃所选文件改动")).toBeInTheDocument();
});

test("discards all changes from the commit panel", async () => {
  const user = userEvent.setup();
  const discardAllSpy = vi.fn(async () => ({
    message: "已丢弃全部改动",
    overview: buildRepoOverview({
      isClean: true,
      changedFiles: [],
    }),
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        discardAllGitChanges: discardAllSpy,
      })}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "丢弃全部" }));

  expect(discardAllSpy).toHaveBeenCalledWith("main");
  expect(await screen.findByText("已丢弃全部改动")).toBeInTheDocument();
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

test("git screen creates and switches branches", async () => {
  const user = userEvent.setup();
  const listGitBranches = vi.fn(async () => ({
    currentBranch: "main",
    branches: [
      { name: "main", current: true, upstream: "origin/main", shortHash: "abc1234", subject: "init" },
      { name: "feature/existing", current: false, upstream: "", shortHash: "def5678", subject: "existing" },
    ],
  }));
  const createGitBranch = vi.fn(async () => ({
    currentBranch: "main",
    branches: [
      { name: "main", current: true, upstream: "origin/main", shortHash: "abc1234", subject: "init" },
      { name: "feature/new", current: false, upstream: "", shortHash: "abc1234", subject: "created" },
    ],
  }));
  const switchGitBranch = vi.fn(async () => ({
    currentBranch: "feature/new",
    branches: [
      { name: "main", current: false, upstream: "origin/main", shortHash: "abc1234", subject: "init" },
      { name: "feature/new", current: true, upstream: "", shortHash: "abc1234", subject: "created" },
    ],
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ listGitBranches, createGitBranch, switchGitBranch })}
    />,
  );

  expect((await screen.findAllByText("feature/existing")).length).toBeGreaterThan(0);
  await user.type(screen.getByLabelText("新建分支名"), "feature/new");
  await user.click(screen.getByRole("button", { name: "新建分支" }));
  expect(createGitBranch).toHaveBeenCalledWith("main", "feature/new", "");

  await user.selectOptions(screen.getByLabelText("切换分支"), "feature/new");
  await user.click(screen.getByRole("button", { name: "切换" }));
  expect(switchGitBranch).toHaveBeenCalledWith("main", "feature/new");
});

test("git screen applies and drops selected stashes", async () => {
  const user = userEvent.setup();
  const applyGitStash = vi.fn(async () => ({ message: "已应用 stash", overview: buildRepoOverview() }));
  const dropGitStash = vi.fn(async () => ({ message: "已删除 stash", overview: buildRepoOverview() }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        listGitStashes: async () => ({
          items: [{ ref: "stash@{0}", hash: "abc1234", createdAt: "2026-04-28 10:30:00 +0800", message: "On main: Web Bot stash" }],
        }),
        applyGitStash,
        dropGitStash,
      })}
    />,
  );

  expect(await screen.findByText("stash@{0}")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "应用 stash@{0}" }));
  expect(applyGitStash).toHaveBeenCalledWith("main", "stash@{0}");

  await user.click(screen.getByRole("button", { name: "删除 stash@{0}" }));
  expect(dropGitStash).toHaveBeenCalledWith("main", "stash@{0}");
});

test("git screen loads blame for a changed file", async () => {
  const user = userEvent.setup();
  const getGitBlame = vi.fn(async () => ({
    path: "tracked.txt",
    lines: [
      {
        line: 1,
        commit: "abcdef0123456789",
        shortCommit: "abcdef0",
        authorName: "Web Bot",
        authorMail: "web-bot@example.com",
        authoredAt: "2026-04-28T02:30:00",
        summary: "feat: initial commit",
        content: "before",
      },
    ],
  }));

  render(<GitScreen botAlias="main" client={createClient({ getGitBlame })} />);

  await user.click(await screen.findByLabelText("查看 blame tracked.txt"));

  expect(getGitBlame).toHaveBeenCalledWith("main", "tracked.txt");
  const blameTitle = await screen.findByText("tracked.txt blame");
  const blamePanel = blameTitle.closest("section");
  expect(blamePanel).not.toBeNull();
  expect(within(blamePanel as HTMLElement).getByText("abcdef0")).toBeInTheDocument();
  expect(within(blamePanel as HTMLElement).getByText("before")).toBeInTheDocument();
});

test("git screen generates commit message into textarea", async () => {
  const user = userEvent.setup();
  const generateGitCommitMessage = vi.fn(async () => ({
    message: "feat(git): add generated commit message flow",
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ generateGitCommitMessage })}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "生成 commit message" }));

  expect(generateGitCommitMessage).toHaveBeenCalledWith("main");
  expect(await screen.findByText("已生成提交说明")).toBeInTheDocument();
  expect(screen.getByLabelText("commit message")).toHaveValue("feat(git): add generated commit message flow");
});

test("git screen shows generate error", async () => {
  const user = userEvent.setup();
  const generateGitCommitMessage = vi.fn(async () => {
    throw new Error("生成失败");
  });

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ generateGitCommitMessage })}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "生成 commit message" }));

  expect(await screen.findByText("生成失败")).toBeInTheDocument();
});

test("git screen saves and resets commit message cli config", async () => {
  const user = userEvent.setup();
  const updateGitCommitMessageConfig = vi.fn(
    async (
      _botAlias: string,
      input: Parameters<WebBotClient["updateGitCommitMessageConfig"]>[1],
    ): Promise<GitCommitMessageCliConfig> => ({
      cliType: input.cliType || "claude",
      cliPath: input.cliPath || "claude",
      params: {
        reasoning_effort: "low",
        extra_args: [],
        ...(input.params || {}),
      },
      defaults: {
        reasoning_effort: "medium",
        extra_args: [],
      },
      schema: {
        reasoning_effort: {
          type: "string" as const,
          enum: ["high", "medium", "low"],
          description: "推理努力程度",
        },
        extra_args: {
          type: "string_list" as const,
          description: "额外参数",
        },
      },
    }),
  );
  const resetGitCommitMessageConfig = vi.fn(async (): Promise<GitCommitMessageCliConfig> => ({
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
        type: "string" as const,
        enum: ["high", "medium", "low"],
        description: "推理努力程度",
      },
      extra_args: {
        type: "string_list" as const,
        description: "额外参数",
      },
    },
  }));

  render(
    <GitScreen
      botAlias="main"
      client={createClient({ updateGitCommitMessageConfig, resetGitCommitMessageConfig })}
      sessionCapabilities={["manage_cli_params"]}
    />,
  );

  expect(await screen.findByTestId("git-commit-cli-panel")).toBeInTheDocument();
  expect(screen.getAllByText("Commit Message CLI")).toHaveLength(1);
  await user.selectOptions(await screen.findByLabelText("Commit Message CLI 类型"), "claude");
  await user.clear(screen.getByLabelText("Commit Message CLI 路径"));
  await user.type(screen.getByLabelText("Commit Message CLI 路径"), "claude-custom");
  await user.selectOptions(screen.getByLabelText("推理努力程度"), "low");
  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(updateGitCommitMessageConfig).toHaveBeenCalledWith("main", {
    cliType: "claude",
    cliPath: "claude-custom",
    params: {
      reasoning_effort: "low",
    },
  });
  expect(await screen.findByText("Commit Message CLI 配置已保存")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "恢复默认" }));
  expect(resetGitCommitMessageConfig).toHaveBeenCalledWith("main");
  expect(await screen.findByText("Commit Message CLI 已恢复默认值")).toBeInTheDocument();
});

test("git screen keeps commit message cli model none after saving", async () => {
  const user = userEvent.setup();
  const updateGitCommitMessageConfig = vi.fn(
    async (
      _botAlias: string,
      input: Parameters<WebBotClient["updateGitCommitMessageConfig"]>[1],
    ): Promise<GitCommitMessageCliConfig> => ({
      cliType: "codex",
      cliPath: "codex",
      params: {
        model: input.params?.model === "none" ? null : input.params?.model,
      },
      defaults: {
        model: "gpt-5.4",
      },
      schema: {
        model: {
          type: "string" as const,
          enum: ["gpt-5.5", "gpt-5.4", "none"],
          description: "模型选择",
          nullable: true,
        },
      },
    }),
  );

  render(
    <GitScreen
      botAlias="main"
      client={createClient({
        getGitCommitMessageConfig: async (): Promise<GitCommitMessageCliConfig> => ({
          cliType: "codex",
          cliPath: "codex",
          params: {
            model: "gpt-5.5",
          },
          defaults: {
            model: "gpt-5.4",
          },
          schema: {
            model: {
              type: "string",
              enum: ["gpt-5.5", "gpt-5.4", "none"],
              description: "模型选择",
              nullable: true,
            },
          },
        }),
        updateGitCommitMessageConfig,
      })}
      sessionCapabilities={["manage_cli_params"]}
    />,
  );

  const modelSelect = await screen.findByLabelText("模型选择");
  await user.selectOptions(modelSelect, "none");
  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(updateGitCommitMessageConfig).toHaveBeenCalledWith("main", {
    cliType: "codex",
    cliPath: "codex",
    params: {
      model: "none",
    },
  });
  expect(await screen.findByText("Commit Message CLI 配置已保存")).toBeInTheDocument();
  expect(screen.getByLabelText("模型选择")).toHaveValue("none");
});

test("git screen commit message cli config is read-only without permission", async () => {
  render(
    <GitScreen
      botAlias="main"
      client={createClient()}
      sessionCapabilities={["git_ops"]}
    />,
  );

  expect(await screen.findByText("当前模式只读")).toBeInTheDocument();
  expect(await screen.findByLabelText("Commit Message CLI 类型")).toBeDisabled();
  expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
});
