import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { EventType } from "../services/agUiProtocol";
import { ChatStreamIncompleteError } from "../services/chatStreamError";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ConversationListResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function createClient(overrides: Partial<WebBotClient> = {}): WebBotClient {
  return Object.assign(new MockWebBotClient(), {
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }),
    listMessages: async () => ({ items: [] }),
    listConversations: async (): Promise<ConversationListResult> => ({
      activeConversationId: "",
      items: [],
    }),
    ...overrides,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

test("leaves plan mode as soon as plan execution starts", async () => {
  const user = userEvent.setup();
  const executionGate = deferred<void>();
  const backingClient = new MockWebBotClient();
  const executePlan = vi.fn<WebBotClient["executePlan"]>(async (...args) => {
    await executionGate.promise;
    return backingClient.executePlan(...args);
  });
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "assistant-plan-executed",
    role: "assistant",
    text: "方案执行完成",
    createdAt: "2026-08-27T02:00:00Z",
    state: "done",
  }));
  const client = createClient({
    listMessages: async () => ({
      items: [{
        id: "assistant-plan-draft",
        role: "assistant",
        text: "<PLAN_DRAFT>\n# 执行这个方案\n\n完成目标改动。\n</PLAN_DRAFT>",
        createdAt: "2026-08-27T01:59:00Z",
        state: "done",
      }],
    }),
    executePlan,
    sendMessage,
  });
  window.localStorage.setItem("tcb.planMode.main", "1");

  render(<ChatScreen botAlias="main" client={client} />);

  const planModeButton = await screen.findByRole("button", { name: "计划模式" });
  expect(planModeButton).toHaveAttribute("aria-pressed", "true");
  await user.click(await screen.findByRole("button", { name: "执行方案" }));
  await waitFor(() => expect(executePlan).toHaveBeenCalledTimes(1));

  expect(planModeButton).toHaveAttribute("aria-pressed", "false");
  expect(window.localStorage.getItem("tcb.planMode.main")).toBeNull();

  await act(async () => executionGate.resolve());
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "计划模式" })).toHaveAttribute("aria-pressed", "false");
});

test("binds direct done assistant message to backend id from stream meta", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    _onChunk,
    onStatus,
  ) => {
    onStatus?.({ turnId: "turn-direct-1", assistantMessageId: "assistant-direct-final" });
    return {
      id: "assistant-direct-final",
      turnId: "turn-direct-1",
      role: "assistant",
      text: "直接完成",
      createdAt: "2026-06-26T14:10:00Z",
      state: "done",
    };
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "直接返回");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("直接完成")).toBeInTheDocument();
  expect(screen.getAllByText("直接完成")).toHaveLength(1);
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
});

test("does not report a hidden cancelled reply as unread", async () => {
  const user = userEvent.setup();
  const onUnreadResult = vi.fn();
  const client = createClient({
    sendMessage: vi.fn<WebBotClient["sendMessage"]>(async () => ({
      id: "assistant-cancelled",
      role: "assistant",
      text: "已停止",
      createdAt: "2026-08-27T01:10:00Z",
      updatedAt: "2026-08-27T01:10:01Z",
      state: "error",
      meta: { completionState: "cancelled" },
    })),
  });
  let visibilityState: DocumentVisibilityState = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibilityState);
  render(<ChatScreen botAlias="main" client={client} onUnreadResult={onUnreadResult} />);
  await screen.findByText("暂无消息，开始聊天吧");

  await user.type(screen.getByPlaceholderText("输入消息"), "停止这个任务");
  visibilityState = "hidden";
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("已停止")).toBeInTheDocument();
  expect(onUnreadResult).not.toHaveBeenCalled();
});

test("binds stream metadata to the placeholder before a deferred final and replaces it in place", async () => {
  const user = userEvent.setup();
  const final = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((
    _botAlias,
    _text,
    _onChunk,
    onStatus,
  ) => {
    onStatus?.({ turnId: "turn-stream-bound", assistantMessageId: "assistant-stream-bound" });
    return final.promise;
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "等待最终答复");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
  await waitFor(() => expect(document.querySelector('[data-message-id="assistant-stream-bound"]')).toBeInTheDocument());

  await act(async () => {
    final.resolve({
      id: "assistant-stream-bound",
      turnId: "turn-stream-bound",
      role: "assistant",
      text: "最终答复",
      createdAt: "2026-08-05T00:00:00Z",
      state: "done",
    });
  });

  expect(await screen.findByText("最终答复")).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
  expect(document.querySelectorAll('[data-message-id="assistant-stream-bound"]')).toHaveLength(1);
});

test("cluster chat stays on the main Agent, preserves @ text, and sends no dispatch fields", async () => {
  const user = userEvent.setup();
  const cluster = {
    enabled: true,
    writePolicy: "main_only" as const,
    conflictPolicy: "snapshot_diff" as const,
    maxParallelAgents: 3,
    defaultTimeoutSeconds: 600,
    modelTiers: { low: "", medium: "", high: "" },
    reasoningEfforts: { low: "", medium: "", high: "" },
  };
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "assistant-cluster-main",
    role: "assistant",
    text: "已由主 Agent 处理",
    createdAt: "2026-08-12T00:00:00Z",
    state: "done",
  }));
  const client = createClient({
    getBotOverview: vi.fn(async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      cluster,
      agents: [
        { id: "main", name: "主 Agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "cluster-slot-1", name: "旧静态角色", systemPrompt: "", enabled: true, isMain: false },
      ],
    })),
    listAgents: vi.fn(async () => ({ items: [
      { id: "main", name: "主 Agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "cluster-slot-1", name: "旧静态角色", systemPrompt: "", enabled: true, isMain: false },
    ] })),
    listConversations: vi.fn<WebBotClient["listConversations"]>(async (): Promise<ConversationListResult> => ({
      activeConversationId: "conv-main",
      items: [{
        id: "conv-main",
        title: "当前会话",
        lastMessagePreview: "",
        messageCount: 0,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        cliType: "codex",
        agentId: "main",
        workingDir: "C:\\workspace",
        clusterTeam: { version: 1, assignments: [] },
        clusterTeamRevision: 0,
        createdAt: "2026-08-12T00:00:00Z",
        updatedAt: "2026-08-12T00:00:00Z",
      }],
    })),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await screen.findByText("暂无消息，开始聊天吧");
  expect(screen.queryByTestId("cluster-team-panel")).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "当前 agent" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "关闭集群模式" })).toHaveAttribute("aria-pressed", "true");

  await user.type(screen.getByPlaceholderText("输入消息"), "@reviewer 请审查");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

  expect(sendMessage.mock.calls[0][1]).toBe("@reviewer 请审查");
  const sendOptions = sendMessage.mock.calls[0][5] as unknown as Record<string, unknown>;
  expect(sendOptions).not.toHaveProperty("cluster");
  expect(sendOptions).not.toHaveProperty("mentions");
});

test("toggles the Bot cluster config from chat and only shows an assigned enabled team", async () => {
  const user = userEvent.setup();
  const cluster = {
    enabled: false,
    writePolicy: "all_agents" as const,
    conflictPolicy: "block_same_file" as const,
    maxParallelAgents: 2,
    defaultTimeoutSeconds: 900,
    modelTiers: { low: "fast-model", medium: "", high: "strong-model" },
    reasoningEfforts: { low: "low", medium: "medium", high: "high" },
  };
  const client = createClient({
    getBotOverview: vi.fn(async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      canOperate: true,
      cluster,
    })),
    listConversations: vi.fn<WebBotClient["listConversations"]>(async (): Promise<ConversationListResult> => ({
      activeConversationId: "conv-main",
      items: [{
        id: "conv-main",
        title: "当前会话",
        lastMessagePreview: "",
        messageCount: 0,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        cliType: "codex",
        agentId: "main",
        workingDir: "C:\\workspace",
        clusterTeam: {
          version: 1,
          assignments: [{
            agentId: "cluster-slot-1",
            name: "前端审查",
            responsibility: "检查界面状态",
            assignmentRevision: 1,
          }],
        },
        clusterTeamRevision: 1,
        createdAt: "2026-08-12T00:00:00Z",
        updatedAt: "2026-08-12T00:00:00Z",
      }],
    })),
  });
  const updateClusterConfig = vi.spyOn(client, "updateClusterConfig");

  render(<ChatScreen botAlias="main" client={client} />);

  const toggle = await screen.findByRole("button", { name: "开启集群模式" });
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByTestId("cluster-team-panel")).not.toBeInTheDocument();

  await user.click(toggle);

  await waitFor(() => expect(updateClusterConfig).toHaveBeenCalledWith("main", {
    ...cluster,
    enabled: true,
  }));
  expect(await screen.findByRole("button", { name: "关闭集群模式" })).toHaveAttribute("aria-pressed", "true");
  const teamPanel = screen.getByTestId("cluster-team-panel");
  await user.click(within(teamPanel).getByRole("button", { name: "展开集群编组" }));
  expect(screen.getByText("前端审查")).toBeInTheDocument();
});

test("pauses auxiliary sync while hidden and reconciles once after returning", async () => {
  let visibilityState: DocumentVisibilityState = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibilityState);
  const clusterStatus = {
    tasks: [
      {
        taskId: "task-running",
        agentId: "worker-running",
        assignmentRevision: 1,
        roleName: "动态审查员",
        responsibility: "检查前端状态",
        status: "running",
        modelTier: "medium",
        allowWrite: false,
        createdAt: "2026-08-08T00:00:00Z",
        startedAt: "2026-08-08T00:00:01Z",
        completedAt: "",
        error: "",
      },
      {
        taskId: "task-completed",
        agentId: "worker-running",
        assignmentRevision: 1,
        roleName: "动态测试员",
        responsibility: "执行回归测试",
        status: "completed",
        modelTier: "medium",
        allowWrite: false,
        createdAt: "2026-08-08T00:00:00Z",
        startedAt: "2026-08-08T00:00:01Z",
        completedAt: "2026-08-08T00:00:02Z",
        error: "",
      },
      {
        taskId: "task-failed",
        agentId: "worker-failed",
        roleName: "动态构建员",
        responsibility: "验证构建产物",
        status: "failed",
        modelTier: "medium",
        allowWrite: false,
        createdAt: "2026-08-08T00:00:00Z",
        startedAt: "2026-08-08T00:00:01Z",
        completedAt: "2026-08-08T00:00:02Z",
        error: "子任务失败",
      },
    ],
    queuedCount: 0,
    runningCount: 1,
    completedCount: 1,
    failedCount: 1,
    pendingCount: 1,
  };
  const getBotOverview = vi.fn<WebBotClient["getBotOverview"]>(async (): Promise<BotOverview> => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: true,
    historyCount: 1,
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 600,
      modelTiers: { low: "", medium: "", high: "" },
      reasoningEfforts: { low: "", medium: "", high: "" },
    },
    activeClusterRun: {
      runId: "cluster-foreground",
      status: "running",
      capacity: 3,
      teamRevision: 1,
      team: {
        version: 1,
        assignments: [{
          agentId: "worker-running",
          name: "动态审查员",
          responsibility: "检查前端状态",
          assignmentRevision: 1,
        }],
      },
      tasks: clusterStatus,
    },
  }));
  const listMessageDelta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({
    reset: false,
    revision: 7,
    nextCursor: "",
    items: [],
  }));
  const getClusterTaskStatus = vi.fn<WebBotClient["getClusterTaskStatus"]>(async () => clusterStatus);
  const client = createClient({
    getBotOverview,
    listMessages: vi.fn<WebBotClient["listMessages"]>(async () => ({
      items: [{
        id: "assistant-background-poll",
        role: "assistant",
        text: "辅助同步运行中",
        createdAt: "2026-08-08T00:00:00Z",
        state: "streaming",
      }],
      revision: 7,
    })),
    listMessageDelta,
    getClusterTaskStatus,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await waitFor(() => expect(getClusterTaskStatus).toHaveBeenCalledTimes(1));
  expect(getClusterTaskStatus).toHaveBeenLastCalledWith(
    "main",
    "cluster-foreground",
    { includeOutput: false },
  );
  expect(await screen.findByText("已分配 1 / 集群规模 3")).toBeInTheDocument();
  expect(screen.queryByText("动态审查员")).not.toBeInTheDocument();
  fireEvent.click(within(screen.getByTestId("cluster-team-panel")).getByRole("button", { name: "展开集群编组" }));
  expect(screen.getByText("动态审查员")).toBeInTheDocument();
  expect(screen.getByText("模型档位：medium")).toBeInTheDocument();
  expect(screen.queryByText("检查前端状态")).not.toBeInTheDocument();
  expect(screen.getByText("已完成")).toBeInTheDocument();
  expect(screen.getByText("处理中")).toBeInTheDocument();
  expect(screen.queryByText("智能体集群任务")).not.toBeInTheDocument();
  expect(screen.queryByText("动态测试员")).not.toBeInTheDocument();
  expect(screen.queryByText("子任务失败")).not.toBeInTheDocument();

  visibilityState = "hidden";
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hiddenCounts = {
    overview: getBotOverview.mock.calls.length,
    delta: listMessageDelta.mock.calls.length,
    cluster: getClusterTaskStatus.mock.calls.length,
  };

  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTimeAsync(30_000));
  expect(getBotOverview).toHaveBeenCalledTimes(hiddenCounts.overview);
  expect(listMessageDelta).toHaveBeenCalledTimes(hiddenCounts.delta);
  expect(getClusterTaskStatus).toHaveBeenCalledTimes(hiddenCounts.cluster);

  visibilityState = "visible";
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getBotOverview).toHaveBeenCalledTimes(hiddenCounts.overview + 1);
  expect(listMessageDelta).toHaveBeenCalledTimes(hiddenCounts.delta + 1);
  expect(getClusterTaskStatus).toHaveBeenCalledTimes(hiddenCounts.cluster + 1);

  visibilityState = "hidden";
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const secondHiddenCounts = {
    overview: getBotOverview.mock.calls.length,
    delta: listMessageDelta.mock.calls.length,
    cluster: getClusterTaskStatus.mock.calls.length,
  };
  await act(async () => vi.advanceTimersByTimeAsync(30_000));
  expect(getBotOverview).toHaveBeenCalledTimes(secondHiddenCounts.overview);
  expect(listMessageDelta).toHaveBeenCalledTimes(secondHiddenCounts.delta);
  expect(getClusterTaskStatus).toHaveBeenCalledTimes(secondHiddenCounts.cluster);
});

test("does not abort the active SSE request when the document is hidden", async () => {
  let visibilityState: DocumentVisibilityState = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibilityState);
  let activeSignal: AbortSignal | undefined;
  const final = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((
    _botAlias,
    _text,
    _onChunk,
    onStatus,
    _onTrace,
    options,
  ) => {
    activeSignal = options?.signal;
    onStatus?.({ turnId: "turn-visible-sse", assistantMessageId: "assistant-visible-sse" });
    return final.promise;
  });
  let overviewCalls = 0;
  const getBotOverview = vi.fn<WebBotClient["getBotOverview"]>(async (): Promise<BotOverview> => {
    overviewCalls += 1;
    return {
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: overviewCalls > 1,
      historyCount: 0,
    };
  });
  const listMessageDelta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({
    reset: false,
    revision: 3,
    nextCursor: "",
    items: [],
  }));
  const client = createClient({
    getBotOverview,
    listMessages: vi.fn(async () => ({ items: [], revision: 3 })),
    listMessageDelta,
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "保持主 SSE" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  expect(activeSignal).toBeDefined();

  visibilityState = "hidden";
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hiddenCounts = {
    overview: getBotOverview.mock.calls.length,
    delta: listMessageDelta.mock.calls.length,
  };
  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTimeAsync(30_000));

  expect(activeSignal?.aborted).toBe(false);
  expect(getBotOverview).toHaveBeenCalledTimes(hiddenCounts.overview);
  expect(listMessageDelta).toHaveBeenCalledTimes(hiddenCounts.delta);

  visibilityState = "visible";
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(activeSignal?.aborted).toBe(false);

  await act(async () => {
    final.resolve({
      id: "assistant-visible-sse",
      turnId: "turn-visible-sse",
      role: "assistant",
      text: "主 SSE 完成",
      createdAt: "2026-08-08T00:00:00Z",
      state: "done",
    });
  });
});

test("recovers an authoritative final reply after EOF arrives before the terminal event", async () => {
  let overviewCalls = 0;
  const listMessageDelta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({
    reset: true,
    revision: 8,
    nextCursor: "1",
    items: [
      {
        id: "user-incomplete-stream",
        turnId: "turn-incomplete-stream",
        role: "user",
        text: "断流恢复",
        createdAt: "2026-07-20T00:00:00Z",
        state: "done",
      },
      {
        id: "assistant-incomplete-stream",
        turnId: "turn-incomplete-stream",
        role: "assistant",
        text: "无需 F5 的权威终答",
        createdAt: "2026-07-20T00:00:01Z",
        state: "done",
      },
    ],
  }));
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    _onChunk,
    onStatus,
  ) => {
    onStatus?.({
      turnId: "turn-incomplete-stream",
      assistantMessageId: "assistant-incomplete-stream",
      previewText: "过程快照",
    });
    throw new ChatStreamIncompleteError({
      turnId: "turn-incomplete-stream",
      assistantMessageId: "assistant-incomplete-stream",
      partialMessage: {
        id: "assistant-incomplete-stream",
        turnId: "turn-incomplete-stream",
        role: "assistant",
        text: "过程快照",
        createdAt: "2026-07-20T00:00:01Z",
        state: "streaming",
      },
    });
  });
  const client = createClient({
    getBotOverview: vi.fn(async (): Promise<BotOverview> => {
      overviewCalls += 1;
      return {
        alias: "main",
        cliType: "codex",
        status: "running",
        workingDir: "C:\\workspace",
        isProcessing: false,
        historyCount: overviewCalls === 1 ? 0 : 2,
      };
    }),
    listMessages: vi.fn(async () => ({ items: [], revision: 7 })),
    listMessageDelta,
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "断流恢复" } });
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2);
    await Promise.resolve();
  });

  expect(listMessageDelta).toHaveBeenCalledTimes(1);
  expect(listMessageDelta).toHaveBeenCalledWith(
    "main",
    expect.any(String),
    50,
    expect.objectContaining({ revision: 7 }),
  );
  expect(screen.getAllByText("无需 F5 的权威终答")).toHaveLength(1);
  expect(screen.queryByText("聊天响应在收到结束事件前中断，正在从历史记录恢复")).not.toBeInTheDocument();
});

test("native permission trace can be approved from flat transcript", async () => {
  const user = userEvent.setup();
  const replyNativeAgentPermission = vi.fn(async () => ({ permissionId: "perm-1", approved: true }));
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: true,
      supportedExecutionModes: ["cli", "native_agent"],
      defaultExecutionMode: "cli",
    }),
    listMessages: async () => ({ items: [
      {
        id: "assistant-1",
        role: "assistant",
        text: "",
        createdAt: new Date().toISOString(),
        state: "streaming",
        meta: {
          tracePresentation: "native_agent_flat",
          nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
          traceCount: 1,
          processCount: 1,
          trace: [{
            kind: "permission",
            source: "native_agent",
            summary: "原生 agent 请求权限",
            payload: { id: "perm-1", state: "permission.updated" },
          }],
        },
      },
    ] }),
    replyNativeAgentPermission,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "原生 agent" })).toBeDisabled();
  expect(await screen.findByTestId("native-agent-transcript")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "展开过程详情" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "允许一次" }));

  await waitFor(() => expect(replyNativeAgentPermission).toHaveBeenCalledWith(
    "main",
    "perm-1",
    expect.objectContaining({ approved: true, executionMode: "native_agent" }),
  ));
  expect(await screen.findByText("原生 agent 权限已允许")).toBeInTheDocument();
});

test("native history loads flat trace details after expansion", async () => {
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      {
        id: "trace-1",
        ordinal: 1,
        kind: "commentary",
        source: "native_agent",
        summary: "我先检查目录结构。",
      },
      {
        id: "trace-2",
        ordinal: 2,
        kind: "tool_call",
        source: "native_agent",
        toolName: "shell_command",
        summary: "Get-ChildItem",
        payload: { arguments: "Get-ChildItem" },
      },
      {
        id: "trace-3",
        ordinal: 3,
        kind: "tool_result",
        source: "native_agent",
        summary: "Exit code: 0",
        payload: { output: "Exit code: 0" },
      },
    ],
    traceCount: 3,
    toolCallCount: 1,
    processCount: 1,
  }));
  const client = createClient({
    listMessages: async () => ({ items: [
      {
        id: "assistant-native-history",
        role: "assistant",
        text: "最终答复",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          tracePresentation: "native_agent_flat",
          nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
          traceCount: 3,
          toolCallCount: 1,
          processCount: 1,
        },
      },
    ] }),
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(getMessageTrace).not.toHaveBeenCalled();
  await userEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-native-history"));
  expect(await within(transcript).findByText("我先检查目录结构。")).toBeInTheDocument();
  const eventGroup = within(transcript).getByTestId("native-agent-event-group");
  await userEvent.click(eventGroup.querySelector("summary") as HTMLElement);
  expect(within(transcript).getAllByText("shell_command").length).toBeGreaterThan(0);
  expect(within(transcript).getAllByText("Exit code: 0").length).toBeGreaterThan(0);
  expect(within(transcript).getByTestId("native-agent-final-result")).toHaveTextContent("最终答复");
});

test("non-native permission trace never exposes native permission actions", async () => {
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: true,
      supportedExecutionModes: ["cli", "native_agent"],
      defaultExecutionMode: "cli",
    }),
    listMessages: async () => ({ items: [
      {
        id: "assistant-1",
        role: "assistant",
        text: "",
        createdAt: new Date().toISOString(),
        state: "streaming",
        meta: {
          traceCount: 1,
          processCount: 1,
          trace: [{
            kind: "permission",
            source: "codex",
            summary: "CLI 请求确认",
            payload: { id: "perm-1", state: "permission.updated" },
          }],
        },
      },
    ] }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("CLI 请求确认")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "允许一次" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
});

test("renders CLI trace in the unified AG-UI transcript", async () => {
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "assistant-cli-trace",
      role: "assistant",
      text: "CLI 最终答复",
      createdAt: "2026-08-05T00:00:00Z",
      state: "done",
      meta: {
        traceCount: 1,
        processCount: 1,
        trace: [{ kind: "commentary", source: "codex", summary: "CLI 路由哨兵" }],
      },
    }] }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const row = await screen.findByTestId("chat-message-row");
  const transcript = within(row).getByTestId("native-agent-transcript");
  expect(within(transcript).getByText("CLI 路由哨兵")).toBeInTheDocument();
  expect(within(transcript).getByTestId("native-agent-final-result")).toHaveTextContent("CLI 最终答复");
  expect(within(row).queryByTestId("chat-trace-panel-assistant-cli-trace")).not.toBeInTheDocument();
});

test("live non-native ag-ui stream renders regular assistant message", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    _onChunk,
    _onStatus,
    _onTrace,
    _options,
    onAgUiEvent,
  ) => {
    onAgUiEvent?.({ type: EventType.RUN_STARTED, threadId: "thread-1", runId: "run-1" });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-1",
      activityType: "TCB_STATUS",
      replace: true,
      content: { previewText: "运行中" },
    });
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_START, messageId: "assistant-live", role: "assistant" });
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-live", delta: "**answer**" });
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_END, messageId: "assistant-live" });
    onAgUiEvent?.({ type: EventType.RUN_FINISHED, threadId: "thread-1", runId: "run-1", outcome: { type: "success" } });
    return {
      id: "assistant-live",
      role: "assistant",
      text: "**answer**",
      createdAt: new Date().toISOString(),
      state: "done",
    };
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(await screen.findByTestId("assistant-markdown-message")).toHaveTextContent("answer");
  expect(screen.queryByTestId("native-agent-transcript")).not.toBeInTheDocument();
});

test("renders native AG-UI only in NativeAgentTranscript", async () => {
  const user = userEvent.setup();
  const final = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((
    _botAlias,
    _text,
    _onChunk,
    _onStatus,
    _onTrace,
    _options,
    onAgUiEvent,
  ) => {
    onAgUiEvent?.({ type: EventType.RUN_STARTED, threadId: "thread-native", runId: "run-native" });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "native-trace-1",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        id: "native-trace-1",
        rawKind: "commentary",
        source: "native_agent",
        summary: "原生 AG-UI 路由哨兵",
      },
    });
    return final.promise;
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} forcedExecutionMode="native_agent" />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "运行原生任务");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(screen.queryByTestId("chat-trace-panel-assistant-native-agui")).not.toBeInTheDocument();
  await user.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
  expect(await within(transcript).findByText("原生 AG-UI 路由哨兵")).toBeInTheDocument();

  await act(async () => {
    final.resolve({
      id: "assistant-native-agui",
      role: "assistant",
      text: "原生完成",
      createdAt: "2026-08-05T00:00:00Z",
      state: "done",
    });
  });
});

test("opens child conversations from the dynamic cluster team and returns to main", async () => {
  const user = userEvent.setup();
  const listAgents = vi.fn(async () => ({
    items: [
      { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
      { id: "reviewer", name: "旧固定角色", systemPrompt: "先列风险", enabled: true, isMain: false },
      { id: "tester", name: "旧测试角色", systemPrompt: "", enabled: true, isMain: false },
    ],
  }));
  const listMessages = vi.fn<WebBotClient["listMessages"]>(async (_botAlias, options) => {
    if (options?.agentId === "reviewer") {
      return { items: [{
        id: "reviewer-1",
        role: "assistant",
        text: "reviewer-history",
        createdAt: new Date().toISOString(),
        state: "done",
      }] };
    }
    return { items: [] };
  });
  const cluster = {
    enabled: true,
    writePolicy: "main_only" as const,
    conflictPolicy: "snapshot_diff" as const,
    maxParallelAgents: 3,
    defaultTimeoutSeconds: 600,
    modelTiers: { low: "gpt-5.6-mini", medium: "gpt-5.6-codex", high: "gpt-5.6-pro" },
    reasoningEfforts: { low: "low", medium: "medium", high: "xhigh" },
  };
  const clusterTeam = {
    version: 1 as const,
    assignments: [
      {
        agentId: "reviewer",
        name: "动态审查员",
        responsibility: "审查本轮改动",
        assignmentRevision: 2,
      },
      {
        agentId: "tester",
        name: "动态测试员",
        responsibility: "验证本轮改动",
        assignmentRevision: 1,
      },
    ],
  };
  const clusterTaskStatus = {
    tasks: [{
      taskId: "task-reviewer-high",
      agentId: "reviewer",
      roleName: "动态审查员",
      responsibility: "审查本轮改动",
      teamRevision: 2,
      assignmentRevision: 2,
      status: "completed",
      modelTier: "high",
      allowWrite: false,
      createdAt: "2026-08-12T00:00:00Z",
      startedAt: "2026-08-12T00:00:01Z",
      completedAt: "2026-08-12T00:00:02Z",
      error: "",
    }],
    queuedCount: 0,
    runningCount: 0,
    completedCount: 1,
    failedCount: 0,
    pendingCount: 0,
  };
  const getBotOverview = vi.fn<WebBotClient["getBotOverview"]>(async (_botAlias, options): Promise<BotOverview> => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    cluster,
    agents: (await listAgents()).items,
    ...(!options?.agentId ? {
      activeClusterRun: {
        runId: "run-readonly-child",
        status: "running",
        team: clusterTeam,
        teamRevision: 2,
        capacity: 3,
        freeSlots: 1,
        tasks: clusterTaskStatus,
      },
    } : {}),
  }));
  const listConversations = vi.fn<WebBotClient["listConversations"]>(async (_botAlias, _query, options): Promise<ConversationListResult> => ({
    activeConversationId: options?.agentId ? "conv-reviewer" : "conv-main",
    items: options?.agentId ? [{
      id: "conv-reviewer",
      title: "子 Agent 会话",
      lastMessagePreview: "reviewer-history",
      messageCount: 1,
      pinned: false,
      active: true,
      status: "active",
      botAlias: "main",
      cliType: "codex",
      agentId: "reviewer",
      workingDir: "C:\\workspace",
      clusterTeam: { version: 1, assignments: [] },
      clusterTeamRevision: 0,
      createdAt: "2026-08-12T00:00:00Z",
      updatedAt: "2026-08-12T00:00:00Z",
    }] : [{
      id: "conv-main",
      title: "当前会话",
      lastMessagePreview: "",
      messageCount: 0,
      pinned: false,
      active: true,
      status: "active",
      botAlias: "main",
      cliType: "codex",
      agentId: "main",
      workingDir: "C:\\workspace",
      clusterTeam,
      clusterTeamRevision: 2,
      createdAt: "2026-08-12T00:00:00Z",
      updatedAt: "2026-08-12T00:00:00Z",
    }],
  }));
  const getClusterTaskStatus = vi.fn<WebBotClient["getClusterTaskStatus"]>(async () => clusterTaskStatus);
  const client = createClient({ getBotOverview, listAgents, listMessages, listConversations, getClusterTaskStatus });
  const sendMessage = vi.spyOn(client, "sendMessage");

  render(<ChatScreen botAlias="main" client={client} />);

  const teamPanel = await screen.findByTestId("cluster-team-panel");
  await user.click(within(teamPanel).getByRole("button", { name: "展开集群编组" }));
  expect(screen.getByText("动态审查员")).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "当前 agent" })).not.toBeInTheDocument();
  expect(screen.queryByText("旧固定角色")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看动态审查员对话" }));

  await waitFor(() => {
    expect(listMessages).toHaveBeenLastCalledWith("main", { agentId: "reviewer" });
  });
  expect(await screen.findByText("reviewer-history")).toBeInTheDocument();
  const childTeamDock = screen.getByTestId("cluster-team-dock");
  const childTeamPanel = within(childTeamDock).getByTestId("cluster-team-panel");
  expect(within(childTeamPanel).getByText("动态审查员")).toBeInTheDocument();
  expect(within(childTeamPanel).queryByText("动态测试员")).not.toBeInTheDocument();
  expect(within(childTeamPanel).queryByText("审查本轮改动")).not.toBeInTheDocument();
  const readOnlyStatus = "会话只读 · 模型：gpt-5.6-pro · 思考深度：xhigh";
  expect(screen.getAllByText(readOnlyStatus)).toHaveLength(1);
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "发送" })).not.toBeInTheDocument();
  expect(sendMessage).not.toHaveBeenCalled();
  expect(within(screen.getByTestId("chat-scroll-container")).queryByRole("button", { name: "返回主 Agent" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "历史会话" }));
  await waitFor(() => {
    expect(listConversations).toHaveBeenLastCalledWith("main", "", { agentId: "reviewer" });
  });
  await user.click(screen.getByRole("button", { name: "返回主 Agent" }));
  await waitFor(() => expect(listMessages).toHaveBeenLastCalledWith("main"));
  await user.click(within(screen.getByTestId("cluster-team-panel")).getByRole("button", { name: "展开集群编组" }));
  expect(await screen.findByText("动态测试员")).toBeInTheDocument();
});

test("execution mode switch reloads scoped history", async () => {
  const user = userEvent.setup();
  const getBotOverview = vi.fn<WebBotClient["getBotOverview"]>(async (_botAlias, options) => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "cli",
    executionMode: options?.executionMode === "native_agent" ? "native_agent" : "cli",
  }));
  const listMessages = vi.fn<WebBotClient["listMessages"]>(async (_botAlias, options) => ({ items: options?.executionMode === "native_agent"
    ? [{
      id: "assistant-native",
      role: "assistant",
      text: "原生历史",
      createdAt: new Date().toISOString(),
      state: "done",
    }]
    : [{
      id: "assistant-cli",
      role: "assistant",
      text: "CLI 历史",
      createdAt: new Date().toISOString(),
      state: "done",
    }] }));
  const client = createClient({ getBotOverview, listMessages });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("CLI 历史")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "原生 agent" }));
  expect(await screen.findByText("原生历史")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "CLI" }));
  expect(await screen.findByText("CLI 历史")).toBeInTheDocument();
  expect(listMessages.mock.calls.some(([, options]) => options?.executionMode === "native_agent")).toBe(true);
  expect(listMessages.mock.calls.some(([, options]) => !options?.executionMode)).toBe(true);
});

test("native user bubble rollback confirms and refreshes history outside solo mode", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  let rolledBack = false;
  const user1: ChatMessage = {
    id: "user-1",
    conversationId: "conv-1",
    role: "user",
    text: "第一轮需求",
    createdAt: now,
    state: "done",
  };
  const assistant1: ChatMessage = {
    id: "assistant-1",
    turnId: "turn-1",
    conversationId: "conv-1",
    role: "assistant",
    text: "第一轮完成",
    createdAt: now,
    state: "done",
    meta: { workspaceHistoryHead: "head-1", linearIndex: 1, rollbackSupported: true },
  };
  const user2: ChatMessage = {
    id: "user-2",
    conversationId: "conv-1",
    role: "user",
    text: "第二轮需求",
    createdAt: now,
    state: "done",
  };
  const assistant2: ChatMessage = {
    id: "assistant-2",
    turnId: "turn-2",
    conversationId: "conv-1",
    role: "assistant",
    text: "第二轮完成",
    createdAt: now,
    state: "done",
    meta: { workspaceHistoryHead: "head-2", linearIndex: 2, rollbackSupported: true },
  };
  const listMessages = vi.fn<WebBotClient["listMessages"]>(async () => ({
    items: rolledBack ? [user1, assistant1] : [user1, assistant1, user2, assistant2],
  }));
  const listConversations = vi.fn<WebBotClient["listConversations"]>(async (): Promise<ConversationListResult> => ({
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
      cliType: "codex",
      workingDir: "C:\\workspace",
      createdAt: now,
      updatedAt: now,
      workspaceHistoryHead: rolledBack ? "head-1" : "head-2",
      linearIndex: rolledBack ? 1 : 2,
      rollbackSupported: true,
    }],
  }));
  const rollbackNativeAgentHistory = vi.fn<WebBotClient["rollbackNativeAgentHistory"]>(async () => {
    rolledBack = true;
    return {
      conversationId: "conv-1",
      currentTurnId: "turn-1",
      rollbackSupported: false,
      message: "已撤回到所选会话点",
    };
  });
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      executionMode: "native_agent",
    }),
    listMessages,
    listConversations,
    rollbackNativeAgentHistory,
  });

  render(<ChatScreen botAlias="main" client={client} forcedExecutionMode="native_agent" />);

  expect(await screen.findByText("第二轮需求")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "撤回到此消息前" }));
  const dialog = await screen.findByRole("dialog", { name: "确认撤回" });
  expect(dialog.parentElement?.parentElement).toBe(document.body);
  expect(rollbackNativeAgentHistory).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "确认撤回" }));

  await waitFor(() => {
    expect(rollbackNativeAgentHistory).toHaveBeenCalledWith("main", {
      conversationId: "conv-1",
      targetTurnId: "turn-1",
    });
  });
  await waitFor(() => {
    expect(screen.queryByText("第二轮需求")).not.toBeInTheDocument();
  });
  expect(listMessages.mock.calls.filter(([, options]) => options?.executionMode === "native_agent").length).toBeGreaterThan(1);
  expect(listConversations).toHaveBeenCalled();
});
