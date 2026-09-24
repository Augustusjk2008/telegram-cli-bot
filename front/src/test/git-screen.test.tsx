import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { GitScreen } from "../screens/GitScreen";
import { WebApiClientError } from "../services/types";
import type {
  GitActionResult,
  GitBranchList,
  GitCommitGraphPayload,
  GitCommitMessageCliConfig,
  GitDiffPayload,
  GitIdentityConfig,
  GitOverview,
  GitStashList,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { createGitChangesFixture } from "./fixtures/performance";

afterEach(() => {
  vi.restoreAllMocks();
});

const overview: GitOverview = {
  repoFound: true,
  canInit: false,
  workingDir: "C:\\workspace\\repo",
  repoPath: "C:\\workspace\\repo",
  repoName: "repo",
  currentBranch: "main",
  isClean: false,
  aheadCount: 0,
  behindCount: 0,
  changedFiles: [
    {
      path: "src/deep/same.ts",
      status: " M",
      staged: false,
      unstaged: true,
      untracked: false,
      additions: 7,
      deletions: 3,
      stagedAdditions: 0,
      stagedDeletions: 0,
      unstagedAdditions: 7,
      unstagedDeletions: 3,
    },
    {
      path: "docs/same.ts",
      status: "M ",
      staged: true,
      unstaged: false,
      untracked: false,
      additions: 2,
      deletions: 1,
      stagedAdditions: 2,
      stagedDeletions: 1,
      unstagedAdditions: 0,
      unstagedDeletions: 0,
    },
    {
      path: "new/folder/file.txt",
      status: "??",
      staged: false,
      unstaged: false,
      untracked: true,
      additions: 4,
      deletions: 0,
      stagedAdditions: 0,
      stagedDeletions: 0,
      unstagedAdditions: 4,
      unstagedDeletions: 0,
    },
  ],
  recentCommits: [],
};

const graphPayload: GitCommitGraphPayload = {
  repoFound: true,
  scope: "all",
  nodes: [],
  hasMore: false,
  nextCursor: "",
};

const identityConfig: GitIdentityConfig = {
  repoFound: true,
  repoPath: "C:\\workspace\\repo",
  global: { name: "", email: "" },
  local: { name: "", email: "" },
};

const branchList: GitBranchList = {
  currentBranch: "main",
  branches: [],
};

const stashList: GitStashList = {
  items: [],
};

const commitMessageConfig: GitCommitMessageCliConfig = {
  cliType: "codex",
  cliPath: "codex",
  params: {},
  defaults: {},
  schema: {},
};

function cloneOverview(): GitOverview {
  return {
    ...overview,
    changedFiles: overview.changedFiles.map((item) => ({ ...item })),
    recentCommits: overview.recentCommits.map((item) => ({ ...item })),
  };
}

function createActionResult(): GitActionResult {
  return {
    message: "ok",
    overview: cloneOverview(),
  };
}

function createGitScreenClient() {
  const getGitOverview = vi.fn(async () => cloneOverview());
  const getGitDiff = vi.fn(async (_botAlias: string, path: string, staged = false): Promise<GitDiffPayload> => ({
    path,
    staged,
    diff: [
      `diff --git a/${path} b/${path}`,
      "index abc..def 100644",
      `--- a/${path}`,
      `+++ b/${path}`,
      "@@ -1,3 +1,3 @@",
      " unchanged line",
      "-old line",
      "+new line",
    ].join("\n"),
    truncated: false,
  }));
  const getGitCommitGraph = vi.fn(async () => graphPayload);
  const client = {
    getGitOverview,
    getGitCommitGraph,
    getGitIdentityConfig: vi.fn(async () => identityConfig),
    getActiveGitSmartCommit: vi.fn(async () => null),
    listGitBranches: vi.fn(async () => branchList),
    listGitStashes: vi.fn(async () => stashList),
    getGitDiff,
    getGitCommitMessageConfig: vi.fn(async () => commitMessageConfig),
    updateGitCommitMessageConfig: vi.fn(async () => commitMessageConfig),
    resetGitCommitMessageConfig: vi.fn(async () => commitMessageConfig),
    stageGitPaths: vi.fn(async () => createActionResult()),
    unstageGitPaths: vi.fn(async () => createActionResult()),
    discardGitPaths: vi.fn(async () => createActionResult()),
    commitGitChanges: vi.fn(async () => createActionResult()),
  };
  return {
    client: client as unknown as WebBotClient,
    getGitDiff,
    getGitOverview,
    getGitCommitGraph,
  };
}

test("remote Git supports overview, all three diffs, individual staging and manual commit without local-only requests", async () => {
  const { client, getGitOverview, getGitDiff } = createGitScreenClient();
  const recentCommit = { hash: "abc1234", shortHash: "abc1234", subject: "Remote commit", authorName: "Dev", authoredAt: "2026-09-24" };
  getGitOverview.mockResolvedValue({ ...cloneOverview(), recentCommits: [recentCommit] });
  const committed = { ...cloneOverview(), changedFiles: [], isClean: true, recentCommits: [{ ...recentCommit, hash: "def5678", shortHash: "def5678", subject: "Manual change" }] };
  vi.mocked(client.commitGitChanges).mockResolvedValue({ message: "已提交", overview: committed });
  render(<GitScreen botAlias="remote" client={client} remote />);

  expect(await screen.findByText("Remote commit")).toBeInTheDocument();
  expect(screen.getByText("main")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "提交更改" })).toBeDisabled();
  for (const [path, staged] of [["docs/same.ts", true], ["src/deep/same.ts", false], ["new/folder/file.txt", false]] as const) {
    fireEvent.click(screen.getByRole("button", { name: `打开 diff ${path}` }));
    await waitFor(() => expect(getGitDiff).toHaveBeenLastCalledWith("remote", path, staged));
    expect(await screen.findByTestId("git-diff-content")).toHaveTextContent("new line");
  }
  for (const path of ["src/deep/same.ts", "new/folder/file.txt"]) {
    fireEvent.click(screen.getByRole("button", { name: `暂存 ${path}` }));
    await waitFor(() => expect(client.stageGitPaths).toHaveBeenLastCalledWith("remote", [path]));
    await waitFor(() => expect(screen.getByRole("button", { name: `暂存 ${path}` })).toBeEnabled());
  }
  fireEvent.click(screen.getByRole("button", { name: "取消暂存 docs/same.ts" }));
  await waitFor(() => expect(client.unstageGitPaths).toHaveBeenCalledWith("remote", ["docs/same.ts"]));
  fireEvent.change(screen.getByRole("textbox", { name: "commit message" }), { target: { value: "Manual change" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "提交更改" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "提交更改" }));
  expect(await screen.findByText("Manual change")).toBeInTheDocument();
  expect(client.commitGitChanges).toHaveBeenCalledExactlyOnceWith("remote", "Manual change");
  expect(screen.getByRole("textbox", { name: "commit message" })).toHaveValue("");
  expect(screen.getByText("工作区干净")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新 Git 状态" }));
  await waitFor(() => expect(getGitOverview).toHaveBeenCalledTimes(2));
  await screen.findByText("Remote commit");

  expect(screen.queryByRole("button", { name: /丢弃|暂存全部|初始化|新建分支|切换|Fetch|Pull|Push|智能提交|生成|重置/ })).not.toBeInTheDocument();
  expect(screen.queryByTestId("git-version-tree-panel")).not.toBeInTheDocument();
  expect(screen.queryByTestId("git-identity-panel")).not.toBeInTheDocument();
  expect(screen.queryByTestId("git-commit-cli-panel")).not.toBeInTheDocument();
  for (const request of [client.getGitCommitGraph, client.getGitIdentityConfig, client.getActiveGitSmartCommit, client.listGitBranches, client.listGitStashes, client.getGitCommitMessageConfig]) {
    expect(request).not.toHaveBeenCalled();
  }
});

test("remote missing Git shows installation and SSH PATH guidance and retries only overview", async () => {
  const { client, getGitOverview } = createGitScreenClient();
  getGitOverview.mockRejectedValueOnce(new WebApiClientError("Git is unavailable", { status: 503, code: "remote_git_not_found" }));
  render(<GitScreen botAlias="remote" client={client} remote embedded />);
  const guidance = await screen.findByRole("alert");
  expect(guidance).toHaveTextContent("非交互式 PATH");
  expect(within(guidance).getByRole("link", { name: "Linux 官方安装指南" })).toHaveAttribute("href", "https://git-scm.com/install/linux");
  expect(within(guidance).getByRole("link", { name: "Windows 官方安装指南" })).toHaveAttribute("href", "https://git-scm.com/install/windows");
  fireEvent.click(within(guidance).getByRole("button", { name: "重试" }));
  await screen.findByTestId("git-changes-panel");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(getGitOverview).toHaveBeenCalledTimes(2);
  expect(client.getGitIdentityConfig).not.toHaveBeenCalled();
});

test("remote SSH errors remain distinct from missing Git", async () => {
  const { client, getGitOverview } = createGitScreenClient();
  getGitOverview.mockRejectedValue(new WebApiClientError("SSH authentication failed", { status: 401, code: "remote_auth_failed" }));
  render(<GitScreen botAlias="remote" client={client} remote />);
  expect(await screen.findByText("SSH authentication failed")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /官方安装指南/ })).not.toBeInTheDocument();
});

test("remote non-repository requires an existing repository root and never offers init", async () => {
  const { client, getGitOverview } = createGitScreenClient();
  getGitOverview.mockResolvedValue({ ...cloneOverview(), repoFound: false, canInit: true });
  render(<GitScreen botAlias="remote" client={client} remote />);
  expect(await screen.findByText("请选择已有 Git 仓库的根目录作为远程工作区。")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "初始化 Git 仓库" })).not.toBeInTheDocument();
});

test("a failed remote commit preserves the draft and does not retry the mutation", async () => {
  const { client } = createGitScreenClient();
  vi.mocked(client.commitGitChanges).mockRejectedValue(new Error("SSH command timed out"));
  render(<GitScreen botAlias="remote" client={client} remote />);
  fireEvent.change(await screen.findByRole("textbox", { name: "commit message" }), { target: { value: "Keep this draft" } });
  fireEvent.click(screen.getByRole("button", { name: "提交更改" }));
  expect(await screen.findByText("SSH command timed out")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "commit message" })).toHaveValue("Keep this draft");
  expect(client.commitGitChanges).toHaveBeenCalledOnce();
  expect(client.getGitOverview).toHaveBeenCalledOnce();
});

test("allows git users to manage commit message cli config", async () => {
  const { client } = createGitScreenClient();
  render(<GitScreen botAlias="main" client={client} sessionCapabilities={["git_ops"]} />);

  const panel = await screen.findByTestId("git-commit-cli-panel");
  await waitFor(() => {
    expect(within(panel).getByRole("button", { name: /恢复默认/ })).toBeEnabled();
  });
  expect(within(panel).queryByText("当前模式只读")).not.toBeInTheDocument();
});

test("reveals the full commit message when a commit row is tapped", async () => {
  const { client, getGitCommitGraph } = createGitScreenClient();
  getGitCommitGraph.mockResolvedValue({
    ...graphPayload,
    nodes: [{
      hash: "abcdef1234567890",
      shortHash: "abcdef1",
      parents: [],
      authorName: "Kai",
      authoredAt: "2026-08-08T12:00:00Z",
      subject: "修复提交标题",
      message: "修复提交标题\n\n这是完整的 commit message 详情。",
      refs: [],
      graph: { column: 0, width: 1, edges: [] },
    }],
  });

  render(<GitScreen botAlias="main" client={client} />);

  const row = await screen.findByTestId("git-graph-row-abcdef1");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  fireEvent.pointerDown(row, { pointerType: "touch" });
  fireEvent.pointerUp(row, { pointerType: "touch" });
  fireEvent.click(row);

  expect(screen.getByRole("tooltip")).toHaveTextContent("这是完整的 commit message 详情。");
});

test("renders compact change rows with basename, stats, and retained actions", async () => {
  const { client } = createGitScreenClient();
  const openDiff = vi.fn();
  render(<GitScreen botAlias="main" client={client} onOpenDiff={openDiff} />);

  const unstagedRow = await screen.findByTestId("git-change-row-src/deep/same.ts");
  const stagedRow = await screen.findByTestId("git-change-row-docs/same.ts");
  const untrackedRow = await screen.findByTestId("git-change-row-new/folder/file.txt");

  expect(screen.getAllByText("same.ts")).toHaveLength(2);
  expect(screen.queryByText("src/deep/same.ts")).not.toBeInTheDocument();
  expect(unstagedRow).toHaveAttribute("data-full-path", "src/deep/same.ts");

  const fileButton = within(unstagedRow).getByRole("button", { name: "打开 diff src/deep/same.ts" });
  expect(fileButton).toHaveTextContent("same.ts");
  expect(fileButton).toHaveAttribute("title", "src/deep/same.ts");
  expect(within(unstagedRow).getByText("+7")).toBeInTheDocument();
  expect(within(unstagedRow).getByText("-3")).toBeInTheDocument();
  expect(within(stagedRow).getByText("+2")).toBeInTheDocument();
  expect(within(untrackedRow).getByText("+4")).toBeInTheDocument();

  expect(screen.queryByLabelText(/查看 blame/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/在编辑器打开/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("暂存 src/deep/same.ts")).toBeEnabled();
  expect(screen.getByLabelText("取消暂存 docs/same.ts")).toBeEnabled();
  expect(screen.getByLabelText("丢弃 src/deep/same.ts")).toBeEnabled();

  await userEvent.click(fileButton);
  expect(openDiff).toHaveBeenCalledWith("src/deep/same.ts", false);

  await userEvent.click(within(stagedRow).getByRole("button", { name: "打开 diff docs/same.ts" }));
  expect(openDiff).toHaveBeenCalledWith("docs/same.ts", true);
});

test("virtualizes 5000 changed files", async () => {
  const { client, getGitOverview } = createGitScreenClient();
  getGitOverview.mockResolvedValue(createGitChangesFixture(5_000));

  render(<GitScreen botAlias="main" client={client} />);

  const list = await screen.findByTestId("git-virtual-change-list-unstaged");
  const mountedRows = list.querySelectorAll("[data-testid^='git-change-row-']");
  expect(mountedRows.length).toBeGreaterThan(0);
  expect(mountedRows.length).toBeLessThanOrEqual(50);
});

test("loads readonly diff panel when no external diff opener is provided", async () => {
  const { client, getGitDiff } = createGitScreenClient();
  render(<GitScreen botAlias="main" client={client} />);

  const row = await screen.findByTestId("git-change-row-src/deep/same.ts");
  await userEvent.click(within(row).getByRole("button", { name: "打开 diff src/deep/same.ts" }));

  await waitFor(() => {
    expect(getGitDiff).toHaveBeenCalledWith("main", "src/deep/same.ts", false);
  });
  expect(await screen.findByTestId("git-diff-panel")).toBeInTheDocument();
});
