import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ChatTraceDetails, CliParamsPayload, ClusterTaskStatus, ConversationDeleteResult, ConversationListResult, ConversationSelectResult, GitActionResult, GitDiffPayload, GitOverview, PromptPreset } from "../services/types";
import { WebApiClientError } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

const MODEL_OPTIONS = ["gpt-5.5", "gpt-5.4", "claude-opus-4-7", "claude-sonnet-4-6", "none"];

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
    deleteConversation: async (): Promise<ConversationDeleteResult> => ({
      deletedConversationId: "conv-deleted",
      activeConversationId: "",
      nativeSessionCleared: true,
      items: [],
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

  render(<ChatScreen botAlias="main" client={client} accountId="acct1" />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "修一下这个 bug");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(screen.getByTestId("chat-composer-root")).toHaveAttribute("data-pulse", "true");
  expect(await screen.findByText("修一下这个 bug")).toBeInTheDocument();
  expect(screen.queryByText("用时 3 秒")).not.toBeInTheDocument();
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
  expect(screen.queryByText("正在输出")).not.toBeInTheDocument();
  expect(await screen.findByText("稍后完成")).toBeInTheDocument();
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
        kind: "event",
        rawType: "thread.started",
        summary: "同步事件已记录。",
      },
      {
        kind: "commentary",
        summary: "目录已读取完成。",
      },
    ],
    traceCount: 5,
    toolCallCount: 1,
    processCount: 3,
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
          traceCount: 5,
          toolCallCount: 1,
          processCount: 3,
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
  expect(traceItems).toHaveLength(4);
  expect(traceItems[0]?.textContent).toContain("我先检查目录结构。");
  expect(traceItems[1]?.textContent).toContain("工具调用 1");
  expect(traceItems[1]?.textContent).toContain("Exit 1");
  expect(traceItems[2]?.textContent).toContain("同步事件已记录。");
  expect(traceItems[3]?.textContent).toContain("目录已读取完成。");
  expect(screen.getByText("我先检查目录结构。").className).not.toContain("text-slate-800");
  expect(traceItems[2]?.className).not.toContain("bg-violet-50");
});


test("kill button is hidden while idle and shown while streaming", async () => {
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

  await screen.findByText("暂无消息，开始聊天吧");
  expect(screen.queryByRole("button", { name: "终止任务" })).not.toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByRole("button", { name: "终止任务" })).toBeEnabled();
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

  await user.click(screen.getByRole("button", { name: "历史会话" }));
  await waitFor(() => {
    expect(listConversations).toHaveBeenLastCalledWith("main", "", { agentId: "reviewer" });
  });
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
  await user.click(await screen.findByRole("button", { name: "历史会话" }));

  expect(await screen.findByRole("button", { name: "旧会话 旧回答" })).toBeDisabled();
});


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
  expect(JSON.parse(window.localStorage.getItem("tcb.queuedMessage.main.main") || "{}")).toMatchObject({
    text: "第二条\n\n第三条",
    attachments: [],
  });

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
  expect(window.localStorage.getItem("tcb.queuedMessage.main.main")).toBeNull();
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





