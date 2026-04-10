import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import type { BotOverview, BotSummary, ChatMessage, CliParamsPayload, DirectoryListing, GitActionResult, GitDiffPayload, GitOverview, SessionState, SystemScript, SystemScriptResult, TunnelSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const baseClient: WebBotClient = {
    login: async (): Promise<SessionState> => ({
      currentBotAlias: "main",
      currentPath: "C:\\workspace",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    }),
    listBots: async (): Promise<BotSummary[]> => [],
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
    }),
    listMessages: async (): Promise<ChatMessage[]> => [],
    sendMessage: async () => ({
      id: "assistant-1",
      role: "assistant" as const,
      text: "ok",
      createdAt: new Date().toISOString(),
      state: "done" as const,
    }),
    getCurrentPath: async () => "C:\\workspace",
    listFiles: async (): Promise<DirectoryListing> => ({
      workingDir: "C:\\workspace",
      entries: [
        { name: "README.md", isDir: false, size: 512, updatedAt: "2026-04-09T10:00:00Z" },
        { name: "notes.txt", isDir: false, size: 128, updatedAt: "2026-04-09T10:00:00Z" },
      ],
    }),
    changeDirectory: async () => "C:\\workspace",
    readFile: async (_botAlias: string, filename: string) => {
      if (filename === "README.md") {
        return [
          "# Markdown Title",
          "",
          "- item 1",
          "- item 2",
          "",
          "| Name | Value |",
          "| --- | --- |",
          "| Cell | 42 |",
          "",
          "![Architecture](assets/diagram.png)",
          "",
          "```ts",
          "const answer = 42;",
          "```",
        ].join("\n");
      }
      return "# Raw Heading\n\n- should stay literal";
    },
    readFileFull: async (_botAlias: string, filename: string) => `FULL:${filename}`,
    uploadFile: async () => undefined,
    downloadFile: async () => undefined,
    resetSession: async () => undefined,
    killTask: async () => "已发送终止任务请求",
    getGitProxySettings: async () => ({ port: "" }),
    updateGitProxySettings: async () => ({ port: "" }),
    updateBotWorkdir: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
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
    restartService: async (): Promise<void> => undefined,
    getGitOverview: async (): Promise<GitOverview> => ({
      repoFound: false,
      canInit: true,
      workingDir: "C:\\workspace",
      repoPath: "",
      repoName: "",
      currentBranch: "",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    }),
    initGitRepository: async (): Promise<GitOverview> => ({
      repoFound: true,
      canInit: false,
      workingDir: "C:\\workspace",
      repoPath: "C:\\workspace",
      repoName: "workspace",
      currentBranch: "main",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    }),
    getGitDiff: async (): Promise<GitDiffPayload> => ({
      path: "README.md",
      staged: false,
      diff: "",
    }),
    stageGitPaths: async (): Promise<GitActionResult> => ({
      message: "已暂存",
      overview: await createClient().getGitOverview("main"),
    }),
    unstageGitPaths: async (): Promise<GitActionResult> => ({
      message: "已取消暂存",
      overview: await createClient().getGitOverview("main"),
    }),
    commitGitChanges: async (): Promise<GitActionResult> => ({
      message: "已提交",
      overview: await createClient().initGitRepository("main"),
    }),
    fetchGitRemote: async (): Promise<GitActionResult> => ({
      message: "已抓取",
      overview: await createClient().initGitRepository("main"),
    }),
    pullGitRemote: async (): Promise<GitActionResult> => ({
      message: "已拉取",
      overview: await createClient().initGitRepository("main"),
    }),
    pushGitRemote: async (): Promise<GitActionResult> => ({
      message: "已推送",
      overview: await createClient().initGitRepository("main"),
    }),
    stashGitChanges: async (): Promise<GitActionResult> => ({
      message: "已暂存工作区",
      overview: await createClient().initGitRepository("main"),
    }),
    popGitStash: async (): Promise<GitActionResult> => ({
      message: "已恢复暂存",
      overview: await createClient().initGitRepository("main"),
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
  };
  return { ...baseClient, ...overrides };
}

test("renders markdown files as formatted content", async () => {
  const user = userEvent.setup();
  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: /README\.md/i }));

  expect(await screen.findByRole("heading", { name: "Markdown Title" })).toBeInTheDocument();
  expect(screen.getByText("item 1")).toBeInTheDocument();
  expect(screen.getByText("Cell")).toBeInTheDocument();
  expect(screen.getByText("const answer = 42;")).toBeInTheDocument();
});

test("shows markdown image paths instead of rendering images", async () => {
  const user = userEvent.setup();
  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: /README\.md/i }));

  expect(await screen.findByText(/assets\/diagram\.png/)).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test("keeps non-markdown files in plain-text preview mode", async () => {
  const user = userEvent.setup();
  render(<FilesScreen botAlias="main" client={createClient()} />);

  await user.click(await screen.findByRole("button", { name: /notes\.txt/i }));

  expect(await screen.findByText((content) => content.includes("# Raw Heading"))).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes("- should stay literal"))).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Raw Heading" })).not.toBeInTheDocument();
});

test("can load full file content from preview modal", async () => {
  const user = userEvent.setup();
  const readFullSpy = vi.fn(async () => "完整内容\n第二行");
  const client = createClient();
  client.readFileFull = readFullSpy;

  render(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: /notes\.txt/i }));
  await user.click(await screen.findByRole("button", { name: "全文读取" }));

  expect(readFullSpy).toHaveBeenCalledWith("main", "notes.txt");
  expect(await screen.findByText((content) => content.includes("完整内容"))).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
});

test("home button refreshes the file view to the latest working directory", async () => {
  const user = userEvent.setup();
  const listFilesSpy = vi
    .fn<() => Promise<DirectoryListing>>()
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace\\old",
      entries: [{ name: "old.txt", isDir: false }],
    })
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace\\new-home",
      entries: [{ name: "new.txt", isDir: false }],
    });

  render(<FilesScreen botAlias="main" client={createClient({ listFiles: listFilesSpy })} />);

  expect(await screen.findByText("main - C:\\workspace\\old")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Home" }));

  expect(listFilesSpy).toHaveBeenCalledTimes(2);
  expect(await screen.findByText("main - C:\\workspace\\new-home")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /new\.txt/i })).toBeInTheDocument();
});
