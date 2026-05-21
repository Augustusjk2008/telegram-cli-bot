import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ChatTraceDetails, CliParamsPayload, ClusterTaskStatus, ConversationListResult, ConversationSelectResult, GitActionResult, GitDiffPayload, GitOverview } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

const MODEL_OPTIONS = ["gpt-5.5", "gpt-5.4", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6", "none"];

function modelCliParams(model: string | null): CliParamsPayload {
  return {
    cliType: "codex",
    params: { model },
    defaults: { model: "gpt-5.4" },
    schema: {
      model: {
        type: "string",
        description: "模型选择",
        nullable: true,
        enum: MODEL_OPTIONS,
      },
    },
  };
}

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    login: async () => ({
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      canExec: true,
      canAdmin: true,
    }),
    listBots: async () => [],
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }),
    listMessages: async () => [],
    listConversations: async (): Promise<ConversationListResult> => ({
      activeConversationId: "",
      items: [],
    }),
    createConversation: async (): Promise<ConversationSelectResult> => ({
      conversation: {
        id: "conv-new",
        title: "新会话",
        lastMessagePreview: "",
        messageCount: 0,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        botMode: "cli",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
      messages: [],
    }),
    selectConversation: async (): Promise<ConversationSelectResult> => ({
      conversation: {
        id: "conv-selected",
        title: "旧会话",
        lastMessagePreview: "",
        messageCount: 0,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        botMode: "cli",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
      messages: [],
    }),
    getMessageTrace: async (): Promise<ChatTraceDetails> => ({
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    }),
    sendMessage: async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("Mock response");
      return {
        id: "assistant-1",
        role: "assistant",
        text: "Mock response",
        createdAt: new Date().toISOString(),
        state: "done",
      };
    },
    getCurrentPath: async () => "C:\\workspace",
    listFiles: async () => ({
      workingDir: "C:\\workspace",
      entries: [],
    }),
    changeDirectory: async () => "C:\\workspace",
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
      path: "tracked.txt",
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
    updateBotWorkdir: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      lastActiveText: "运行中",
    }),
    getCliParams: async () => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    updateCliParam: async () => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    resetCliParams: async () => ({
      cliType: "codex",
      params: {},
      defaults: {},
      schema: {},
    }),
    getTunnelStatus: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    startTunnel: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    stopTunnel: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    restartTunnel: async () => ({
      mode: "disabled",
      status: "stopped",
      source: "disabled",
      publicUrl: "",
      localUrl: "",
      lastError: "",
      pid: null,
    }),
    ...overrides,
  });
}

function mockClipboardWrite() {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  Object.defineProperty(globalThis.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

test("shows model selector in chat action bar and saves selected model", async () => {
  const updateCliParam = vi.fn(async (_botAlias: string, _key: string, value: unknown) => modelCliParams(String(value)));
  const user = userEvent.setup();
  const client = createClient({
    getCliParams: async () => modelCliParams("gpt-5.5"),
    updateCliParam,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const selector = await screen.findByLabelText("模型");
  expect(selector).toHaveValue("gpt-5.5");

  await user.selectOptions(selector, "gpt-5.4");

  expect(updateCliParam).toHaveBeenCalledWith("main", "model", "gpt-5.4", "codex");
  expect(selector).toHaveValue("gpt-5.4");
});

test("shows none for null model and disables model param with none", async () => {
  const updateCliParam = vi.fn(async (_botAlias: string, _key: string, value: unknown) => (
    modelCliParams(value === "none" ? null : String(value))
  ));
  const user = userEvent.setup();
  const client = createClient({
    getCliParams: async () => modelCliParams(null),
    updateCliParam,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const selector = await screen.findByLabelText("模型");
  expect(selector).toHaveValue("none");

  await user.selectOptions(selector, "gpt-5.4");
  expect(updateCliParam).toHaveBeenCalledWith("main", "model", "gpt-5.4", "codex");

  await user.selectOptions(selector, "none");
  expect(updateCliParam).toHaveBeenLastCalledWith("main", "model", "none", "codex");
  expect(selector).toHaveValue("none");
});

test("shows a user message after sending text", async () => {
  const client = createClient({
    sendMessage: async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("已收到");
      return {
        id: "assistant-immediate",
        role: "assistant",
        text: "已收到",
        elapsedSeconds: 3,
        createdAt: new Date().toISOString(),
        state: "done",
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "修一下这个 bug");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(screen.getByTestId("chat-composer-root")).toHaveAttribute("data-pulse", "true");
  expect(await screen.findByText("修一下这个 bug")).toBeInTheDocument();
  expect(screen.queryByText("用时 3 秒")).not.toBeInTheDocument();
});

test("uploads chat attachments and appends absolute paths to the sent message", async () => {
  const user = userEvent.setup();
  const sendSpy = vi.fn(
    async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("已收到");
      return {
        id: "assistant-attachment",
        role: "assistant" as const,
        text: "已收到",
        createdAt: new Date().toISOString(),
        state: "done" as const,
      };
    },
  );
  const uploadChatAttachment = vi.fn(async (_botAlias: string, file: File) => ({
    filename: file.name,
    savedPath: `C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\${file.name}`,
    size: file.size,
  }));
  const client = createClient({
    sendMessage: sendSpy as never,
    uploadChatAttachment: uploadChatAttachment as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  const attachmentInput = screen.getByTestId("chat-attachment-input");
  const file = new File(["hello"], "report.txt", { type: "text/plain" });
  await user.upload(attachmentInput, file);

  await waitFor(() => {
    expect(uploadChatAttachment).toHaveBeenCalledTimes(1);
  });
  expect(await screen.findByRole("button", { name: "移除附件 report.txt" })).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "请分析这个附件");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => {
    expect(sendSpy).toHaveBeenCalledWith(
      "main",
      "请分析这个附件\n\n附件路径为：C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  expect(await screen.findByText("report.txt")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "删除附件文件 report.txt" })).toBeInTheDocument();
  expect(screen.queryByText((content) => (
    content.includes("附件路径为：")
    && content.includes("report.txt")
  ))).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "移除附件 report.txt" })).not.toBeInTheDocument();
});

test("deletes attachment files from user message pills without exposing injected prompt text", async () => {
  const user = userEvent.setup();
  const deleteSpy = vi.fn(async (_botAlias: string, savedPath: string) => ({
    filename: "report.txt",
    savedPath,
    existed: true,
    deleted: true,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-attachment-1",
        role: "user",
        text: "请参考附件\n\n附件路径为：C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
    deleteChatAttachment: deleteSpy as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("请参考附件")).toBeInTheDocument();
  expect(await screen.findByText("report.txt")).toBeInTheDocument();
  expect(screen.queryByText((content) => content.includes("附件路径为："))).not.toBeInTheDocument();

  await user.click(await screen.findByRole("button", { name: "删除附件文件 report.txt" }));

  await waitFor(() => {
    expect(deleteSpy).toHaveBeenCalledWith(
      "main",
      "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
    );
  });
  expect(await screen.findByText("已删除")).toBeInTheDocument();
});

test("submits the chat composer when pressing Shift+Enter", async () => {
  const sendSpy = vi.fn(
    async (_botAlias: string, _text: string, onChunk: (chunk: string) => void) => {
      onChunk("已通过快捷键发送");
      return {
        id: "assistant-shift-enter",
        role: "assistant" as const,
        text: "已通过快捷键发送",
        createdAt: new Date().toISOString(),
        state: "done" as const,
      };
    },
  );
  const client = createClient({
    sendMessage: sendSpy,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  const composer = await screen.findByPlaceholderText("输入消息");
  fireEvent.change(composer, { target: { value: "Shift+Enter 发送" } });
  fireEvent.keyDown(composer, { key: "Enter", code: "Enter", shiftKey: true });

  await waitFor(() => {
    expect(sendSpy).toHaveBeenCalledWith(
      "main",
      "Shift+Enter 发送",
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });

  expect(await screen.findByText("Shift+Enter 发送")).toBeInTheDocument();
});

test("shows streaming state before assistant message completes", async () => {
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-later",
            role: "assistant",
            text: "稍后完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(screen.getByText("正在输出...")).toBeInTheDocument();
  expect(await screen.findByText("稍后完成")).toBeInTheDocument();
});

test("treats inactive history streaming rows as completed", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      historyCount: 2,
    }),
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-22T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "最终回答",
        createdAt: "2026-04-22T10:00:01",
        state: "streaming",
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最终回答")).toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出...")).not.toBeInTheDocument();
});

test("keeps history streaming rows active while overview is processing", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "busy",
      workingDir: "C:\\workspace",
      isProcessing: true,
      historyCount: 2,
    }),
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-22T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "处理中预览",
        createdAt: "2026-04-22T10:00:01",
        state: "streaming",
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("处理中预览")).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();
});

test("shows cluster task summary after main reply finishes", async () => {
  let pollCount = 0;
  const taskStatuses: ClusterTaskStatus[] = [
    {
      tasks: [
        {
          taskId: "clt_1",
          agentId: "tester",
          status: "running",
          modelTier: "low",
          allowWrite: false,
          createdAt: "2026-05-06T10:00:00+08:00",
          startedAt: "2026-05-06T10:00:01+08:00",
          completedAt: "",
          error: "",
        },
      ],
      queuedCount: 0,
      runningCount: 1,
      completedCount: 0,
      failedCount: 0,
      pendingCount: 1,
    },
    {
      tasks: [
        {
          taskId: "clt_1",
          agentId: "tester",
          status: "completed",
          modelTier: "low",
          allowWrite: false,
          createdAt: "2026-05-06T10:00:00+08:00",
          startedAt: "2026-05-06T10:00:01+08:00",
          completedAt: "2026-05-06T10:00:02+08:00",
          output: "3 passed",
          error: "",
        },
      ],
      queuedCount: 0,
      runningCount: 0,
      completedCount: 1,
      failedCount: 0,
      pendingCount: 0,
    },
  ];
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "gpt-low", medium: "gpt-mid", high: "gpt-high" },
      },
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "tester", name: "测试专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    getClusterTaskStatus: vi.fn(async () => taskStatuses[Math.min(pollCount++, taskStatuses.length - 1)]),
    sendMessage: async (
      _botAlias: string,
      _text: string,
      onChunk: (chunk: string) => void,
      onStatus?: (status: { clusterRunId?: string }) => void,
    ) => {
      onStatus?.({ clusterRunId: "clr_1" });
      onChunk("主回复");
      return {
        id: "assistant-cluster",
        role: "assistant",
        text: "主回复",
        createdAt: new Date().toISOString(),
        state: "done",
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const user = userEvent.setup();
  expect(await screen.findByPlaceholderText("@ 可指定智能体集群")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("@ 可指定智能体集群"), "跑测试");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const panelTitle = await screen.findByText("智能体集群任务");
  const panel = panelTitle.closest("section") as HTMLElement | null;
  expect(panel).not.toBeNull();
  expect(await screen.findByText("已完成")).toBeInTheDocument();
  expect(screen.queryByText("3 passed")).not.toBeInTheDocument();
  expect(within(panel as HTMLElement).getByText("@tester")).toBeInTheDocument();
  expect(within(panel as HTMLElement).getByText("测试专家")).toBeInTheDocument();
  await waitFor(() => expect(client.getClusterTaskStatus).toHaveBeenCalledWith("main", "clr_1"));
});

test("restores active cluster tasks from bot overview", async () => {
  const getClusterTaskStatus = vi.fn(async (): Promise<ClusterTaskStatus> => ({
    tasks: [
      {
        taskId: "clt_restore",
        agentId: "tester",
        status: "running",
        modelTier: "medium",
        allowWrite: false,
        createdAt: "2026-05-06T10:00:00+08:00",
        startedAt: "2026-05-06T10:00:01+08:00",
        completedAt: "",
        error: "",
      },
    ],
    queuedCount: 0,
    runningCount: 1,
    completedCount: 0,
    failedCount: 0,
    pendingCount: 1,
  }));
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "", medium: "", high: "" },
      },
      activeClusterRun: {
        runId: "clr_restore",
        status: "completed",
        tasks: {
          tasks: [
            {
              taskId: "clt_restore",
              agentId: "tester",
              status: "running",
              modelTier: "medium",
              allowWrite: false,
              createdAt: "2026-05-06T10:00:00+08:00",
              startedAt: "2026-05-06T10:00:01+08:00",
              completedAt: "",
              error: "",
            },
          ],
          queuedCount: 0,
          runningCount: 1,
          completedCount: 0,
          failedCount: 0,
          pendingCount: 1,
        },
      },
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "tester", name: "测试专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    getClusterTaskStatus,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const panelTitle = await screen.findByText("智能体集群任务");
  const panel = panelTitle.closest("section") as HTMLElement | null;
  expect(panel).not.toBeNull();
  expect(within(panel as HTMLElement).getByText("@tester")).toBeInTheDocument();
  expect(within(panel as HTMLElement).getByText("测试专家")).toBeInTheDocument();
  expect(screen.getByText("运行中")).toBeInTheDocument();
  await waitFor(() => expect(getClusterTaskStatus).toHaveBeenCalledWith("main", "clr_restore"));
});

test("streamed trace count grows beyond the first process event", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: async (
      _botAlias: string,
      _text: string,
      _onChunk: (chunk: string) => void,
      _onStatus,
      onTrace,
    ) => {
      onTrace?.({ kind: "commentary", summary: "第一条过程" } as never);
      onTrace?.({ kind: "commentary", summary: "第二条过程" } as never);
      return {
        id: "assistant-final",
        role: "assistant",
        text: "最终结果",
        createdAt: new Date().toISOString(),
        state: "done",
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "执行");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("最终结果")).toBeInTheDocument();
  expect(screen.getByText("2 条过程")).toBeInTheDocument();
});

test("copies final answer from collapsed trace header without expanding details", async () => {
  const user = userEvent.setup();
  const writeText = mockClipboardWrite();
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "最终回答内容",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          trace: [{ kind: "commentary", summary: "过程内容" }],
          traceCount: 1,
          toolCallCount: 0,
          processCount: 1,
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最终回答内容")).toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "展开过程详情" });
  await user.click(screen.getByRole("button", { name: "复制最终回答" }));

  await waitFor(() => expect(writeText).toHaveBeenCalledWith("最终回答内容"));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("过程内容")).not.toBeInTheDocument();
});

test("copy final answer button shows success feedback and locks briefly", async () => {
  const writeText = mockClipboardWrite();
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "最终回答内容",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          trace: [{ kind: "commentary", summary: "过程内容" }],
          traceCount: 1,
          toolCallCount: 0,
          processCount: 1,
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最终回答内容")).toBeInTheDocument();
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "复制最终回答" }));

  await act(async () => {
    await Promise.resolve();
  });
  expect(writeText).toHaveBeenCalledWith("最终回答内容");
  const copiedButton = screen.getByRole("button", { name: "已复制最终回答" });
  expect(copiedButton).toBeDisabled();

  fireEvent.click(copiedButton);
  expect(writeText).toHaveBeenCalledTimes(1);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });

  expect(screen.getByRole("button", { name: "复制最终回答" })).toBeEnabled();
});

test("shows streamed commentary trace in the assistant bubble before final text", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: async (
      _botAlias: string,
      _text: string,
      _onChunk: (chunk: string) => void,
      _onStatus,
      onTrace,
    ) => new Promise<ChatMessage>((resolve) => {
      onTrace?.({ kind: "commentary", summary: "正在分析需求" } as never);
      window.setTimeout(() => {
        resolve({
          id: "assistant-final",
          role: "assistant",
          text: "最终结果",
          createdAt: new Date().toISOString(),
          state: "done",
        });
      }, 50);
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "执行");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("正在分析需求")).toBeInTheDocument();
  expect(await screen.findByText("最终结果")).toBeInTheDocument();
});

test("expanding a partially loaded trace fetches full trace details", async () => {
  const user = userEvent.setup();
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      { kind: "commentary", summary: "第一条过程" },
      { kind: "commentary", summary: "第二条过程" },
      { kind: "commentary", summary: "第三条过程" },
    ],
    traceCount: 3,
    toolCallCount: 0,
    processCount: 3,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "最终结果",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          trace: [{ kind: "commentary", summary: "第一条过程" }],
          traceCount: 3,
          toolCallCount: 0,
          processCount: 3,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最终结果")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "展开过程详情" }));

  expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-1");
  expect(await screen.findByText("第二条过程")).toBeInTheDocument();
  expect(screen.getByText("第三条过程")).toBeInTheDocument();
});

test("lazy-loads trace details and groups tool call/result into one trace card", async () => {
  const user = userEvent.setup();
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      {
        kind: "commentary",
        summary: "我先检查目录结构。",
      },
      {
        kind: "tool_call",
        title: "shell_command",
        toolName: "shell_command",
        callId: "call_1",
        summary: "Get-Content -Path todo.txt",
        payload: {
          arguments: {
            command: "Get-Content -Path todo.txt",
          },
        },
      },
      {
        kind: "tool_result",
        callId: "call_1",
        summary: "Exit code: 1\nWall time: 1.3 seconds\nOutput:\nboom",
        payload: {
          output: "Exit code: 1\nWall time: 1.3 seconds\nOutput:\nboom",
        },
      },
      {
        kind: "commentary",
        summary: "目录已读取完成。",
      },
    ],
    traceCount: 4,
    toolCallCount: 1,
    processCount: 2,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "列出当前目录",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "目录已读取完成。",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          traceCount: 4,
          toolCallCount: 1,
          processCount: 2,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("目录已读取完成。")).toBeInTheDocument();
  expect(getMessageTrace).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "展开过程详情" }));

  expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-1");
  expect(await screen.findByText("我先检查目录结构。")).toBeInTheDocument();
  expect(screen.getByText("工具调用 1")).toBeInTheDocument();
  expect(screen.getByText("Get-Content -Path todo.txt")).toBeInTheDocument();
  expect(screen.getByText("返回")).toBeInTheDocument();
  expect(screen.getByText("Exit 1")).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes("Wall time: 1.3 seconds") && content.includes("Output:"))).toBeInTheDocument();

  const panel = screen.getByTestId("chat-trace-panel-assistant-1");
  const traceItems = Array.from(panel.querySelectorAll("[data-trace-seq]"));
  expect(traceItems).toHaveLength(3);
  expect(traceItems[0]?.textContent).toContain("我先检查目录结构。");
  expect(traceItems[1]?.textContent).toContain("工具调用 1");
  expect(traceItems[1]?.textContent).toContain("Exit 1");
  expect(traceItems[2]?.textContent).toContain("目录已读取完成。");
});

test("shows a streaming placeholder before the first assistant chunk arrives", async () => {
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-final",
            role: "assistant",
            text: "# 最终结果\n- 已完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("正在输出...")).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "最终结果" })).toBeInTheDocument();
});

test("kill button is disabled while idle and highlighted while streaming", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-later",
            role: "assistant",
            text: "稍后完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} isVisible />);

  const killButton = await screen.findByRole("button", { name: "终止任务" });
  expect(killButton).toBeDisabled();

  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByRole("button", { name: "终止任务" })).toBeEnabled();
});

test("switching bots resets chat history instead of mixing conversations", async () => {
  const client = createClient({
    listMessages: async (botAlias: string): Promise<ChatMessage[]> => {
      if (botAlias === "main") {
        return [{
          id: "main-1",
          role: "assistant",
          text: "main-history",
          createdAt: new Date().toISOString(),
          state: "done",
        }];
      }
      return [{
        id: "team2-1",
        role: "assistant",
        text: "team2-history",
        createdAt: new Date().toISOString(),
        state: "done",
      }];
    },
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("main-history")).toBeInTheDocument();

  rerender(<ChatScreen botAlias="team2" client={client} />);

  expect(await screen.findByText("team2-history")).toBeInTheDocument();
  expect(screen.queryByText("main-history")).not.toBeInTheDocument();
});

test("switching bots ignores stale streaming completion from the previous bot", async () => {
  const user = userEvent.setup();
  let resolveMainSend: ((message: ChatMessage) => void) | null = null;
  const sendMessage = vi.fn((botAlias: string) => {
    if (botAlias === "main") {
      return new Promise<ChatMessage>((resolve) => {
        resolveMainSend = resolve;
      });
    }
    return Promise.resolve({
      id: `${botAlias}-reply`,
      role: "assistant",
      text: `${botAlias}-reply`,
      createdAt: new Date().toISOString(),
      state: "done" as const,
    });
  });
  const client = createClient({
    listMessages: async (botAlias: string): Promise<ChatMessage[]> => (
      botAlias === "main"
        ? []
        : [{
          id: "team2-1",
          role: "assistant",
          text: "team2-history",
          createdAt: new Date().toISOString(),
          state: "done",
        }]
    ),
    sendMessage: sendMessage as never,
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "main-question");
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("正在输出...")).toBeInTheDocument();

  rerender(<ChatScreen botAlias="team2" client={client} />);
  expect(await screen.findByText("team2-history")).toBeInTheDocument();

  resolveMainSend?.({
    id: "main-final",
    role: "assistant",
    text: "main-final",
    createdAt: new Date().toISOString(),
    state: "done",
  });

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(screen.getByText("team2-history")).toBeInTheDocument();
  expect(screen.queryByText("main-final")).not.toBeInTheDocument();
});

test("chat screen hides agent switcher when there are no child agents", async () => {
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
    ],
  }));
  const client = createClient({ listAgents });

  render(<ChatScreen botAlias="main" client={client} />);

  await waitFor(() => {
    expect(listAgents).toHaveBeenCalledWith("main");
  });
  expect(screen.queryByRole("combobox", { name: "当前 agent" })).not.toBeInTheDocument();
});

test("chat screen shows agent dropdown in non-cluster mode", async () => {
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false },
      { id: "tester", name: "测试专家", systemPrompt: "先跑测试", enabled: true, isMain: false },
    ],
  }));
  const client = createClient({ listAgents });

  render(<ChatScreen botAlias="main" client={client} />);

  const selector = await screen.findByRole("combobox", { name: "当前 agent" });
  expect(selector).toHaveValue("main");
  expect(screen.getByRole("option", { name: "主 agent" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "代码审查" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "测试专家" })).toBeInTheDocument();
});

test("cluster mode shows child agent mention chips", async () => {
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false },
    ],
  }));
  const client = createClient({
    listAgents,
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "", medium: "", high: "" },
      },
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "@reviewer 代码审查" })).toBeInTheDocument();
  expect(await screen.findByRole("combobox", { name: "当前 agent" })).toHaveValue("main");
});

test("chat action bar toggles cluster mode without resetting config", async () => {
  const cluster = {
    enabled: false,
    writePolicy: "main_only" as const,
    conflictPolicy: "warn_only" as const,
    maxParallelAgents: 4,
    defaultTimeoutSeconds: 900,
    modelTiers: { low: "gpt-5.4-mini", medium: "gpt-5.4", high: "gpt-5.5" },
  };
  let savedCluster = cluster;
  const updateClusterConfig = vi.fn(async (_botAlias: string, input) => ({
    cluster: savedCluster = { ...savedCluster, ...input, modelTiers: { ...savedCluster.modelTiers, ...input.modelTiers } },
    status: {
      enabled: Boolean(input.enabled),
      modelTiers: { ...savedCluster.modelTiers, ...input.modelTiers },
      mcp: {
        serverName: "tcb-cluster",
        activeCliType: "codex",
        runtime: { state: "runtime_ready" as const, message: "运行态可用" },
        codex: { state: "runtime_ready" as const, message: "运行态可用" },
        claude: { state: "not_checked" as const, message: "未使用" },
        kimi: { state: "not_checked" as const, message: "未使用" },
      },
      agents: [],
    },
  }));
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      botMode: "cli",
      isProcessing: false,
      cluster,
    }),
    updateClusterConfig,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const toggle = await screen.findByRole("button", { name: "开启集群模式" });
  expect(toggle).toHaveTextContent("集群关");

  await userEvent.click(toggle);

  await waitFor(() => expect(updateClusterConfig).toHaveBeenCalledWith("main", {
    enabled: true,
    writePolicy: "main_only",
    conflictPolicy: "warn_only",
    maxParallelAgents: 4,
    defaultTimeoutSeconds: 900,
    modelTiers: { low: "gpt-5.4-mini", medium: "gpt-5.4", high: "gpt-5.5" },
  }));
  const closeToggle = await screen.findByRole("button", { name: "关闭集群模式" });
  expect(closeToggle).toHaveTextContent("集群开");

  await userEvent.click(closeToggle);

  await waitFor(() => expect(updateClusterConfig).toHaveBeenLastCalledWith("main", {
    enabled: false,
    writePolicy: "main_only",
    conflictPolicy: "warn_only",
    maxParallelAgents: 4,
    defaultTimeoutSeconds: 900,
    modelTiers: { low: "gpt-5.4-mini", medium: "gpt-5.4", high: "gpt-5.5" },
  }));
  expect(await screen.findByRole("button", { name: "开启集群模式" })).toHaveTextContent("集群关");
});

test("chat message motion keeps assistant text and trace controls accessible", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-trace-1",
        role: "assistant",
        text: "完成",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          traceCount: 2,
          toolCallCount: 0,
          processCount: 2,
          trace: [
            { kind: "commentary", summary: "读取文件", rawType: "commentary" },
            { kind: "commentary", summary: "运行测试", rawType: "commentary" },
          ],
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} allowTrace />);

  expect(await screen.findByText("完成")).toBeInTheDocument();
  const toggle = await screen.findByRole("button", { name: "展开过程详情" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");

  await userEvent.click(toggle);
  await screen.findByText("读取文件");
  const traceRows = screen.getAllByText(/读取文件|运行测试/).map((item) => item.textContent);
  expect(traceRows).toEqual(["读取文件", "运行测试"]);
  expect(screen.getByRole("button", { name: "收起过程详情" })).toHaveAttribute("aria-expanded", "true");
});

test("cluster mode keeps a previously active child agent as read-only", async () => {
  window.localStorage.setItem("tcb.activeAgent.main", "reviewer");
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false },
    ],
  }));
  const listMessages = vi.fn(async (_botAlias: string, options?: { agentId?: string }): Promise<ChatMessage[]> => {
    if (options?.agentId === "reviewer") {
      return [{
        id: "reviewer-1",
        role: "assistant",
        text: "reviewer-history",
        createdAt: new Date().toISOString(),
        state: "done",
      }];
    }
    return [{
      id: "main-1",
      role: "assistant",
      text: "main-history",
      createdAt: new Date().toISOString(),
      state: "done",
    }];
  });
  const getBotOverview = vi.fn(async (): Promise<BotOverview> => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    cluster: {
      enabled: true,
      writePolicy: "selected_agents",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 2,
      defaultTimeoutSeconds: 600,
      modelTiers: { low: "", medium: "", high: "" },
    },
  }));
  const client = createClient({ listAgents, listMessages, getBotOverview });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("reviewer-history")).toBeInTheDocument();
  expect(screen.queryByText("main-history")).not.toBeInTheDocument();
  expect(listMessages).toHaveBeenLastCalledWith("main", { agentId: "reviewer" });
  expect(await screen.findByRole("combobox", { name: "当前 agent" })).toHaveValue("reviewer");
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  expect(screen.getByText("只读模式")).toBeInTheDocument();
  expect(window.localStorage.getItem("tcb.activeAgent.main")).toBe("reviewer");
});

test("cluster mode can switch to a child agent for read-only history", async () => {
  const user = userEvent.setup();
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false },
    ],
  }));
  const listMessages = vi.fn(async (_botAlias: string, options?: { agentId?: string }): Promise<ChatMessage[]> => {
    if (options?.agentId === "reviewer") {
      return [{
        id: "reviewer-1",
        role: "assistant",
        text: "reviewer-history",
        createdAt: new Date().toISOString(),
        state: "done",
      }];
    }
    return [{
      id: "main-1",
      role: "assistant",
      text: "main-history",
      createdAt: new Date().toISOString(),
      state: "done",
    }];
  });
  const getBotOverview = vi.fn(async (): Promise<BotOverview> => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    cluster: {
      enabled: true,
      writePolicy: "selected_agents",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 2,
      defaultTimeoutSeconds: 600,
      modelTiers: { low: "", medium: "", high: "" },
    },
  }));
  const client = createClient({ listAgents, listMessages, getBotOverview });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("main-history")).toBeInTheDocument();

  await user.selectOptions(await screen.findByRole("combobox", { name: "当前 agent" }), "reviewer");

  await waitFor(() => {
    expect(listMessages).toHaveBeenLastCalledWith("main", { agentId: "reviewer" });
  });
  expect(await screen.findByText("reviewer-history")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  expect(screen.getByText("只读模式")).toBeInTheDocument();
});

test("chat screen switches agent and scopes history requests", async () => {
  const user = userEvent.setup();
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false },
    ],
  }));
  const listMessages = vi.fn(async (_botAlias: string, options?: { agentId?: string }): Promise<ChatMessage[]> => {
    if (options?.agentId === "reviewer") {
      return [{
        id: "reviewer-1",
        role: "assistant",
        text: "reviewer-history",
        createdAt: new Date().toISOString(),
        state: "done",
      }];
    }
    return [];
  });
  const listConversations = vi.fn(async (): Promise<ConversationListResult> => ({
    activeConversationId: "",
    items: [],
  }));
  const client = createClient({ listAgents, listMessages, listConversations });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.selectOptions(await screen.findByRole("combobox", { name: "当前 agent" }), "reviewer");

  await waitFor(() => {
    expect(listMessages).toHaveBeenLastCalledWith("main", { agentId: "reviewer" });
  });
  expect(await screen.findByText("reviewer-history")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "历史" }));
  await waitFor(() => {
    expect(listConversations).toHaveBeenLastCalledWith("main", "", { agentId: "reviewer" });
  });
});

test("chat screen reports active child agent activity when sending", async () => {
  const user = userEvent.setup();
  let resolveSend: ((message: ChatMessage) => void) | null = null;
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "代码审查", systemPrompt: "先列风险", enabled: true, isMain: false },
    ],
  }));
  const sendMessage = vi.fn(
    async () => new Promise<ChatMessage>((resolve) => {
      resolveSend = resolve;
    }),
  );
  const onBotActivityChange = vi.fn();
  const client = createClient({ listAgents, sendMessage });

  render(
    <ChatScreen
      botAlias="main"
      client={client}
      onBotActivityChange={onBotActivityChange}
    />,
  );

  await user.selectOptions(await screen.findByRole("combobox", { name: "当前 agent" }), "reviewer");
  await user.type(screen.getByPlaceholderText("发给 代码审查..."), "检查实现");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => {
    expect(onBotActivityChange).toHaveBeenCalledWith("main", expect.objectContaining({
      activityStatus: "busy",
      agentId: "reviewer",
      agentName: "代码审查",
      busyAgentIds: ["reviewer"],
      busyAgentNames: ["代码审查"],
      busyAgentCount: 1,
    }));
  });

  await act(async () => {
    resolveSend?.({
      id: "assistant-done",
      role: "assistant",
      text: "完成",
      createdAt: new Date().toISOString(),
      state: "done",
    });
  });

  await waitFor(() => {
    expect(onBotActivityChange).toHaveBeenLastCalledWith("main", expect.objectContaining({
      activityStatus: "idle",
      agentId: "reviewer",
      agentName: "代码审查",
      busyAgentIds: [],
      busyAgentNames: [],
      busyAgentCount: 0,
    }));
  });
});

test("chat screen opens history and switches conversation", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  const client = createClient({
    listConversations: async (): Promise<ConversationListResult> => ({
      activeConversationId: "conv-1",
      items: [{
        id: "conv-2",
        title: "旧会话",
        lastMessagePreview: "旧回答",
        messageCount: 2,
        pinned: false,
        active: false,
        status: "active",
        botAlias: "main",
        botMode: "cli",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: now,
        updatedAt: now,
      }],
    }),
    selectConversation: async (): Promise<ConversationSelectResult> => ({
      conversation: {
        id: "conv-2",
        title: "旧会话",
        lastMessagePreview: "旧回答",
        messageCount: 2,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        botMode: "cli",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: now,
        updatedAt: now,
      },
      messages: [{
        id: "assistant-old",
        role: "assistant",
        text: "旧回答",
        createdAt: now,
        state: "done",
      }],
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "历史" }));
  await user.click(await screen.findByRole("button", { name: /旧会话/ }));

  expect(await screen.findByText("旧回答")).toBeInTheDocument();
});

test("chat screen creates a new conversation from the action bar", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  const createConversation = vi.fn(async (): Promise<ConversationSelectResult> => ({
    conversation: {
      id: "conv-new",
      title: "新会话",
      lastMessagePreview: "",
      messageCount: 0,
      pinned: false,
      active: true,
      status: "active",
      botAlias: "main",
      botMode: "cli",
      cliType: "codex",
      workingDir: "C:\\workspace",
      createdAt: now,
      updatedAt: now,
    },
    messages: [],
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-existing",
      role: "assistant",
      text: "已有会话",
      createdAt: now,
      state: "done",
    }],
    createConversation,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("已有会话")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "新会话" }));

  expect(createConversation).toHaveBeenCalledWith("main");
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  expect(screen.queryByText("已有会话")).not.toBeInTheDocument();
});

test("chat screen blocks conversation switch while streaming", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  const client = createClient({
    listConversations: async (): Promise<ConversationListResult> => ({
      activeConversationId: "conv-1",
      items: [{
        id: "conv-2",
        title: "旧会话",
        lastMessagePreview: "旧回答",
        messageCount: 2,
        pinned: false,
        active: false,
        status: "active",
        botAlias: "main",
        botMode: "cli",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: now,
        updatedAt: now,
      }],
    }),
    sendMessage: async () => new Promise<ChatMessage>(() => {}),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "运行");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await user.click(await screen.findByRole("button", { name: "历史" }));

  expect(await screen.findByRole("button", { name: /旧会话/ })).toBeDisabled();
});

test("shows waiting time while a reply is still pending", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          onChunk("done");
          resolve({
            id: "assistant-done",
            role: "assistant",
            text: "done",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 1600);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("已等待 1 秒", {}, { timeout: 2500 })).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByTestId("assistant-markdown-message")).toHaveTextContent("done");
  }, { timeout: 3000 });
}, 8000);

test("queues and merges messages typed while a reply is streaming", async () => {
  const user = userEvent.setup();
  let resolveFirst: ((message: ChatMessage) => void) | null = null;
  const sendMessage = vi.fn((
    _botAlias: string,
    text: string,
    _onChunk: (chunk: string) => void,
  ) => {
    if (sendMessage.mock.calls.length === 1) {
      return new Promise<ChatMessage>((resolve) => {
        resolveFirst = resolve;
      });
    }
    return Promise.resolve({
      id: "assistant-queued",
      role: "assistant",
      text: `已处理 ${text}`,
      createdAt: new Date().toISOString(),
      state: "done" as const,
    });
  });
  const client = createClient({ sendMessage: sendMessage as never });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "第一条");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(screen.getByRole("textbox")).toBeEnabled();
  await user.type(screen.getByRole("textbox"), "第二条");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await user.type(screen.getByRole("textbox"), "第三条");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(screen.getByText("排队中")).toBeInTheDocument();
  expect(screen.getByText("排队中").parentElement).toHaveTextContent("第二条");
  expect(screen.getByText("排队中").parentElement).toHaveTextContent("第三条");

  resolveFirst?.({
    id: "assistant-first",
    role: "assistant",
    text: "第一条完成",
    createdAt: new Date().toISOString(),
    state: "done",
  });

  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
  expect(sendMessage.mock.calls[1][1]).toBe("第二条\n\n第三条");
  expect(await screen.findByText(/已处理 第二条/)).toBeInTheDocument();
  expect(screen.queryByText("排队中")).not.toBeInTheDocument();
});

test("previous bot reply does not drain queued messages from the next bot", async () => {
  const user = userEvent.setup();
  let resolveMainSend: ((message: ChatMessage) => void) | null = null;
  const sendMessage = vi.fn((botAlias: string, text: string) => {
    if (botAlias === "main") {
      return new Promise<ChatMessage>((resolve) => {
        resolveMainSend = resolve;
      });
    }
    return Promise.resolve({
      id: `${botAlias}-reply`,
      role: "assistant",
      text: `${botAlias}:${text}`,
      createdAt: new Date().toISOString(),
      state: "done" as const,
    });
  });
  const client = createClient({
    getBotOverview: async (botAlias: string): Promise<BotOverview> => (
      botAlias === "main"
        ? {
          alias: "main",
          cliType: "codex",
          status: "running",
          workingDir: "C:\\workspace",
          isProcessing: false,
        }
        : {
          alias: "team2",
          cliType: "codex",
          status: "busy",
          workingDir: "C:\\team2",
          isProcessing: true,
        }
    ),
    listMessages: async (botAlias: string): Promise<ChatMessage[]> => (
      botAlias === "main"
        ? []
        : [{
          id: "team2-streaming",
          role: "assistant",
          text: "team2-processing",
          createdAt: new Date().toISOString(),
          state: "streaming",
        }]
    ),
    sendMessage: sendMessage as never,
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "main-question");
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(sendMessage.mock.calls[0][0]).toBe("main");

  rerender(<ChatScreen botAlias="team2" client={client} />);
  expect(await screen.findByText("team2-processing")).toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "team2-queued");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(screen.getByText("排队中")).toBeInTheDocument();

  resolveMainSend?.({
    id: "main-final",
    role: "assistant",
    text: "main-final",
    createdAt: new Date().toISOString(),
    state: "done",
  });

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(screen.getByText("排队中")).toBeInTheDocument();
  expect(screen.queryByText("main-final")).not.toBeInTheDocument();
});

test("recovers from a stalled sse completion by syncing finished history", async () => {
  vi.useFakeTimers();
  const getBotOverview = vi.fn(async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }));
  const listMessages = vi
    .fn<() => Promise<ChatMessage[]>>()
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([
      {
        id: "user-server-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-20T12:00:00",
        state: "done",
      },
      {
        id: "assistant-server-1",
        role: "assistant",
        text: "最终结果",
        createdAt: "2026-04-20T12:00:01",
        state: "done",
      },
    ]);
  const client = createClient({
    getBotOverview: getBotOverview as never,
    listMessages: listMessages as never,
    sendMessage: (_botAlias: string, _text: string, onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>(() => {
        window.setTimeout(() => {
          onChunk("最终结果");
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(screen.getByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "继续" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1300);
  });

  expect(screen.getByText("最终结果")).toBeInTheDocument();
  expect(screen.getByText(/已等待 \d+ 秒/)).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2600);
    await Promise.resolve();
  });

  expect(getBotOverview).toHaveBeenCalledTimes(2);
  expect(listMessages).toHaveBeenCalledTimes(2);
  expect(screen.getByText("最终结果")).toBeInTheDocument();
  expect(screen.queryByText(/已等待 \d+ 秒/)).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
}, 8000);

test("keeps showing a visible streaming badge while preview text is updating", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void, onStatus) =>
      new Promise<ChatMessage>((resolve) => {
        onStatus?.({ previewText: "正在整理上下文" });
        window.setTimeout(() => {
          resolve({
            id: "assistant-done",
            role: "assistant",
            text: "完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 300);
      }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("正在整理上下文")).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();
});

test("assistant send does not let an old idle poll replace the finishing reply with a stale streaming row", async () => {
  vi.useFakeTimers();
  let overviewCalls = 0;
  const listMessages = vi
    .fn<() => Promise<ChatMessage[]>>()
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([
      {
        id: "user-server-1",
        role: "user",
        text: "继续",
        createdAt: "2026-04-20T12:00:00",
        state: "done",
      },
      {
        id: "assistant-server-1",
        role: "assistant",
        text: "轮询中的旧预览",
        createdAt: "2026-04-20T12:00:01",
        state: "streaming",
      },
    ]);
  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      return {
        alias: "assistant1",
        cliType: "codex",
        status: overviewCalls === 1 ? "running" : "busy",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: overviewCalls > 1,
      };
    },
    listMessages: listMessages as never,
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void) =>
      new Promise<ChatMessage>((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-done",
            role: "assistant",
            text: "真正完成的回复",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 6000);
      }),
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(screen.getByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "继续" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5100);
  });

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });

  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText("真正完成的回复")).toBeInTheDocument();
  expect(screen.queryByText("轮询中的旧预览")).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  expect(screen.queryByText(/已等待 \d+ 秒/)).not.toBeInTheDocument();
});

test("assistant poll reloads full history for existing streaming assistant row when count is unchanged", async () => {
  vi.useFakeTimers();

  const initialMessages: ChatMessage[] = [
    {
      id: "user-1",
      role: "user",
      text: "继续",
      createdAt: "2026-04-30T01:00:00.000Z",
      state: "done",
    },
    {
      id: "assistant-1",
      role: "assistant",
      text: "旧过程预览",
      createdAt: "2026-04-30T01:00:01.000Z",
      state: "streaming",
    },
  ];
  const finalMessages: ChatMessage[] = [
    initialMessages[0],
    {
      id: "assistant-1",
      role: "assistant",
      text: "最终结果",
      createdAt: "2026-04-30T01:00:01.000Z",
      state: "done",
    },
  ];

  let overviewCalls = 0;
  let historyCalls = 0;
  const getBotOverview = vi.fn(async () => {
    overviewCalls += 1;
    return {
      alias: "assistant1",
      cliType: "codex" as const,
      status: overviewCalls === 1 ? "busy" as const : "running" as const,
      workingDir: "C:\\workspace",
      botMode: "assistant" as const,
      isProcessing: overviewCalls === 1,
      historyCount: 2,
    };
  });
  const listMessages = vi.fn(async () => {
    historyCalls += 1;
    return historyCalls === 1 ? initialMessages : finalMessages;
  });
  const listMessageDelta = vi.fn(async () => ({
    items: [],
    reset: false,
  }));
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  }) as WebBotClient & { listMessageDelta: typeof listMessageDelta };
  client.listMessageDelta = listMessageDelta;

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(screen.getByText("旧过程预览")).toBeInTheDocument();
  expect(screen.getByText("正在输出")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(screen.getByText("最终结果")).toBeInTheDocument();
  expect(screen.queryByText("旧过程预览")).not.toBeInTheDocument();
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  expect(listMessageDelta).not.toHaveBeenCalled();
  expect(listMessages).toHaveBeenCalledTimes(2);
});

test("assistant sse recovery resolves stale runningReply when overview is idle", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "assistant1",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      botMode: "assistant",
      isProcessing: false,
      runningReply: {
        userText: "修吧",
        previewText: "旧预览",
        startedAt: "2026-04-26T01:00:57.000Z",
      },
    }),
    listMessages: async () => [
      {
        id: "user-server-1",
        role: "user",
        text: "修吧",
        createdAt: "2026-04-26T01:00:57.000Z",
        state: "done",
      },
      {
        id: "assistant-server-1",
        role: "assistant",
        text: "已修。",
        createdAt: "2026-04-26T01:00:58.000Z",
        state: "done",
      },
    ],
    sendMessage: () => new Promise<ChatMessage>(() => undefined),
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "修吧" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(screen.getByText("正在输出")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  }, { timeout: 4000 });
  expect(screen.getByText("已修。")).toBeInTheDocument();
});

test("shows new conversation and kill actions for non-main bots", async () => {
  const client = createClient();

  render(<ChatScreen botAlias="team2" client={client} />);

  expect(await screen.findByRole("button", { name: "新会话" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重置会话" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "终止任务" })).toBeInTheDocument();
});

test("does not force-scroll to the bottom once the user scrolls away during streaming", async () => {
  const user = userEvent.setup();
  const original = HTMLElement.prototype.scrollIntoView;
  const scrollSpy = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollSpy,
  });

  const client = createClient({
    sendMessage: (_botAlias: string, _text: string, _onChunk: (chunk: string) => void, onStatus) =>
      new Promise<ChatMessage>((resolve) => {
        onStatus?.({ previewText: "第一段预览" });
        window.setTimeout(() => {
          onStatus?.({ previewText: "第二段预览" });
        }, 80);
        window.setTimeout(() => {
          resolve({
            id: "assistant-final",
            role: "assistant",
            text: "最终结果",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 160);
      }),
  });

  let scrollTop = 1500;

  try {
    render(<ChatScreen botAlias="main" client={client} />);
    expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    Object.defineProperties(scrollContainer, {
      scrollHeight: {
        configurable: true,
        get: () => 2200,
      },
      clientHeight: {
        configurable: true,
        get: () => 600,
      },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
      },
    });

    await user.type(screen.getByPlaceholderText("输入消息"), "继续");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("第一段预览")).toBeInTheDocument();

    scrollSpy.mockClear();
    scrollTop = 400;
    fireEvent.wheel(scrollContainer);
    fireEvent.scroll(scrollContainer);

    expect(await screen.findByText("最终结果")).toBeInTheDocument();
    expect(scrollSpy).not.toHaveBeenCalled();
  } finally {
    if (original) {
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
        configurable: true,
        value: original,
      });
    } else {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  }
}, 10000);

test("scrolls back to the bottom when a hidden chat screen becomes visible again", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "第一条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-2",
        role: "assistant",
        text: "第二条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
  });

  const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
  expect(await screen.findByText("第二条")).toBeInTheDocument();

  const scrollContainer = screen.getByTestId("chat-scroll-container");
  let scrollTop = 0;
  Object.defineProperties(scrollContainer, {
    scrollHeight: {
      configurable: true,
      get: () => 2200,
    },
    clientHeight: {
      configurable: true,
      get: () => 600,
    },
    scrollTop: {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value;
      },
    },
  });

  scrollTop = 100;
  fireEvent.scroll(scrollContainer);

  rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
  rerender(<ChatScreen botAlias="main" client={client} isVisible />);

  await waitFor(() => {
    expect(scrollTop).toBe(2200);
  });
});

test("keeps a cached chat screen pinned when reveal layout settles after the first frame", async () => {
  const originalRequestAnimationFrame = window.requestAnimationFrame;
  const originalCancelAnimationFrame = window.cancelAnimationFrame;
  const frameCallbacks: FrameRequestCallback[] = [];
  Object.defineProperty(window, "requestAnimationFrame", {
    configurable: true,
    writable: true,
    value: (callback: FrameRequestCallback) => {
      frameCallbacks.push(callback);
      return frameCallbacks.length;
    },
  });
  Object.defineProperty(window, "cancelAnimationFrame", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });

  const messages: ChatMessage[] = Array.from({ length: 24 }, (_, index) => ({
    id: `message-${index}`,
    role: index % 2 === 0 ? "user" : "assistant",
    text: `消息 ${index}`,
    createdAt: new Date().toISOString(),
    state: "done",
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => messages,
  });

  function Harness({ visible }: { visible: boolean }) {
    return (
      <div className={visible ? "block" : "hidden"}>
        <ChatScreen botAlias="main" client={client} isVisible={visible} />
      </div>
    );
  }

  try {
    const { rerender } = render(<Harness visible />);
    expect(await screen.findByText("消息 23")).toBeInTheDocument();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    let scrollTop = 0;
    let stableLayout = true;
    Object.defineProperties(scrollContainer, {
      scrollHeight: {
        configurable: true,
        get: () => (stableLayout ? 2200 : 1200),
      },
      clientHeight: {
        configurable: true,
        get: () => 600,
      },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value;
        },
      },
    });

    scrollTop = 100;
    fireEvent.scroll(scrollContainer);

    rerender(<Harness visible={false} />);
    stableLayout = false;
    rerender(<Harness visible />);

    await waitFor(() => {
      expect(scrollTop).toBe(1200);
    });
    stableLayout = true;

    while (frameCallbacks.length > 0) {
      const callback = frameCallbacks.shift();
      callback?.(performance.now());
      if (scrollTop === 2200) {
        break;
      }
    }

    expect(scrollTop).toBe(2200);
  } finally {
    Object.defineProperty(window, "requestAnimationFrame", {
      configurable: true,
      writable: true,
      value: originalRequestAnimationFrame,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      configurable: true,
      writable: true,
      value: originalCancelAnimationFrame,
    });
  }
});

test("keeps reveal auto-scroll alive when layout emits a scroll event during quick bot switching", async () => {
  const originalRequestAnimationFrame = window.requestAnimationFrame;
  const originalCancelAnimationFrame = window.cancelAnimationFrame;
  const frameCallbacks = new Map<number, FrameRequestCallback>();
  let nextFrameId = 1;
  Object.defineProperty(window, "requestAnimationFrame", {
    configurable: true,
    writable: true,
    value: (callback: FrameRequestCallback) => {
      const frameId = nextFrameId;
      nextFrameId += 1;
      frameCallbacks.set(frameId, callback);
      return frameId;
    },
  });
  Object.defineProperty(window, "cancelAnimationFrame", {
    configurable: true,
    writable: true,
    value: (frameId: number) => {
      frameCallbacks.delete(frameId);
    },
  });

  const messages: ChatMessage[] = Array.from({ length: 24 }, (_, index) => ({
    id: `quick-switch-message-${index}`,
    role: index % 2 === 0 ? "user" : "assistant",
    text: `快速切换消息 ${index}`,
    createdAt: new Date().toISOString(),
    state: "done",
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => messages,
  });

  function Harness({ visible }: { visible: boolean }) {
    return (
      <div className={visible ? "block" : "hidden"}>
        <ChatScreen botAlias="main" client={client} isVisible={visible} />
      </div>
    );
  }

  try {
    const { rerender } = render(<Harness visible />);
    expect(await screen.findByText("快速切换消息 23")).toBeInTheDocument();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    let scrollTop = 0;
    let stableLayout = true;
    Object.defineProperties(scrollContainer, {
      scrollHeight: {
        configurable: true,
        get: () => (stableLayout ? 2200 : 1200),
      },
      clientHeight: {
        configurable: true,
        get: () => 600,
      },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value;
        },
      },
    });

    scrollTop = 100;
    fireEvent.scroll(scrollContainer);

    rerender(<Harness visible={false} />);
    stableLayout = false;
    rerender(<Harness visible />);

    await waitFor(() => {
      expect(scrollTop).toBe(1200);
    });

    stableLayout = true;
    scrollTop = 100;
    fireEvent.scroll(scrollContainer);

    while (frameCallbacks.size > 0) {
      const [frameId, callback] = Array.from(frameCallbacks.entries())[0];
      frameCallbacks.delete(frameId);
      callback(performance.now());
    }

    expect(scrollTop).toBe(2200);
  } finally {
    Object.defineProperty(window, "requestAnimationFrame", {
      configurable: true,
      writable: true,
      value: originalRequestAnimationFrame,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      configurable: true,
      writable: true,
      value: originalCancelAnimationFrame,
    });
  }
});

test("keeps a newly visible chat screen pinned when rendered content grows", async () => {
  const originalResizeObserver = window.ResizeObserver;
  let resizeCallback: ResizeObserverCallback | null = null;
  class MockResizeObserver {
    observe = vi.fn();
    disconnect = vi.fn();

    constructor(callback: ResizeObserverCallback) {
      resizeCallback = callback;
    }
  }
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    value: MockResizeObserver,
  });

  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-1",
        role: "assistant",
        text: "第一条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
      {
        id: "assistant-2",
        role: "assistant",
        text: "第二条",
        createdAt: new Date().toISOString(),
        state: "done",
      },
    ],
  });

  try {
    const { rerender } = render(<ChatScreen botAlias="main" client={client} isVisible />);
    expect(await screen.findByText("第二条")).toBeInTheDocument();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    let scrollHeight = 1200;
    let scrollTop = 0;
    Object.defineProperties(scrollContainer, {
      scrollHeight: {
        configurable: true,
        get: () => scrollHeight,
      },
      clientHeight: {
        configurable: true,
        get: () => 600,
      },
      scrollTop: {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = value;
        },
      },
    });

    rerender(<ChatScreen botAlias="main" client={client} isVisible={false} />);
    rerender(<ChatScreen botAlias="main" client={client} isVisible />);

    await waitFor(() => {
      expect(scrollTop).toBe(1200);
    });

    scrollHeight = 2200;
    resizeCallback?.([] as unknown as ResizeObserverEntry[], {} as ResizeObserver);

    expect(scrollTop).toBe(2200);
  } finally {
    if (originalResizeObserver) {
      Object.defineProperty(window, "ResizeObserver", {
        configurable: true,
        value: originalResizeObserver,
      });
    } else {
      delete (window as { ResizeObserver?: unknown }).ResizeObserver;
    }
  }
});

test("opens a file preview dialog when clicking a local markdown file link", async () => {
  const user = userEvent.setup();
  const readSpy = vi.fn(async () => ({
    content: "# README\n\n文件预览",
    mode: "head" as const,
    fileSizeBytes: 128,
    isFullContent: true,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "[查看 README](C:/workspace/README.md)",
      createdAt: new Date().toISOString(),
      state: "done",
    }],
    readFile: readSpy,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("link", { name: "查看 README" }));

  expect(readSpy).toHaveBeenCalledWith("main", "README.md");
  expect(await screen.findByRole("dialog", { name: "README.md" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "README" })).toBeInTheDocument();
});

test("chat screen trusts the history streaming row instead of merging overview.runningReply", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "列出当前目录",
        createdAt: "2026-04-18T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "我先检查目录结构。",
        createdAt: "2026-04-18T10:00:01",
        state: "streaming",
      },
    ],
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "busy",
      workingDir: "C:\\workspace",
      isProcessing: true,
      runningReply: {
        userText: "列出当前目录",
        previewText: "这段预览不应再单独插入",
        startedAt: "2026-04-18T10:00:01",
        updatedAt: "2026-04-18T10:00:02",
      },
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("我先检查目录结构。")).toBeInTheDocument();
  expect(screen.queryByText("这段预览不应再单独插入")).not.toBeInTheDocument();
  expect(screen.getAllByText("列出当前目录")).toHaveLength(1);
});

test("chat screen does not render restored synthetic reply bubbles after refresh", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "继续执行",
        createdAt: "2026-04-18T10:00:00",
        state: "done",
      },
      {
        id: "assistant-1",
        role: "assistant",
        text: "恢复到上次可见输出",
        createdAt: "2026-04-18T10:00:01",
        state: "error",
      },
    ],
    getBotOverview: async () => {
      overviewCalls += 1;
      return {
        alias: "main",
        cliType: "codex",
        status: overviewCalls === 1 ? "busy" : "running",
        workingDir: "C:\\workspace",
        isProcessing: false,
        runningReply: {
          userText: "继续执行",
          previewText: "恢复到上次可见输出",
          startedAt: "2026-04-18T10:00:01",
          updatedAt: "2026-04-18T10:00:05",
        },
      };
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  expect(screen.getByText("恢复到上次可见输出")).toBeInTheDocument();
  expect(screen.queryByText("检测到上次未完成任务，已恢复最近预览。")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "继续" })).not.toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });

  expect(screen.getAllByText("恢复到上次可见输出")).toHaveLength(1);
});

test("does not show elapsed badge from loaded history", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "历史结果",
      createdAt: new Date().toISOString(),
      elapsedSeconds: 8,
      state: "done",
    }],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("历史结果")).toBeInTheDocument();
  expect(screen.queryByText("用时 8 秒")).not.toBeInTheDocument();
});

test("assistant chat polls while idle and picks up scheduled cron runs", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  let historyCalls = 0;
  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      if (overviewCalls < 3) {
        return {
          alias: "assistant1",
          cliType: "codex",
          status: "running",
          workingDir: "C:\\workspace",
          botMode: "assistant",
          isProcessing: false,
        };
      }
      return {
        alias: "assistant1",
        cliType: "codex",
        status: "busy",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: true,
        runningReply: {
          userText: "定时检查邮箱",
          previewText: "正在读取最新邮件",
          startedAt: "2026-04-16T18:00:00",
          updatedAt: "2026-04-16T18:00:02",
        },
      };
    },
    listMessages: async (): Promise<ChatMessage[]> => {
      historyCalls += 1;
      if (historyCalls < 2) {
        return [];
      }
      return [
        {
          id: "user-cron-1",
          role: "user",
          text: "定时检查邮箱",
          createdAt: "2026-04-16T18:00:00",
          state: "done",
        },
        {
          id: "assistant-cron-1",
          role: "assistant",
          text: "正在读取最新邮件",
          createdAt: "2026-04-16T18:00:01",
          state: "streaming",
        },
      ];
    },
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  expect(screen.queryByText("定时检查邮箱")).not.toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(10100);
  });

  expect(screen.getByText("定时检查邮箱")).toBeInTheDocument();
  expect(screen.getByText("正在读取最新邮件")).toBeInTheDocument();
});

test("hidden assistant chat does not start idle polling on mount", async () => {
  vi.useFakeTimers();

  const getBotOverview = vi.fn(async () => ({
    alias: "assistant1",
    cliType: "codex" as const,
    status: "running" as const,
    workingDir: "C:\\workspace",
    botMode: "assistant",
    isProcessing: false,
    historyCount: 0,
  }));
  const listMessages = vi.fn(async (): Promise<ChatMessage[]> => []);
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  });

  render(<ChatScreen botAlias="assistant1" client={client} isVisible={false} />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(getBotOverview).not.toHaveBeenCalled();
  expect(listMessages).not.toHaveBeenCalled();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });

  expect(getBotOverview).not.toHaveBeenCalled();
  expect(listMessages).not.toHaveBeenCalled();
});

test("hidden assistant chat activates when it becomes visible", async () => {
  const getBotOverview = vi.fn(async () => ({
    alias: "assistant1",
    cliType: "codex" as const,
    status: "running" as const,
    workingDir: "C:\\workspace",
    botMode: "assistant",
    isProcessing: false,
    historyCount: 0,
  }));
  const listMessages = vi.fn(async (): Promise<ChatMessage[]> => []);
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  });

  const { rerender } = render(<ChatScreen botAlias="assistant1" client={client} isVisible={false} />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getBotOverview).not.toHaveBeenCalled();

  rerender(<ChatScreen botAlias="assistant1" client={client} isVisible />);

  await waitFor(() => {
    expect(getBotOverview).toHaveBeenCalledTimes(1);
    expect(listMessages).toHaveBeenCalledTimes(1);
  });
});

test("assistant idle polling requests history delta when history count changes", async () => {
  vi.useFakeTimers();
  const initialMessages: ChatMessage[] = [
    {
      id: "user-1",
      role: "user",
      text: "第一问",
      createdAt: "2026-04-16T18:00:00",
      state: "done",
    },
  ];
  const deltaMessages: ChatMessage[] = [
    {
      id: "assistant-2",
      role: "assistant",
      text: "增量回复",
      createdAt: "2026-04-16T18:00:02",
      state: "done",
    },
  ];
  let overviewCalls = 0;
  const getBotOverview = vi.fn(async () => {
    overviewCalls += 1;
    return {
      alias: "assistant1",
      cliType: "codex" as const,
      status: "running" as const,
      workingDir: "C:\\workspace",
      botMode: "assistant",
      isProcessing: false,
      historyCount: overviewCalls === 1 ? 1 : 2,
    };
  });
  const listMessages = vi.fn(async () => initialMessages);
  const listMessageDelta = vi.fn(async () => ({
    items: deltaMessages,
    reset: false,
  }));
  const client = createClient({
    getBotOverview,
    listMessages: listMessages as never,
  }) as WebBotClient & {
    listMessageDelta: typeof listMessageDelta;
  };
  client.listMessageDelta = listMessageDelta;

  render(<ChatScreen botAlias="assistant1" client={client} isVisible />);

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(listMessages).toHaveBeenCalledTimes(1);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5100);
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(listMessageDelta).toHaveBeenCalledWith("assistant1", "user-1", 50);
  expect(screen.getByText("增量回复")).toBeInTheDocument();
});

test("assistant chat immediately shows manual cron prompts after the settings handoff event", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  let historyCalls = 0;
  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      if (overviewCalls === 1) {
        return {
          alias: "assistant1",
          cliType: "codex",
          status: "running",
          workingDir: "C:\\workspace",
          botMode: "assistant",
          isProcessing: false,
        };
      }
      return {
        alias: "assistant1",
        cliType: "codex",
        status: "busy",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: true,
        runningReply: {
          userText: "检查最近邮件并总结重点",
          previewText: "正在读取最近邮件",
          startedAt: "2026-04-16T18:05:00",
          updatedAt: "2026-04-16T18:05:01",
        },
      };
    },
    listMessages: async (): Promise<ChatMessage[]> => {
      historyCalls += 1;
      if (historyCalls === 1) {
        return [];
      }
      return [
        {
          id: "user-cron-1",
          role: "user",
          text: "检查最近邮件并总结重点",
          createdAt: "2026-04-16T18:05:00",
          state: "done",
        },
        {
          id: "assistant-cron-1",
          role: "assistant",
          text: "正在读取最近邮件",
          createdAt: "2026-04-16T18:05:01",
          state: "streaming",
        },
      ];
    },
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  await act(async () => {
    window.dispatchEvent(new CustomEvent("assistant-cron-run-enqueued", {
      detail: {
        botAlias: "assistant1",
        runId: "run_123456",
        prompt: "检查最近邮件并总结重点",
        queuedAt: "2026-04-16T18:05:00",
      },
    }));
    await Promise.resolve();
  });

  expect(screen.getByText("检查最近邮件并总结重点")).toBeInTheDocument();
  expect(screen.getByText("正在输出...")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1100);
  });

  expect(screen.getByText("正在读取最近邮件")).toBeInTheDocument();
});

test("assistant proposal patch request event sends structured chat task and dispatches completion", async () => {
  const dispatchSpy = vi.spyOn(window, "dispatchEvent");
  const sendMessage = vi.fn(async (
    _botAlias: string,
    _text: string,
    _onChunk: (chunk: string) => void,
    _onStatus?: unknown,
    onTrace?: (trace: unknown) => void,
    _options?: unknown,
  ) => {
    onTrace?.({
      kind: "tool_call",
      summary: "git worktree add",
      toolName: "git",
      callId: "call_git_worktree_add",
    });
    return {
      id: "assistant-patch-1",
      role: "assistant",
      text: "patch 已生成\n目标工程: main",
      createdAt: new Date().toISOString(),
      state: "done",
    } satisfies ChatMessage;
  });
  const client = createClient({
    getBotOverview: async () => ({
      alias: "assistant1",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      botMode: "assistant",
      isProcessing: false,
    }),
    listMessages: async () => [],
    sendMessage,
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });
  dispatchSpy.mockClear();

  await act(async () => {
    window.dispatchEvent(new CustomEvent("assistant-proposal-patch-requested", {
      detail: {
        botAlias: "assistant1",
        proposalId: "pr_sync_memory_index",
        proposalTitle: "补 memory index 审计",
        targetAlias: "main",
        regenerate: false,
        visibleText: "为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch",
      },
    }));
    await Promise.resolve();
  });

  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalled();
  });

  const sendArgs = sendMessage.mock.calls[0];
  expect(sendArgs?.[1]).toBe("为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch");
  expect(sendArgs?.[5]).toEqual({
    taskMode: "proposal_patch",
    taskPayload: {
      proposalId: "pr_sync_memory_index",
      targetAlias: "main",
      regenerate: false,
    },
    visibleText: "为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch",
  });
  expect(await screen.findByText("为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch")).toBeInTheDocument();
  expect(await screen.findByText(/patch 已生成\s*目标工程: main/)).toBeInTheDocument();

  const completeEvent = dispatchSpy.mock.calls
    .map(([value]) => value)
    .find((value) => value instanceof CustomEvent && value.type === "assistant-proposal-patch-completed") as CustomEvent | undefined;
  expect(completeEvent?.detail).toMatchObject({
    botAlias: "assistant1",
    proposalId: "pr_sync_memory_index",
    ok: true,
    targetAlias: "main",
    summary: "patch 已生成\n目标工程: main",
  });
});

test("assistant chat shows explicit runtime queue banner for background tasks", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "assistant1",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      botMode: "assistant",
      isProcessing: false,
      assistantRuntime: {
        pendingCount: 2,
        queuedCount: 1,
        active: {
          runId: "run_active",
          source: "cron",
          status: "running",
          taskMode: "dream",
          interactive: false,
          jobId: "daily_dream",
          jobTitle: "每日自整理",
          visibleText: "dream prompt",
          enqueuedAt: "2026-04-16T18:05:00",
        },
        queue: [
          {
            runId: "run_queued",
            source: "web",
            status: "queued",
            taskMode: "standard",
            interactive: true,
            visibleText: "帮我总结今天进度",
            enqueuedAt: "2026-04-16T18:05:01",
          },
        ],
      },
    }),
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  expect(await screen.findByText("assistant 串行队列忙碌中：1 项执行，1 项排队")).toBeInTheDocument();
  expect(screen.getByText("当前：定时 dream · 每日自整理")).toBeInTheDocument();
  expect(screen.getByText("排队：聊天消息 · 帮我总结今天进度")).toBeInTheDocument();
});

test("assistant queued send keeps the pending row visible while runtime queue is still busy", async () => {
  vi.useFakeTimers();

  let overviewCalls = 0;
  let resolveSend: ((message: ChatMessage) => void) | null = null;
  const sendResult = new Promise<ChatMessage>((resolve) => {
    resolveSend = resolve;
  });

  const client = createClient({
    getBotOverview: async () => {
      overviewCalls += 1;
      if (overviewCalls === 1) {
        return {
          alias: "assistant1",
          cliType: "codex",
          status: "running",
          workingDir: "C:\\workspace",
          botMode: "assistant",
          isProcessing: false,
        };
      }
      return {
        alias: "assistant1",
        cliType: "codex",
        status: "running",
        workingDir: "C:\\workspace",
        botMode: "assistant",
        isProcessing: false,
        assistantRuntime: {
          pendingCount: 2,
          queuedCount: 1,
          active: {
            runId: "run_active",
            source: "cron",
            status: "running",
            taskMode: "dream",
            interactive: false,
            jobTitle: "每日自整理",
            visibleText: "dream prompt",
            enqueuedAt: "2026-04-16T18:05:00",
          },
          queue: [
            {
              runId: "run_queued",
              source: "web",
              status: "queued",
              taskMode: "standard",
              interactive: true,
              visibleText: "帮我总结今天进度",
              enqueuedAt: "2026-04-16T18:05:01",
            },
          ],
        },
      };
    },
    listMessages: async () => [],
    sendMessage: async () => sendResult,
  });

  render(<ChatScreen botAlias="assistant1" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });

  fireEvent.change(screen.getByPlaceholderText("输入消息"), {
    target: { value: "帮我总结今天进度" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(screen.getByText("正在输出...")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2600);
  });

  expect(screen.getByText("assistant 串行队列忙碌中：1 项执行，1 项排队")).toBeInTheDocument();
  expect(screen.getByText("正在输出...")).toBeInTheDocument();

  resolveSend?.({
    id: "assistant-final",
    role: "assistant",
    text: "已总结完成",
    createdAt: new Date().toISOString(),
    state: "done",
  });

  await act(async () => {
    await Promise.resolve();
  });
});
