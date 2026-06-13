import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { NativeAgentTranscript } from "../components/NativeAgentTranscript";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ChatMessage, FileReadResult } from "../services/types";
import { FILE_PREVIEW_FULL_READ_LIMIT_BYTES } from "../utils/filePreview";
import { SoloWorkbench } from "../workbench/SoloWorkbench";
import type { SoloSessionSnapshot } from "../workbench/soloTypes";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const snapshot: SoloSessionSnapshot = {
  botAlias: "main",
  agentId: "main",
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

function buildFileResult(content: string, overrides: Partial<FileReadResult> = {}): FileReadResult {
  return {
    content,
    mode: "head",
    fileSizeBytes: content.length,
    isFullContent: true,
    ...overrides,
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

function nativeTurn(turnId: string, linearIndex: number, head: string, createdAt: string): ChatMessage {
  return {
    id: `msg-${turnId}`,
    turnId,
    conversationId: "conv-1",
    role: "assistant",
    text: `完成第 ${linearIndex} 轮`,
    createdAt,
    state: "done",
    meta: {
      workspaceHistoryHead: head,
      linearIndex,
      rollbackSupported: true,
    },
  };
}

function userTurn(text: string, createdAt: string): ChatMessage {
  return {
    id: `user-${createdAt}`,
    conversationId: "conv-1",
    role: "user",
    text,
    createdAt,
    state: "done",
  };
}

test("renders solo layout with session tab and no manual file controls", () => {
  renderSoloWorkbench(new MockWebBotClient(), <div>chat</div>);

  expect(screen.getByTestId("solo-workbench-root")).toBeInTheDocument();
  expect(screen.getByTestId("solo-chat-pane")).toBeInTheDocument();
  expect(screen.getByTestId("solo-tabs-pane")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "会话信息" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tab", { name: "会话变更" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Git" })).not.toBeInTheDocument();
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

test("auto-loads full html preview for readonly solo tabs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFile = vi.spyOn(client, "readFile").mockResolvedValue(
    buildFileResult("<html><body>partial</body></html>", {
      isFullContent: false,
      fileSizeBytes: 256,
    }),
  );
  const readFileFull = vi.spyOn(client, "readFileFull").mockResolvedValue(
    buildFileResult("<html><body><h1>Full report</h1></body></html>", {
      mode: "cat",
      isFullContent: true,
      fileSizeBytes: 512,
    }),
  );

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <button type="button" onClick={() => requestPreview("report.html")}>打开 report.html</button>
  ));

  await user.click(screen.getByRole("button", { name: "打开 report.html" }));

  await waitFor(() => {
    expect(readFile).toHaveBeenCalledWith("main", "report.html");
    expect(readFileFull).toHaveBeenCalledWith("main", "report.html");
  });
  expect(document.querySelector("iframe[title='report.html']")).toBeInTheDocument();
  expect(screen.getByText("已加载 HTML 预览")).toBeInTheDocument();
});

test("readonly solo preview can load full content for partial files", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "readFile").mockResolvedValue(
    buildFileResult("预览片段", {
      isFullContent: false,
      fileSizeBytes: 256,
    }),
  );
  const readFileFull = vi.spyOn(client, "readFileFull").mockResolvedValue(
    buildFileResult("# Full README", {
      mode: "cat",
      isFullContent: true,
      fileSizeBytes: 512,
    }),
  );

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <button type="button" onClick={() => requestPreview("README.md")}>打开 README.md</button>
  ));

  await user.click(screen.getByRole("button", { name: "打开 README.md" }));

  expect(await screen.findByText("预览片段")).toBeInTheDocument();
  expect(readFileFull).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "全文读取" }));

  await waitFor(() => {
    expect(readFileFull).toHaveBeenCalledWith("main", "README.md");
  });
  expect(await screen.findByRole("heading", { name: "Full README" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
});

test("readonly solo preview hides full read action for oversized files", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFileFull = vi.spyOn(client, "readFileFull");
  vi.spyOn(client, "readFile").mockResolvedValue(
    buildFileResult("仅预览", {
      isFullContent: false,
      fileSizeBytes: FILE_PREVIEW_FULL_READ_LIMIT_BYTES + 1,
    }),
  );

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <button type="button" onClick={() => requestPreview("big.log")}>打开 big.log</button>
  ));

  await user.click(screen.getByRole("button", { name: "打开 big.log" }));

  expect(await screen.findByText("仅预览")).toBeInTheDocument();
  expect(screen.getByText("文件超过1MB，请下载后读取全文")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
  expect(readFileFull).not.toHaveBeenCalled();
});

test("native transcript file link opens a readonly solo preview tab", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const readFile = vi.spyOn(client, "readFile");

  renderSoloWorkbench(client, ({ requestPreview }) => (
    <NativeAgentTranscript
      entries={[]}
      resultText="[README](README.md)"
      state="done"
      onFileLinkClick={requestPreview}
    />
  ));

  await user.click(screen.getByRole("link", { name: "README" }));

  await waitFor(() => {
    expect(readFile).toHaveBeenCalledTimes(1);
    expect(readFile).toHaveBeenCalledWith("main", "README.md");
  });
  expect(await screen.findByRole("tab", { name: "README.md" })).toBeInTheDocument();
  expect(await screen.findByText(/Mock full content for README\.md/)).toBeInTheDocument();
});

test("opens readonly session diff tab from session changes", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "listMessages").mockResolvedValue([
    nativeTurn("turn-1", 1, "head-1", "2026-06-12T10:00:00Z"),
    nativeTurn("turn-2", 2, "head-2", "2026-06-12T10:01:00Z"),
  ]);
  const getChanges = vi.spyOn(client, "getNativeAgentHistoryChanges").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-2",
    linearIndex: 2,
    baseHead: "head-1",
    head: "head-2",
    files: [
      { path: "bot/web/server.py", oldPath: "", status: "modified", additions: 1, deletions: 1, binary: false },
    ],
  });
  const getDiff = vi.spyOn(client, "getNativeAgentHistoryDiff").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-2",
    path: "bot/web/server.py",
    oldPath: "",
    status: "modified",
    diff: "diff --git a/bot/web/server.py b/bot/web/server.py\n@@ -1 +1 @@\n-old\n+new",
  });

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "会话变更" }));
  await user.click(await screen.findByLabelText("打开 bot/web/server.py diff"));

  expect(getChanges).toHaveBeenCalledWith("main", { conversationId: "conv-1", turnId: "turn-2" });
  expect(getDiff).toHaveBeenCalledWith("main", { conversationId: "conv-1", turnId: "turn-2", path: "bot/web/server.py" });
  expect(await screen.findByRole("tab", { name: "server.py.diff" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText(/\+new/)).toBeInTheDocument();
  expect(screen.queryByLabelText("文件内容")).not.toBeInTheDocument();
});

test("passes child agent scope to session changes APIs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const listMessages = vi.spyOn(client, "listMessages").mockResolvedValue([
    nativeTurn("turn-2", 2, "head-2", "2026-06-12T10:01:00Z"),
  ]);
  const getChanges = vi.spyOn(client, "getNativeAgentHistoryChanges").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-2",
    linearIndex: 2,
    baseHead: "head-1",
    head: "head-2",
    files: [
      { path: "bot/web/server.py", oldPath: "", status: "modified", additions: 1, deletions: 0, binary: false },
    ],
  });
  const getDiff = vi.spyOn(client, "getNativeAgentHistoryDiff").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-2",
    path: "bot/web/server.py",
    oldPath: "",
    status: "modified",
    diff: "diff\n+new",
  });

  renderSoloWorkbench(client, <div>chat</div>, "main", { agentId: "reviewer" });

  await user.click(screen.getByRole("tab", { name: "会话变更" }));
  await user.click(await screen.findByLabelText("打开 bot/web/server.py diff"));

  expect(listMessages).toHaveBeenCalledWith("main", { executionMode: "native_agent", agentId: "reviewer" });
  expect(getChanges).toHaveBeenCalledWith("main", { conversationId: "conv-1", turnId: "turn-2", agentId: "reviewer" });
  expect(getDiff).toHaveBeenCalledWith("main", { conversationId: "conv-1", turnId: "turn-2", path: "bot/web/server.py", agentId: "reviewer" });
});

test("session change summaries hide attachment paths from user messages", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "listMessages").mockResolvedValue([
    userTurn("请处理附件\n\n附件路径为：C:\\Users\\demo\\private\\secret.txt", "2026-06-12T09:59:59Z"),
    nativeTurn("turn-1", 1, "head-1", "2026-06-12T10:00:00Z"),
  ]);
  vi.spyOn(client, "getNativeAgentHistoryChanges").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-1",
    linearIndex: 1,
    baseHead: "",
    head: "head-1",
    files: [
      { path: "smoke/history.txt", oldPath: "", status: "added", additions: 1, deletions: 0, binary: false },
    ],
  });

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "会话变更" }));

  expect(await screen.findByLabelText("选择 请处理附件")).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("private");
  expect(document.body).not.toHaveTextContent("secret.txt");
});

test("keeps session diff content when switching tabs", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "listMessages").mockResolvedValue([
    nativeTurn("turn-2", 2, "head-2", "2026-06-12T10:01:00Z"),
  ]);
  vi.spyOn(client, "getNativeAgentHistoryChanges").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-2",
    linearIndex: 2,
    baseHead: "head-1",
    head: "head-2",
    files: [
      { path: "bot/web/server.py", oldPath: "", status: "modified", additions: 1, deletions: 0, binary: false },
    ],
  });
  const getDiff = vi.spyOn(client, "getNativeAgentHistoryDiff").mockResolvedValue({
    conversationId: "conv-1",
    turnId: "turn-2",
    path: "bot/web/server.py",
    oldPath: "",
    status: "modified",
    diff: "persistent diff\n+new",
  });

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "会话变更" }));
  await user.click(await screen.findByLabelText("打开 bot/web/server.py diff"));
  expect(await screen.findByText(/persistent diff/)).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "会话信息" }));
  await user.click(screen.getByRole("tab", { name: "server.py.diff" }));

  expect(screen.getByText(/persistent diff/)).toBeInTheDocument();
  expect(getDiff).toHaveBeenCalledTimes(1);
});

test("rolls back to a previous session turn and refreshes the active chain", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  vi.spyOn(client, "listMessages")
    .mockResolvedValueOnce([
      userTurn("初始化历史文件", "2026-06-12T09:59:59Z"),
      nativeTurn("turn-1", 1, "head-1", "2026-06-12T10:00:00Z"),
      userTurn("添加新文件", "2026-06-12T10:00:30Z"),
      nativeTurn("turn-2", 2, "head-2", "2026-06-12T10:01:00Z"),
    ])
    .mockResolvedValueOnce([
      userTurn("初始化历史文件", "2026-06-12T09:59:59Z"),
      nativeTurn("turn-1", 1, "head-1", "2026-06-12T10:00:00Z"),
    ]);
  vi.spyOn(client, "getNativeAgentHistoryChanges").mockImplementation(async (_botAlias, input) => ({
    conversationId: input.conversationId,
    turnId: input.turnId,
    linearIndex: input.turnId === "turn-1" ? 1 : 2,
    baseHead: input.turnId === "turn-1" ? "" : "head-1",
    head: input.turnId === "turn-1" ? "head-1" : "head-2",
    files: [
      { path: input.turnId === "turn-1" ? "smoke/history.txt" : "smoke/new.txt", oldPath: "", status: "added", additions: 1, deletions: 0, binary: false },
    ],
  }));
  const rollback = vi.spyOn(client, "rollbackNativeAgentHistory").mockResolvedValue({
    conversationId: "conv-1",
    currentTurnId: "turn-1",
    rollbackSupported: false,
    message: "已撤回到所选会话点；该操作不可撤销",
  });

  renderSoloWorkbench(client, <div>chat</div>);

  await user.click(screen.getByRole("tab", { name: "会话变更" }));
  await user.click(await screen.findByLabelText("选择 初始化历史文件"));
  expect(screen.getByText("初始化历史文件")).toBeInTheDocument();
  expect(screen.queryByText("第 1 轮")).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "撤回到此轮" }));
  const dialog = await screen.findByRole("dialog", { name: "确认撤回" });
  expect(dialog).toBeInTheDocument();
  expect(dialog.parentElement?.parentElement).toBe(document.body);
  expect(dialog.parentElement).toHaveClass("z-[1000]");
  expect(screen.getByText("会丢弃该点之后的会话和工作区改动，不可撤销")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "确认撤回" }));

  expect(rollback).toHaveBeenCalledWith("main", { conversationId: "conv-1", targetTurnId: "turn-1" });
  await waitFor(() => {
    expect(screen.queryByLabelText("选择 添加新文件")).not.toBeInTheDocument();
  });
  expect(screen.queryByRole("button", { name: "撤回到此轮" })).not.toBeInTheDocument();
  expect(screen.getByText("已撤回到所选会话点；该操作不可撤销")).toBeInTheDocument();
});

test("syncs solo chat after rolling back from session changes", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let rolledBack = false;
  const messagesBefore = [
    userTurn("初始化历史文件", "2026-06-12T09:59:59Z"),
    nativeTurn("turn-1", 1, "head-1", "2026-06-12T10:00:00Z"),
    userTurn("添加新文件", "2026-06-12T10:00:30Z"),
    nativeTurn("turn-2", 2, "head-2", "2026-06-12T10:01:00Z"),
  ];
  const messagesAfter = messagesBefore.slice(0, 2);
  vi.spyOn(client, "getBotOverview").mockResolvedValue({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace\\main",
    isProcessing: false,
    supportedExecutionModes: ["native_agent"],
    defaultExecutionMode: "native_agent",
    executionMode: "native_agent",
  });
  vi.spyOn(client, "listMessages").mockImplementation(async () => (
    rolledBack ? messagesAfter : messagesBefore
  ));
  vi.spyOn(client, "listConversations").mockImplementation(async () => ({
    activeConversationId: "conv-1",
    items: [{
      id: "conv-1",
      title: "当前会话",
      lastMessagePreview: "",
      messageCount: rolledBack ? 2 : 4,
      pinned: false,
      active: true,
      status: "active",
      botAlias: "main",
      botMode: "cli",
      cliType: "codex",
      workingDir: "C:\\workspace\\main",
      createdAt: "2026-06-12T10:00:00Z",
      updatedAt: "2026-06-12T10:01:00Z",
      workspaceHistoryHead: rolledBack ? "head-1" : "head-2",
      linearIndex: rolledBack ? 1 : 2,
      rollbackSupported: true,
    }],
  }));
  vi.spyOn(client, "getNativeAgentHistoryChanges").mockImplementation(async (_botAlias, input) => ({
    conversationId: input.conversationId,
    turnId: input.turnId,
    linearIndex: input.turnId === "turn-1" ? 1 : 2,
    baseHead: input.turnId === "turn-1" ? "" : "head-1",
    head: input.turnId === "turn-1" ? "head-1" : "head-2",
    files: [
      { path: input.turnId === "turn-1" ? "smoke/history.txt" : "smoke/new.txt", oldPath: "", status: "added", additions: 1, deletions: 0, binary: false },
    ],
  }));
  const rollback = vi.spyOn(client, "rollbackNativeAgentHistory").mockImplementation(async () => {
    rolledBack = true;
    return {
      conversationId: "conv-1",
      currentTurnId: "turn-1",
      rollbackSupported: false,
      message: "已撤回到所选会话点",
    };
  });

  function Harness() {
    const [revision, setRevision] = useState(0);
    const bumpRevision = () => setRevision((value) => value + 1);
    return (
      <SoloWorkbench
        botAlias="main"
        client={client}
        workspaceName="main"
        viewMode="desktop"
        chatPaneContent={(
          <ChatScreen
            botAlias="main"
            client={client}
            embedded
            forcedExecutionMode="native_agent"
            soloMode
            soloHistoryRevision={revision}
            onSoloHistoryRollback={bumpRevision}
          />
        )}
        sessionSnapshot={{ ...snapshot, linearIndex: 2, workspaceHistoryHead: "head-2" }}
        soloHistoryRevision={revision}
        productMode="solo"
        soloAvailable
        onProductModeChange={() => {}}
        onSoloHistoryRollback={bumpRevision}
        onViewModeChange={() => {}}
        onOpenBotSwitcher={() => {}}
        onLogout={() => {}}
      />
    );
  }

  render(<Harness />);

  expect(await screen.findByText("添加新文件")).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "会话变更" }));
  await user.click(await screen.findByLabelText("选择 初始化历史文件"));
  await user.click(await screen.findByRole("button", { name: "撤回到此轮" }));
  await user.click(await screen.findByRole("button", { name: "确认撤回" }));

  expect(rollback).toHaveBeenCalledWith("main", { conversationId: "conv-1", targetTurnId: "turn-1" });
  await waitFor(() => {
    expect(screen.queryByText("添加新文件")).not.toBeInTheDocument();
  });
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
