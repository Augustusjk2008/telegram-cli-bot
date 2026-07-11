import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { GitScreen } from "../screens/GitScreen";
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
  const client = {
    getGitOverview,
    getGitCommitGraph: vi.fn(async () => graphPayload),
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
  };
  return {
    client: client as unknown as WebBotClient,
    getGitDiff,
    getGitOverview,
  };
}

test("allows git users to manage commit message cli config", async () => {
  const { client } = createGitScreenClient();
  render(<GitScreen botAlias="main" client={client} sessionCapabilities={["git_ops"]} />);

  const panel = await screen.findByTestId("git-commit-cli-panel");
  await waitFor(() => {
    expect(within(panel).getByRole("button", { name: /恢复默认/ })).toBeEnabled();
  });
  expect(within(panel).queryByText("当前模式只读")).not.toBeInTheDocument();
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
  const diffContent = await screen.findByTestId("git-diff-content");
  expect(within(diffContent).queryByText(/diff --git/)).not.toBeInTheDocument();
  expect(within(diffContent).queryByText(/@@/)).not.toBeInTheDocument();
  expect(within(diffContent).queryByText(" unchanged line")).not.toBeInTheDocument();

  const deleteRow = within(diffContent).getByText("-old line").closest("[data-diff-kind]");
  const addRow = within(diffContent).getByText("+new line").closest("[data-diff-kind]");
  expect(deleteRow).toHaveAttribute("data-diff-kind", "delete");
  expect(deleteRow).toHaveClass("bg-red-50");
  expect(addRow).toHaveAttribute("data-diff-kind", "add");
  expect(addRow).toHaveClass("bg-emerald-50");
});
