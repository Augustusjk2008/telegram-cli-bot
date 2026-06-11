import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileReadResult, GitDiffPayload, GitOverview } from "../services/types";
import { SoloWorkbench } from "../workbench/SoloWorkbench";
import type { SoloSessionSnapshot } from "../workbench/soloTypes";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const snapshot: SoloSessionSnapshot = {
  botAlias: "main",
  executionMode: "native_agent",
  conversationId: "conv-1",
  conversationTitle: "当前会话",
  workingDir: "C:\\workspace\\main",
  model: "claude-sonnet-4-5",
  nativeSessionId: "native-session-1",
  workspaceHistoryHead: "head-1",
  linearIndex: 1,
  rollbackSupported: true,
  degraded: false,
  degradedReason: "",
  contextStatusText: "上下文正常",
};

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function buildFileResult(content: string): FileReadResult {
  return {
    content,
    mode: "head",
    fileSizeBytes: content.length,
    isFullContent: true,
  };
}

function buildGitOverview(changedFiles: GitOverview["changedFiles"]): GitOverview {
  return {
    repoFound: true,
    canInit: false,
    workingDir: "C:\\workspace\\main",
    repoPath: "C:\\workspace\\main",
    repoName: "main",
    currentBranch: "main",
    isClean: false,
    aheadCount: 0,
    behindCount: 0,
    changedFiles,
    recentCommits: [],
  };
}

function renderSoloWorkbench(
  client: MockWebBotClient,
  chatPaneContent: Parameters<typeof SoloWorkbench>[0]["chatPaneContent"],
  botAlias = "main",
  snapshotOverride: Partial<SoloSessionSnapshot> = {},
) {
  return render(
    <SoloWorkbench
      botAlias={botAlias}
      client={client}
      workspaceName="main"
      viewMode="desktop"
      chatPaneContent={chatPaneContent}
      sessionSnapshot={{ ...snapshot, botAlias, ...snapshotOverride }}
      productMode="solo"
      soloAvailable
      onProductModeChange={() => {}}
      onViewModeChange={() => {}}
      onOpenBotSwitcher={() => {}}
      onLogout={() => {}}
    />,
  );
}

test("renders solo layout with session tab and no manual file controls", () => {
  renderSoloWorkbench(new MockWebBotClient(), <div>chat</div>);

  expect(screen.getByTestId("solo-workbench-root")).toBeInTheDocument();
  expect(screen.getByTestId("solo-chat-pane")).toBeInTheDocument();
  expect(screen.getByTestId("solo-tabs-pane")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "会话信息" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tab", { name: "Git" })).toBeInTheDocument();
  expect(screen.queryByText("打开系统文件夹")).not.toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: /路径|文件路径|path/i })).not.toBeInTheDocument();
});

test("opens a readonly file preview tab from chat request", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFile = vi.spyOn(client, "readFile");

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <button type="button" onClick={() => requestPreview("README.md")}>打开 README.md</button>
  ));

  await user.click(screen.getByRole("button", { name: "打开 README.md" }));

  await waitFor(() => {
    expect(readFile).toHaveBeenCalledWith("main", "README.md");
  });
  expect(await screen.findByRole("tab", { name: "README.md" })).toBeInTheDocument();
  expect(await screen.findByText(/Mock full content for README\.md/)).toBeInTheDocument();
});

test("reuses existing file preview tab for the same path", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <button type="button" onClick={() => requestPreview("README.md")}>打开 README.md</button>
  ));

  await user.click(screen.getByRole("button", { name: "打开 README.md" }));
  await screen.findByText(/Mock full content for README\.md/);
  await user.click(screen.getByRole("button", { name: "打开 README.md" }));

  expect(screen.getAllByRole("tab", { name: "README.md" })).toHaveLength(1);
});

test("keeps file preview loading state per path", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const pending: Record<string, ReturnType<typeof createDeferred<FileReadResult>>> = {};
  vi.spyOn(client, "readFile").mockImplementation(async (_botAlias, filename) => {
    pending[filename] = createDeferred<FileReadResult>();
    return pending[filename].promise;
  });

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <div>
      <button type="button" onClick={() => requestPreview("A.md")}>打开 A.md</button>
      <button type="button" onClick={() => requestPreview("B.md")}>打开 B.md</button>
    </div>
  ));

  await user.click(screen.getByRole("button", { name: "打开 A.md" }));
  await user.click(screen.getByRole("button", { name: "打开 B.md" }));

  pending["B.md"].resolve(buildFileResult("# B content"));
  expect(await screen.findByRole("heading", { name: "B content" })).toBeInTheDocument();
  pending["A.md"].resolve(buildFileResult("# A content"));
  await user.click(screen.getByRole("tab", { name: "A.md" }));

  expect(await screen.findByRole("heading", { name: "A content" })).toBeInTheDocument();
});

test("opens readonly git diff tab from git status", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const getGitDiff = vi.spyOn(client, "getGitDiff").mockResolvedValue({
    path: "bot/web/server.py",
    staged: true,
    diff: "diff --git a/bot/web/server.py b/bot/web/server.py\n@@ -1 +1 @@\n-old\n+new",
  });

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "Git" }));
  await user.click(await screen.findByLabelText("在编辑器打开 bot/web/server.py"));

  expect(getGitDiff).toHaveBeenCalledWith("main", "bot/web/server.py", true);
  expect(await screen.findByRole("tab", { name: "server.py.diff" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText(/\+new/)).toBeInTheDocument();
  expect(screen.queryByLabelText("文件内容")).not.toBeInTheDocument();
});

test("keeps git diff content when switching tabs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const getGitDiff = vi.spyOn(client, "getGitDiff").mockResolvedValue({
    path: "bot/web/server.py",
    staged: true,
    diff: "persistent diff\n+new",
  });

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "Git" }));
  await user.click(await screen.findByLabelText("在编辑器打开 bot/web/server.py"));
  expect(await screen.findByText(/persistent diff/)).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "会话信息" }));
  await user.click(screen.getByRole("tab", { name: "server.py.diff" }));

  expect(screen.getByText(/persistent diff/)).toBeInTheDocument();
  expect(getGitDiff).toHaveBeenCalledTimes(1);
});

test("keeps staged and worktree diff tabs separate", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "getGitOverview").mockResolvedValue(buildGitOverview([
    { path: "tracked.txt", status: "M ", staged: true, unstaged: false, untracked: false },
    { path: "tracked.txt", status: " M", staged: false, unstaged: true, untracked: false },
  ]));
  vi.spyOn(client, "getGitDiff").mockImplementation(async (_botAlias, path, staged): Promise<GitDiffPayload> => ({
    path,
    staged: Boolean(staged),
    diff: staged ? "staged diff\n+index" : "worktree diff\n+worktree",
  }));

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "Git" }));
  const diffButtons = await screen.findAllByLabelText("在编辑器打开 tracked.txt");
  await user.click(diffButtons[0]);
  expect(await screen.findByText(/staged diff/)).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Git" }));
  const refreshedDiffButtons = await screen.findAllByLabelText("在编辑器打开 tracked.txt");
  await user.click(refreshedDiffButtons[1]);
  expect(await screen.findByText(/worktree diff/)).toBeInTheDocument();

  const diffTabs = screen.getAllByRole("tab", { name: "tracked.txt.diff" });
  expect(diffTabs).toHaveLength(2);
  await user.click(diffTabs[0]);
  expect(screen.getByText(/staged diff/)).toBeInTheDocument();
  await user.click(diffTabs[1]);
  expect(screen.getByText(/worktree diff/)).toBeInTheDocument();
});

test("renders session info with short ids and basename only", () => {
  renderSoloWorkbench(new MockWebBotClient(), <div>chat</div>, "main", {
    conversationId: "conversation-abcdef1234567890",
    conversationTitle: "重要会话",
    workingDir: "C:\\Users\\demo\\secret\\repo",
    nativeSessionId: "native-session-abcdef1234567890",
    workspaceHistoryHead: "history-head-abcdef1234567890",
  });

  expect(screen.getByText("重要会话 (conversa...7890)")).toBeInTheDocument();
  expect(screen.getByText("repo")).toBeInTheDocument();
  expect(screen.getByText("native-s...7890")).toBeInTheDocument();
  expect(screen.getByText("history-...7890")).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("C:\\Users\\demo\\secret\\repo");
});

test("does not leak manual path list or full cwd", () => {
  renderSoloWorkbench(new MockWebBotClient(), <div>chat</div>, "main", {
    workingDir: "C:\\Users\\demo\\private\\repo",
  });

  expect(document.body).not.toHaveTextContent("C:\\Users\\demo\\private");
  expect(document.body).not.toHaveTextContent("manual");
  expect(screen.queryByRole("textbox", { name: /路径|文件路径|path/i })).not.toBeInTheDocument();
});

test.each([
  ["Windows", "history failed: C:\\Users\\demo\\private\\repo\\.session_store.json"],
  ["POSIX", "history failed: /Users/demo/private/repo/.session_store.json:12"],
  ["relative", "history failed: ../private/repo/file.py:8"],
])("shows degraded reason without raw %s paths", (_label, degradedReason) => {
  renderSoloWorkbench(new MockWebBotClient(), <div>chat</div>, "main", {
    degraded: true,
    degradedReason,
  });

  const sanitized = screen.getByText("会话历史降级，详情见后端诊断");
  expect(sanitized).toBeInTheDocument();
  expect(sanitized).toHaveAttribute("title", "会话历史降级，详情见后端诊断");
  expect([...document.querySelectorAll("[title]")].map((node) => node.getAttribute("title") || "").join("\n")).not.toContain("private");
  expect(document.body).not.toHaveTextContent(".session_store.json");
});

test("solo chat forces native_agent send for a mixed-mode bot", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "mixed",
    botMode: "cli",
    cliType: "codex",
    cliPath: "codex",
    workingDir: "C:\\workspace\\mixed",
    avatarName: "avatar_01.png",
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "cli",
    nativeAgent: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      piAgent: "reviewer",
    },
  });
  const sendMessage = vi.spyOn(client, "sendMessage");

  renderSoloWorkbench(client, (
    <ChatScreen
      botAlias="mixed"
      client={client}
      embedded
      forcedExecutionMode="native_agent"
    />
  ), "mixed");

  await user.type(await screen.findByPlaceholderText("输入消息"), "hello");
  await user.click(screen.getByLabelText("发送"));

  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalled();
  });
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ executionMode: "native_agent" });
});
