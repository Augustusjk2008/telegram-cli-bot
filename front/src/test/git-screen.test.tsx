import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { GitScreen } from "../screens/GitScreen";
import type {
  BotOverview,
  BotSummary,
  ChatMessage,
  CliParamsPayload,
  DirectoryListing,
  GitActionResult,
  GitDiffPayload,
  GitOverview,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function buildRepoOverview(): GitOverview {
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
  };
}

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  return {
    login: async (): Promise<SessionState> => ({
      currentBotAlias: "main",
      currentPath: "C:\\workspace\\repo",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    }),
    listBots: async (): Promise<BotSummary[]> => [],
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\repo",
    }),
    listMessages: async (): Promise<ChatMessage[]> => [],
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
    readFile: async () => "",
    readFileFull: async () => "",
    uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => "已发送终止任务请求",
    restartService: async () => undefined,
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
    getGitDiff: async (): Promise<GitDiffPayload> => ({
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
    ...overrides,
  };
}

test("renders git repo summary and changed files", async () => {
  render(<GitScreen botAlias="main" client={createClient()} />);

  expect(await screen.findByText("repo")).toBeInTheDocument();
  expect(screen.getByText("当前分支")).toBeInTheDocument();
  expect(screen.getByText("tracked.txt")).toBeInTheDocument();
  expect(screen.getByText("feat: initial commit")).toBeInTheDocument();
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
