import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { EventType } from "../services/agUiProtocol";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ChatTraceDetails, CliParamsPayload, ClusterTaskStatus, ConversationBulkDeleteResult, ConversationDeleteResult, ConversationListResult, ConversationSelectResult, FavoriteAnswerItem, GitActionResult, GitDiffPayload, GitOverview, PromptPreset } from "../services/types";
import { WebApiClientError } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { createChatHistoryFixture } from "./fixtures/performance";

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
    deleteAllConversations: async (): Promise<ConversationBulkDeleteResult> => ({
      deletedCount: 0,
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
  vi.restoreAllMocks();
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

test("refreshes visible idle chat when history count changes", async () => {
  vi.useFakeTimers();
  let overviewCalls = 0;
  const oldMessage: ChatMessage = {
    id: "user-1",
    role: "user",
    text: "旧消息",
    createdAt: "2026-07-07T10:00:00Z",
    state: "done",
  };
  const newMessage: ChatMessage = {
    id: "assistant-2",
    role: "assistant",
    text: "自动出现的新回复",
    createdAt: "2026-07-07T10:00:05Z",
    state: "done",
  };
  const listMessageDelta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({
    reset: false,
    items: [newMessage],
  }));
  const client = createClient({
    getBotOverview: vi.fn(async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      historyCount: overviewCalls++ === 0 ? 1 : 2,
    })),
    listMessages: vi.fn(async () => [oldMessage]),
    listMessageDelta,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText("旧消息")).toBeInTheDocument();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });

  expect(screen.getByText("自动出现的新回复")).toBeInTheDocument();
  expect(listMessageDelta).toHaveBeenCalledWith("main", "user-1", 50);
});

test("virtualizes expanded 500-message history", async () => {
  const user = userEvent.setup();
  const client = createClient({
    listMessages: async () => createChatHistoryFixture({ messageCount: 500 }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "展开较早消息（420）" }));
  const list = await screen.findByTestId("virtualized-chat-message-list");

  await waitFor(() => {
    const mountedRows = within(list).queryAllByTestId("chat-message-row");
    expect(mountedRows.length).toBeGreaterThan(0);
    expect(mountedRows.length).toBeLessThanOrEqual(35);
  });
});

test("recovers stalled SSE with revision delta and never reloads full history", async () => {
  let overviewCalls = 0;
  let historyCalls = 0;
  let requestSignal: AbortSignal | undefined;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((
    _botAlias,
    _text,
    _onChunk,
    _onStatus,
    _onTrace,
    options,
  ) => {
    requestSignal = options?.signal;
    return new Promise<ChatMessage>(() => {});
  });
  const listMessageDelta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({
    reset: false,
    revision: 4,
    items: [
      {
        id: "user-history-stalled",
        role: "user",
        text: "公网缓冲",
        createdAt: "2026-07-07T10:00:00Z",
        state: "done",
      },
      {
        id: "assistant-history-stalled",
        role: "assistant",
        text: "历史恢复的最终回复",
        createdAt: "2026-07-07T10:00:05Z",
        state: "done",
      },
    ],
  }));
  const listMessages = vi.fn(async (): Promise<ChatMessage[]> => {
    historyCalls += 1;
    return [];
  });
  const client = createClient({
    getBotOverview: vi.fn(async (): Promise<BotOverview> => {
      overviewCalls += 1;
      return {
        alias: "main",
        cliType: "codex",
        status: "running",
        workingDir: "C:\\workspace",
        isProcessing: overviewCalls > 1,
      };
    }),
    listMessages,
    listMessageDelta,
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "公网缓冲" } });
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await Promise.resolve();
  });
  expect(sendMessage).toHaveBeenCalled();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500);
    await Promise.resolve();
  });

  expect(screen.getByText("历史恢复的最终回复")).toBeInTheDocument();
  expect(requestSignal?.aborted).toBe(true);
  expect(screen.getByRole("button", { name: "终止任务" })).toBeEnabled();
  expect(listMessageDelta).toHaveBeenCalledTimes(1);
  expect(listMessages).toHaveBeenCalledTimes(1);
  expect(historyCalls).toBe(1);
});

test("shows send errors only in assistant bubble when placeholder exists", async () => {
  const user = userEvent.setup();
  const client = createClient({
    sendMessage: async () => {
      throw new Error("CLI 失败");
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "触发错误");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findByText("CLI 失败")).toBeInTheDocument();
  expect(screen.queryByTestId("chat-error-banner")).not.toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
});

test("hides duplicate final error text in transcript when assistant bubble already shows it", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-error-dup",
        role: "assistant",
        text: "Selected model is at capacity. Please try a different model.",
        createdAt: new Date().toISOString(),
        state: "error",
        meta: {
          tracePresentation: "native_agent_flat",
          trace: [
            { kind: "error", summary: "Selected model is at capacity. Please try a different model.", source: "codex" },
          ],
          traceCount: 1,
          processCount: 1,
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("Selected model is at capacity. Please try a different model.")).toBeInTheDocument();
  expect(screen.queryByTestId("chat-error-banner")).not.toBeInTheDocument();
  expect(within(transcript).getAllByText("Selected model is at capacity. Please try a different model.")).toHaveLength(1);
});

test("hides duplicate CLI exit-code error text when final message includes the diagnostic prefix", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-cli-error-prefix-dup",
        role: "assistant",
        text: "错误信息",
        createdAt: new Date().toISOString(),
        state: "error",
        meta: {
          trace: [
            { kind: "error", summary: "命令退出码 1\n错误信息", source: "runtime" },
          ],
          traceCount: 1,
          processCount: 1,
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("错误信息")).toBeInTheDocument();
  expect(transcript).not.toHaveTextContent("命令退出码 1");
  expect(transcript.textContent?.match(/错误信息/g) || []).toHaveLength(1);
});

test("hides duplicate CLI error text when final message already includes exit-code prefix", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-cli-error-new-format",
        role: "assistant",
        text: "命令退出码 1\n错误信息",
        createdAt: new Date().toISOString(),
        state: "error",
        meta: {
          trace: [
            { kind: "error", summary: "命令退出码 1\n错误信息", source: "runtime" },
          ],
          traceCount: 1,
          processCount: 1,
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(transcript.textContent?.match(/命令退出码 1/g) || []).toHaveLength(1);
  expect(transcript.textContent?.match(/错误信息/g) || []).toHaveLength(1);
});

test("keeps the scroll position after dragging the scrollbar away from the bottom", async () => {
  class TestResizeObserver {
    static instances: TestResizeObserver[] = [];
    target: Element | null = null;

    constructor(readonly callback: ResizeObserverCallback) {
      TestResizeObserver.instances.push(this);
    }

    observe(target: Element) {
      this.target = target;
    }

    disconnect() {
      this.target = null;
    }

    unobserve() {}
  }

  vi.stubGlobal("ResizeObserver", TestResizeObserver);
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
  render(<ChatScreen botAlias="main" client={createClient()} />);
  await screen.findByText("暂无消息，开始聊天吧");

  const container = screen.getByTestId("chat-scroll-container");
  const content = screen.getByTestId("chat-scroll-content");
  let scrollTop = 900;
  Object.defineProperties(container, {
    clientHeight: { configurable: true, get: () => 100 },
    scrollHeight: { configurable: true, get: () => 1_000 },
    scrollTop: {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => { scrollTop = value; },
    },
  });

  fireEvent.scroll(container);
  scrollTop = 500;
  fireEvent.scroll(container);

  const contentObserver = TestResizeObserver.instances.find((observer) => observer.target === content);
  expect(contentObserver).toBeDefined();
  act(() => {
    contentObserver?.callback(
      [{ target: content, contentRect: { height: 600 } } as unknown as ResizeObserverEntry],
      contentObserver as unknown as ResizeObserver,
    );
  });

  expect(scrollTop).toBe(500);
});

test("shows final answer actions for failed assistant messages", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "assistant-after-error-continue",
    role: "assistant",
    text: "继续后的回答",
    createdAt: new Date().toISOString(),
    state: "done",
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-error-actions",
        role: "assistant",
        text: "错误信息",
        createdAt: new Date().toISOString(),
        state: "error",
        meta: {
          contextUsage: {
            provider: "codex",
            contextUsed: 36565,
            contextWindow: 1000000,
            contextLeftPercent: 74,
            usedDisplay: "36.6K",
            windowDisplay: "1M",
          },
        },
      },
    ],
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("错误信息")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "复制最终回答" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "复制上下文详情" })).toBeInTheDocument();
  expect(await screen.findByTestId("chat-message-context-usage-bottom")).toHaveTextContent("ctx 74%");
  expect(screen.getAllByRole("button", { name: "继续" })).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "收藏回答" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "继续" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][1]).toBe("继续");
});

test("shows final answer actions for failed CLI transcript messages", async () => {
  const user = userEvent.setup();
  const writeText = mockClipboardWrite();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "assistant-after-cli-error-continue",
    role: "assistant",
    text: "继续后的回答",
    createdAt: new Date().toISOString(),
    state: "done",
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-cli-error-actions",
        role: "assistant",
        text: "命令退出码 1\n错误信息",
        createdAt: new Date().toISOString(),
        state: "error",
        meta: {
          trace: [
            { kind: "error", summary: "命令退出码 1\n错误信息", source: "runtime" },
          ],
          traceCount: 1,
          processCount: 1,
          contextUsage: {
            provider: "codex",
            contextUsed: 36565,
            contextWindow: 1000000,
            contextLeftPercent: 74,
            usedDisplay: "36.6K",
            windowDisplay: "1M",
          },
        },
      },
    ],
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(transcript).toHaveTextContent("命令退出码 1错误信息");
  expect(await screen.findByRole("button", { name: "复制最终回答" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "复制上下文详情" })).toBeInTheDocument();
  expect(await screen.findByTestId("chat-message-context-usage-bottom")).toHaveTextContent("ctx 74%");
  expect(screen.getAllByRole("button", { name: "继续" })).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "收藏回答" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "复制完整回答" }));
  const lastCopyCall = writeText.mock.calls.at(-1) as unknown[] | undefined;
  expect(String(lastCopyCall?.[0] ?? "")).toBe("[最终回答]\n命令退出码 1\n错误信息");

  await user.click(screen.getByRole("button", { name: "继续" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][1]).toBe("继续");
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

test("uses cli status preview while waiting for first output chunk", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    _onChunk,
    onStatus,
  ) => {
    onStatus?.({ previewText: "正在检查目录" });
    return new Promise<ChatMessage>((resolve) => {
      resolveFinal = resolve;
    });
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(screen.queryByText("正在检查目录")).not.toBeInTheDocument();
  expect(screen.getByText("正在输出...")).toBeInTheDocument();

  await act(async () => {
    resolveFinal({
      id: "assistant-preview-final",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
    });
  });
  expect(await screen.findByText("最终答复")).toBeInTheDocument();
});

test("renders live cli trace without temporary answer while streaming", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    onChunk,
    _onStatus,
    onTrace,
  ) => {
    onChunk("正文先出");
    onTrace?.({
      kind: "tool_call",
      summary: "Get-ChildItem",
      toolName: "shell_command",
      callId: "call-1",
    });
    return new Promise<ChatMessage>((resolve) => {
      resolveFinal = resolve;
    });
  });
  const client = createClient({
    sendMessage,
    getMessageTrace: vi.fn(async () => ({
      trace: [
        { kind: "tool_call", summary: "Get-ChildItem", toolName: "shell_command", callId: "call-1" },
      ],
      traceCount: 1,
      toolCallCount: 1,
      processCount: 0,
    })) as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).queryByText("正文先出")).not.toBeInTheDocument();
  expect(within(transcript).getByText("shell_command")).toBeInTheDocument();
  expect(within(transcript).queryByTestId("native-agent-final-result")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "复制最终回答" })).not.toBeInTheDocument();
  expect(screen.getByTestId("native-agent-streaming-status")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "展开过程详情" })).not.toBeInTheDocument();

  await act(async () => {
    resolveFinal({
      id: "assistant-stream-mid-trace",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
    });
  });
});

test("plain cli streaming text waits for done before rendering answer", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (_botAlias, _text, onChunk) => {
    onChunk("临时正文");
    return new Promise<ChatMessage>((resolve) => {
      resolveFinal = resolve;
    });
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(screen.queryByText("临时正文")).not.toBeInTheDocument();
  expect(screen.getByText("正在输出...")).toBeInTheDocument();

  await act(async () => {
    resolveFinal({
      id: "assistant-plain-cli-final",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
    });
  });

  expect(await screen.findByText("最终答复")).toBeInTheDocument();
});

test("renders live cli trace as transcript after final message", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      { kind: "commentary", summary: "我先检查目录。", source: "codex" },
      {
        kind: "tool_call",
        summary: "Get-ChildItem",
        toolName: "shell_command",
        callId: "call-1",
        payload: { arguments: "Get-ChildItem" },
      },
      {
        kind: "tool_result",
        summary: "Exit code: 0",
        callId: "call-1",
        payload: { output: "Exit code: 0" },
      },
      { kind: "commentary", summary: "继续整理结果。", source: "codex" },
      { kind: "commentary", summary: "完成。", source: "codex" },
    ],
    traceCount: 5,
    toolCallCount: 1,
    processCount: 5,
  }));
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    _onChunk,
    _onStatus,
    onTrace,
  ) => {
    onTrace?.({
      kind: "commentary",
      summary: "我先检查目录。",
      source: "codex",
    });
    return new Promise<ChatMessage>((resolve) => {
      resolveFinal = resolve;
    });
  });
  const client = createClient({ sendMessage, getMessageTrace: getMessageTrace as never });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  const liveTranscript = await screen.findByTestId("native-agent-transcript");
  expect(within(liveTranscript).getAllByText("我先检查目录。").length).toBeGreaterThan(0);
  expect(liveTranscript.closest("[data-streaming='true']")).not.toHaveClass("chat-message-bubble-delight");
  expect(screen.queryByRole("button", { name: "展开过程详情" })).not.toBeInTheDocument();

  await act(async () => {
    resolveFinal({
      id: "assistant-cli-final",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: { traceCount: 5, toolCallCount: 1, processCount: 5 },
    });
  });

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("最终答复")).toBeInTheDocument();
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-cli-final"));
  expect(await within(transcript).findByText("shell_command")).toBeInTheDocument();
  expect(within(transcript).getAllByText("Exit code: 0").length).toBeGreaterThan(0);
  expect(within(transcript).getAllByText("我先检查目录。").length).toBeGreaterThan(0);
});

test("keeps live cli trace when done omits trace payload", async () => {
  const user = userEvent.setup();
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      { kind: "commentary", summary: "我先检查目录。", source: "codex" },
    ],
    traceCount: 1,
    toolCallCount: 0,
    processCount: 1,
  }));
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    onChunk,
    _onStatus,
    onTrace,
  ) => {
    onChunk("正文先出");
    onTrace?.({
      kind: "commentary",
      summary: "我先检查目录。",
      source: "codex",
    });
    await new Promise((resolve) => window.setTimeout(resolve, 200));
    return {
      id: "assistant-cli-final-no-trace",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: { traceCount: 1, toolCallCount: 0, processCount: 1 },
    };
  });
  const client = createClient({ sendMessage, getMessageTrace: getMessageTrace as never });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).queryByText("正文先出")).not.toBeInTheDocument();
  expect(within(transcript).getByText("我先检查目录。")).toBeInTheDocument();
  expect(screen.getByTestId("native-agent-streaming-status")).toBeInTheDocument();
  expect(getMessageTrace).not.toHaveBeenCalled();
});

test("keeps authoritative final cli trace count when live trace matches final trace", async () => {
  const user = userEvent.setup();
  const finalTrace = { kind: "commentary", summary: "我先检查目录。", rawType: "message", source: "codex" };
  const getMessageTrace = vi.fn(async () => ({
    trace: [],
    traceCount: 0,
    toolCallCount: 0,
    processCount: 0,
  }));
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias,
    _text,
    _onChunk,
    _onStatus,
    onTrace,
  ) => {
    onTrace?.(finalTrace);
    return {
      id: "assistant-cli-authoritative-final",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: {
        trace: [finalTrace],
        traceCount: 1,
        toolCallCount: 0,
        processCount: 1,
      },
    };
  });
  const client = createClient({ sendMessage, getMessageTrace: getMessageTrace as never });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("最终答复")).toBeInTheDocument();
  expect(within(transcript).getByText("我先检查目录。")).toBeInTheDocument();
  expect(getMessageTrace).not.toHaveBeenCalled();
});

test("final resolved assistant message does not keep streaming state", async () => {
  const client = createClient({
    sendMessage: async () => ({
      id: "assistant-final-streaming",
      role: "assistant",
      text: "已完成",
      createdAt: new Date().toISOString(),
      state: "streaming",
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  const finalText = await screen.findByText("已完成");
  expect(finalText.closest("[data-streaming]")).toHaveAttribute("data-streaming", "false");
  expect(screen.queryByText("正在输出...")).not.toBeInTheDocument();
});

test("replaces snapshot text and appends later stream chunks", async () => {
  let resolveFinal!: (message: ChatMessage) => void;
  const client = createClient({
    sendMessage: async (
      _botAlias: string,
      _text: string,
      onChunk: (chunk: string) => void,
      onStatus?: (status: { replaceText?: string }) => void,
    ) => {
      onChunk("先查一下...");
      onStatus?.({ replaceText: "" });
      onChunk("最终答复");
      return new Promise<ChatMessage>((resolve) => {
        resolveFinal = resolve;
      });
    },
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "查");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(screen.queryByText("最终答复")).not.toBeInTheDocument();
  expect(screen.getByText("正在输出...")).toBeInTheDocument();
  expect(screen.queryByText("先查一下...最终答复")).not.toBeInTheDocument();
  await act(async () => {
    resolveFinal({
      id: "assistant-snapshot",
      role: "assistant",
      text: "最终答复",
      createdAt: new Date().toISOString(),
      state: "done",
    });
  });
  expect(await screen.findByText("最终答复")).toBeInTheDocument();
});

test("uses full width chat content outside embedded workbench", async () => {
  render(<ChatScreen botAlias="main" client={createClient()} />);

  expect(await screen.findByTestId("chat-scroll-content")).toHaveClass("w-full");
  expect(screen.getByTestId("chat-scroll-content")).not.toHaveClass("max-w-5xl");
});

test("keeps embedded chat content capped", async () => {
  render(<ChatScreen botAlias="main" client={createClient()} embedded />);

  expect(await screen.findByTestId("chat-scroll-content")).toHaveClass("max-w-5xl");
});

test("toggles mobile immersive mode from the floating button", async () => {
  const onToggleImmersive = vi.fn();
  render(<ChatScreen botAlias="main" client={createClient()} onToggleImmersive={onToggleImmersive} />);

  await screen.findByText("暂无消息，开始聊天吧");
  await userEvent.click(screen.getByRole("button", { name: "进入沉浸模式" }));

  expect(onToggleImmersive).toHaveBeenCalledTimes(1);
});

test("lets the mobile immersive button move without triggering toggle", async () => {
  const onToggleImmersive = vi.fn();
  window.localStorage.setItem("tcb.chatImmersiveButton.main", JSON.stringify({ x: 296, y: 512 }));
  render(<ChatScreen botAlias="main" client={createClient()} onToggleImmersive={onToggleImmersive} />);

  await screen.findByText("暂无消息，开始聊天吧");
  const button = screen.getByRole("button", { name: "进入沉浸模式" });
  const chatRoot = button.closest("main");
  expect(chatRoot).not.toBeNull();
  vi.spyOn(chatRoot as HTMLElement, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 360,
    bottom: 640,
    width: 360,
    height: 640,
    toJSON: () => ({}),
  } as DOMRect);

  fireEvent.pointerDown(button, { pointerId: 1, pointerType: "touch", clientX: 296, clientY: 512 });
  fireEvent.pointerMove(button, { pointerId: 1, pointerType: "touch", clientX: 216, clientY: 252 });
  fireEvent.pointerUp(button, { pointerId: 1, pointerType: "touch", clientX: 216, clientY: 252 });
  fireEvent.click(button);

  expect(onToggleImmersive).not.toHaveBeenCalled();
  expect(button).toHaveStyle({ transform: "translate3d(216px, 252px, 0)" });
  expect(JSON.parse(window.localStorage.getItem("tcb.chatImmersiveButton.main") || "{}")).toEqual({
    x: 216,
    y: 252,
  });
});

test("toggles on the first tap after moving the mobile immersive button", async () => {
  const onToggleImmersive = vi.fn();
  window.localStorage.setItem("tcb.chatImmersiveButton.main", JSON.stringify({ x: 296, y: 512 }));
  render(<ChatScreen botAlias="main" client={createClient()} onToggleImmersive={onToggleImmersive} />);

  await screen.findByText("暂无消息，开始聊天吧");
  const button = screen.getByRole("button", { name: "进入沉浸模式" });
  const chatRoot = button.closest("main");
  expect(chatRoot).not.toBeNull();
  vi.spyOn(chatRoot as HTMLElement, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 360,
    bottom: 640,
    width: 360,
    height: 640,
    toJSON: () => ({}),
  } as DOMRect);

  fireEvent.pointerDown(button, { pointerId: 1, pointerType: "touch", clientX: 296, clientY: 512 });
  fireEvent.pointerMove(button, { pointerId: 1, pointerType: "touch", clientX: 216, clientY: 252 });
  fireEvent.pointerUp(button, { pointerId: 1, pointerType: "touch", clientX: 216, clientY: 252 });
  await userEvent.click(button);

  expect(onToggleImmersive).toHaveBeenCalledTimes(1);
});

test("shows read only reason and disables composer", async () => {
  render(
    <ChatScreen
      botAlias="main"
      client={createClient()}
      readOnly
      disabledReason="主机已关闭聊天，当前无法发送消息"
    />,
  );

  expect(await screen.findAllByText("主机已关闭聊天，当前无法发送消息")).toHaveLength(2);
  expect(screen.getByPlaceholderText("主机已关闭聊天，当前无法发送消息")).toBeDisabled();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
});

test("copies final answer using execCommand fallback when clipboard api is unavailable", async () => {
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(() => true),
  });
  const execCommand = vi.spyOn(document, "execCommand");
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(globalThis.navigator, "clipboard", {
    configurable: true,
    value: undefined,
  });
  const client = createClient({
    listMessages: async () => [{
      id: "assistant-copy",
      role: "assistant",
      text: "最终答案",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: {
        trace: [{ kind: "commentary", summary: "完成。", source: "codex" }],
        traceCount: 1,
        toolCallCount: 0,
        processCount: 1,
      },
    }],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const copyButton = await screen.findByRole("button", { name: "复制最终回答" });
  const finalResult = await screen.findByTestId("native-agent-final-result");
  const finalAnswer = within(finalResult).getByText("最终答案");
  expect(finalAnswer.compareDocumentPosition(copyButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  await userEvent.click(copyButton);

  expect(execCommand).toHaveBeenCalledWith("copy");
  expect(await screen.findByRole("button", { name: "已复制最终回答" })).toBeInTheDocument();
});

test("favorites final answers through backend and restores from server", async () => {
  const now = new Date().toISOString();
  const favoriteItems: FavoriteAnswerItem[] = [];
  const favoriteAnswer = vi.fn<WebBotClient["favoriteAnswer"]>(async (_botAlias, input) => {
    const item: FavoriteAnswerItem = {
      id: "fav-assistant-favorite",
      botId: 1,
      botAlias: "main",
      userId: 1,
      agentId: "main",
      executionMode: "cli",
      conversationId: input.conversationId,
      messageId: input.messageId,
      messageKey: input.messageKey,
      turnId: input.turnId || "",
      title: input.title || "测试会话",
      preview: input.preview || "",
      answerText: input.answerText || "",
      createdAt: now,
      favoritedAt: now,
    };
    favoriteItems.splice(0, favoriteItems.length, item);
    return item;
  });
  const client = createClient({
    listFavoriteAnswers: async () => ({ items: [...favoriteItems], executionMode: "cli" }),
    favoriteAnswer,
    listMessages: async () => [{
      id: "assistant-favorite",
      conversationId: "conv-favorite",
      role: "assistant",
      text: "值得收藏的答案",
      createdAt: now,
      state: "done",
    }],
    listConversations: async () => ({
      activeConversationId: "conv-favorite",
      items: [{
        id: "conv-favorite",
        title: "测试会话",
        lastMessagePreview: "值得收藏的答案",
        messageCount: 1,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: now,
        updatedAt: now,
      }],
    }),
  });

  const { unmount } = render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("值得收藏的答案")).toBeInTheDocument();
  const favoriteButton = screen.getByRole("button", { name: "收藏回答" });
  await userEvent.click(favoriteButton);

  expect(await screen.findByRole("button", { name: "取消收藏回答" })).toHaveAttribute("aria-pressed", "true");
  await waitFor(() => expect(favoriteAnswer).toHaveBeenCalled());
  expect(favoriteAnswer.mock.calls[0][1]).toMatchObject({
    conversationId: "conv-favorite",
    messageId: "assistant-favorite",
    messageKey: "assistant|assistant-favorite",
  });

  unmount();
  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("值得收藏的答案")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消收藏回答" })).toHaveAttribute("aria-pressed", "true");
});

test("opens favorites panel from history sheet", async () => {
  const now = new Date().toISOString();
  const client = createClient({
    listFavoriteAnswers: async () => ({
      executionMode: "cli",
      items: [{
        id: "fav-toolbar",
        botId: 1,
        botAlias: "main",
        userId: 1,
        agentId: "main",
        executionMode: "cli",
        conversationId: "conv-toolbar",
        messageId: "msg-toolbar",
        messageKey: "assistant|msg-toolbar",
        turnId: "turn-toolbar",
        title: "工具栏收藏",
        preview: "收藏预览",
        answerText: "收藏预览",
        createdAt: now,
        favoritedAt: now,
      }],
    }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await userEvent.click(await screen.findByRole("button", { name: "历史会话" }));
  await userEvent.click(await screen.findByRole("button", { name: "收藏" }));

  expect(await screen.findByRole("button", { name: "收藏", pressed: true })).toBeInTheDocument();
  expect(await screen.findByText("工具栏收藏")).toBeInTheDocument();
  expect(screen.getByText("收藏预览")).toBeInTheDocument();
});

test("continues from the latest final answer", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (_botAlias, text, onChunk) => {
    onChunk(`收到：${text}`);
    return {
      id: "assistant-continued",
      role: "assistant",
      text: `收到：${text}`,
      createdAt: now,
      state: "done",
    };
  });
  const client = createClient({
    listMessages: async () => [
      {
        id: "assistant-old",
        role: "assistant",
        text: "旧回答",
        createdAt: now,
        state: "done",
      },
      {
        id: "assistant-latest",
        role: "assistant",
        text: "最新回答",
        createdAt: now,
        state: "done",
      },
    ],
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最新回答")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "继续" })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "继续" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][1]).toBe("继续");
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ taskMode: "standard" });
});

test("renders prompt preset editor in a high level document portal", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      promptPresets: [{ id: "p1", title: "修复", content: "请修复" }],
      effectiveCapabilities: ["admin_ops"],
    } as BotOverview),
  });

  const { container } = render(<ChatScreen botAlias="main" client={client} />);
  await userEvent.click(await screen.findByRole("button", { name: "打开提示词预设" }));
  await userEvent.click(screen.getByRole("button", { name: "配置预设" }));

  const dialog = await screen.findByRole("dialog", { name: "配置提示词预设" });
  const backdrop = dialog.parentElement;
  expect(container).not.toContainElement(dialog);
  expect(document.body).toContainElement(dialog);
  expect(backdrop).toHaveClass("z-[1000]");
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
        reasoningEfforts: { low: "", medium: "", high: "" },
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

test("native agent mode shows cluster entry and sends cluster options", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias: string,
    _text: string,
    onChunk: (chunk: string) => void,
  ): Promise<ChatMessage> => {
    onChunk("原生集群回复");
    return {
      id: "assistant-native-cluster",
      role: "assistant",
      text: "原生集群回复",
      createdAt: new Date().toISOString(),
      state: "done",
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
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "gpt-low", medium: "gpt-mid", high: "gpt-high" },
        reasoningEfforts: { low: "", medium: "", high: "" },
      },
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "tester", name: "测试专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "关闭集群模式" })).toBeInTheDocument();
  const input = screen.getByPlaceholderText("@ 可指定智能体集群");
  await user.type(input, "跑测试");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][5]).toMatchObject({
    executionMode: "native_agent",
    cluster: true,
    mentions: [],
  });
});

test("native agent @mention sends cluster options", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias: string,
    _text: string,
    onChunk: (chunk: string) => void,
  ): Promise<ChatMessage> => {
    onChunk("原生点名回复");
    return {
      id: "assistant-native-mention",
      role: "assistant",
      text: "原生点名回复",
      createdAt: new Date().toISOString(),
      state: "done",
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
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "gpt-low", medium: "gpt-mid", high: "gpt-high" },
        reasoningEfforts: { low: "", medium: "", high: "" },
      },
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "tester", name: "测试专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "关闭集群模式" })).toBeInTheDocument();
  const input = screen.getByPlaceholderText("@ 可指定智能体集群");
  await user.type(input, "@tester 跑测试");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][5]).toMatchObject({
    executionMode: "native_agent",
    cluster: true,
    mentions: [{ agentId: "tester", label: "测试专家", start: 0, end: 7 }],
  });
});








test("auto-loads trace details and groups tool call/result into transcript", async () => {
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
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-1"));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(await within(transcript).findByText("我先检查目录结构。")).toBeInTheDocument();
  expect(within(transcript).getByText("Get-Content -Path todo.txt")).toBeInTheDocument();
  expect(transcript.textContent).toContain("Exit code: 1");
  expect(transcript.textContent).toContain("Wall time: 1.3 seconds");
  expect(within(transcript).getByText("同步事件已记录。")).toBeInTheDocument();
  expect(within(transcript).getAllByText("目录已读取完成。").length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: "展开过程详情" })).not.toBeInTheDocument();
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
    listMessages: async (): Promise<ChatMessage[]> => [
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
            payload: {
              id: "perm-1",
              state: "permission.updated",
            },
          }],
        },
      },
    ],
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

test("native history auto-loads flat trace details", async () => {
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
    listMessages: async (): Promise<ChatMessage[]> => [
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
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-native-history"));
  expect(await within(transcript).findByText("我先检查目录结构。")).toBeInTheDocument();
  const eventGroup = within(transcript).getByTestId("native-agent-event-group");
  expect(eventGroup.textContent).toContain("过程 1");
  expect(eventGroup.textContent).toContain("2 条事件 · 1 次工具");
  expect(eventGroup.textContent).not.toContain("我先检查目录结构。");
  expect(eventGroup.textContent).toContain("shell_command");
  expect(eventGroup.textContent).toContain("Exit code: 0");
  expect(within(transcript).getAllByText("shell_command").length).toBeGreaterThan(0);
  expect(within(transcript).getAllByText("Exit code: 0").length).toBeGreaterThan(0);
  expect(within(transcript).getByTestId("native-agent-final-result").textContent).toContain("最终答复");
  expect(screen.queryByRole("button", { name: "展开过程详情" })).not.toBeInTheDocument();
});

test("native history folds duplicate tool results and keeps commentary in trace order", async () => {
  const getMessageTrace = vi.fn(async () => ({
    trace: [
      {
        kind: "tool_call",
        ordinal: 2,
        source: "native_agent",
        toolName: "shell_command",
        callId: "call-1",
        summary: "Get-ChildItem",
        payload: { arguments: "Get-ChildItem" },
      },
      {
        kind: "tool_result",
        ordinal: 3,
        source: "native_agent",
        callId: "call-1",
        summary: "partial",
        payload: { output: "partial" },
      },
      {
        kind: "commentary",
        ordinal: 4,
        source: "native_agent",
        rawType: "message.text.reclassified",
        summary: "我先检查目录结构。",
      },
      {
        kind: "tool_result",
        ordinal: 5,
        source: "native_agent",
        callId: "call-1",
        summary: "final",
        payload: { output: "final" },
      },
    ],
    traceCount: 4,
    toolCallCount: 1,
    processCount: 2,
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-native-history",
        role: "assistant",
        text: "最终答复",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          tracePresentation: "native_agent_flat",
          nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
          traceCount: 4,
          toolCallCount: 1,
          processCount: 2,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledWith("main", "assistant-native-history"));
  const firstVisibleRow = transcript.firstElementChild as HTMLElement | null;
  expect(firstVisibleRow?.textContent).toContain("Get-ChildItem");
  expect(within(transcript).queryByText("partial")).not.toBeInTheDocument();
  expect(within(transcript).getByText("我先检查目录结构。")).toBeInTheDocument();
  expect(within(transcript).getAllByText("final").length).toBeGreaterThan(0);
});

test("native history trace auto-load does not retry immediately after failure", async () => {
  const getMessageTrace = vi.fn(async () => {
    throw new Error("trace unavailable");
  });
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-native-history-error",
        role: "assistant",
        text: "最终答复",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          tracePresentation: "native_agent_flat",
          nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
          traceCount: 3,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await screen.findByTestId("native-agent-transcript");
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledTimes(1));
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 20));
  });
  expect(getMessageTrace).toHaveBeenCalledTimes(1);
});

test("non-native history trace auto-load does not retry immediately after failure", async () => {
  const getMessageTrace = vi.fn(async () => {
    throw new Error("trace unavailable");
  });
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-history-error",
        role: "assistant",
        text: "最终答复",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          traceCount: 3,
          toolCallCount: 0,
          processCount: 3,
        },
      },
    ],
    getMessageTrace: getMessageTrace as never,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("最终答复")).toBeInTheDocument();
  expect(await screen.findByTestId("native-agent-transcript")).toBeInTheDocument();
  await waitFor(() => expect(getMessageTrace).toHaveBeenCalledTimes(1));
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 20));
  });
  expect(getMessageTrace).toHaveBeenCalledTimes(1);
});

test("non-native permission trace hides native permission actions", async () => {
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
    listMessages: async (): Promise<ChatMessage[]> => [
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
            payload: {
              id: "perm-1",
              state: "permission.updated",
            },
          }],
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("CLI 请求确认")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "允许一次" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
});

test("user message does not show native transcript entry", async () => {
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "user-1",
        role: "user",
        text: "hi",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          tracePresentation: "native_agent_flat",
          nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
          traceCount: 1,
          trace: [{
            kind: "commentary",
            summary: "不应显示",
            source: "native_agent",
          }],
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("hi")).toBeInTheDocument();
  expect(screen.queryByTestId("native-agent-transcript")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "展开过程详情" })).not.toBeInTheDocument();
  expect(screen.queryByText("不应显示")).not.toBeInTheDocument();
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

test("live non-native ag-ui session error stays in regular error bubble", async () => {
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
    onAgUiEvent?.({ type: EventType.RUN_ERROR, message: "Pi failed", code: "session.error" });
    return {
      id: "assistant-error",
      role: "assistant",
      text: "Pi failed",
      createdAt: new Date().toISOString(),
      state: "error",
    };
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(await screen.findByText("Pi failed")).toBeInTheDocument();
  expect(screen.queryByTestId("native-agent-transcript")).not.toBeInTheDocument();
});


test("live ag-ui stream renders flat transcript and final result last", async () => {
  const user = userEvent.setup();
  const writeText = mockClipboardWrite();
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
    onAgUiEvent?.({ type: EventType.REASONING_START, messageId: "reason-1" });
    onAgUiEvent?.({ type: EventType.REASONING_MESSAGE_CONTENT, messageId: "reason-1", delta: "检查上下文" });
    onAgUiEvent?.({ type: EventType.REASONING_END, messageId: "reason-1" });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_START, toolCallId: "tool-1", toolCallName: "shell_command" });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_ARGS, toolCallId: "tool-1", delta: "{\"command\":\"dir\"}" });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_RESULT, messageId: "tool-result-1", toolCallId: "tool-1", content: "Exit code: 0" });
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
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("运行中")).toBeInTheDocument();
  expect(within(transcript).getByText("检查上下文")).toBeInTheDocument();
  const eventGroup = within(transcript).getByTestId("native-agent-event-group");
  expect(eventGroup.textContent).toContain("过程 1");
  expect(eventGroup.textContent).toContain("4 条事件 · 1 次工具");
  expect(eventGroup.textContent).toContain("检查上下文");
  expect(eventGroup.textContent).toContain("shell_command");
  expect(eventGroup.textContent).toContain("Exit code: 0");
  expect(within(transcript).getAllByText("shell_command").length).toBeGreaterThan(0);
  expect(within(transcript).getAllByText("Exit code: 0").length).toBeGreaterThan(0);
  expect(within(transcript).getByTestId("native-agent-final-result").textContent).toContain("answer");
  expect(transcript.textContent?.trim().endsWith("answer")).toBe(true);
  expect(screen.queryByTestId("native-agent-run-timeline")).not.toBeInTheDocument();
  expect(screen.queryByTestId("chat-trace-panel-assistant-live")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "复制完整回答" }));
  const lastCopyCall = writeText.mock.calls.at(-1) as unknown[] | undefined;
  const copiedText = String(lastCopyCall?.[0] ?? "");
  expect(copiedText).toContain("[过程] 运行中");
  expect(copiedText).toContain("[思考] 检查上下文");
  expect(copiedText).toContain("[工具: shell_command] {\"command\":\"dir\"}");
  expect(copiedText).toContain("[工具结果] Exit code: 0");
  expect(copiedText).toContain("[最终回答]\n**answer**");
  expect(await screen.findByRole("button", { name: "已复制完整回答" })).toBeInTheDocument();
});

test("native send renders streaming transcript immediately without cli bubble chrome", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(() => new Promise<ChatMessage>((resolve) => {
    resolveFinal = resolve;
  }));
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(screen.getByTestId("native-agent-streaming-status")).toBeInTheDocument();
  const messageChrome = transcript.closest("[data-streaming='true']");
  expect(messageChrome).not.toHaveClass("chat-message-bubble-delight");

  await act(async () => {
    resolveFinal({
      id: "assistant-native-final",
      role: "assistant",
      text: "final answer",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: { tracePresentation: "native_agent_flat" },
    });
  });

  expect(screen.queryByTestId("native-agent-streaming-status")).not.toBeInTheDocument();
  expect(await screen.findByText("final answer")).toBeInTheDocument();
});

test("native ag-ui commentary is visible while stream is still running", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
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
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_START, messageId: "assistant-live", role: "assistant" });
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-live", delta: "我先读取文件。" });
    onAgUiEvent?.({
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [
        { id: "assistant-live", role: "assistant", content: "" },
      ],
    });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-trace-1",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        id: "activity-trace-1",
        summary: "我先读取文件。",
        source: "native_agent",
        rawKind: "commentary",
        rawType: "message.text.reclassified",
      },
    });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_START, toolCallId: "tool-1", toolCallName: "shell_command" });
    return new Promise<ChatMessage>((resolve) => {
      resolveFinal = resolve;
    });
  });
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("我先读取文件。")).toBeInTheDocument();
  expect(screen.getByTestId("native-agent-streaming-status")).toBeInTheDocument();

  await act(async () => {
    resolveFinal({
      id: "assistant-native-final",
      role: "assistant",
      text: "final answer",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: {
        tracePresentation: "native_agent_flat",
        nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
        trace: [{ kind: "commentary", summary: "我先读取文件。", source: "native_agent" }],
      },
    });
  });
});

test("native ag-ui delta commentary is visible while stream is still running", async () => {
  const user = userEvent.setup();
  let resolveFinal!: (message: ChatMessage) => void;
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
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_START, messageId: "assistant-live", role: "assistant" });
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-live", delta: "我先读取文件。" });
    onAgUiEvent?.({
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [
        { id: "assistant-live", role: "assistant", content: "" },
      ],
    });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-trace-1",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        id: "activity-trace-1",
        source: "native_agent",
        rawKind: "commentary",
        rawType: "message.text.reclassified",
      },
    });
    onAgUiEvent?.({
      type: EventType.ACTIVITY_DELTA,
      messageId: "activity-trace-1",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      patch: [
        { op: "add", path: "/summary", value: "我先读取文件。" },
      ],
    });
    onAgUiEvent?.({ type: EventType.TOOL_CALL_START, toolCallId: "tool-1", toolCallName: "shell_command" });
    return new Promise<ChatMessage>((resolve) => {
      resolveFinal = resolve;
    });
  });
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("我先读取文件。")).toBeInTheDocument();
  expect(screen.getByTestId("native-agent-streaming-status")).toBeInTheDocument();

  await act(async () => {
    resolveFinal({
      id: "assistant-native-final",
      role: "assistant",
      text: "final answer",
      createdAt: new Date().toISOString(),
      state: "done",
      meta: {
        tracePresentation: "native_agent_flat",
        nativeSource: { provider: "原生 agent", sessionId: "sess-1" },
        trace: [{ kind: "commentary", summary: "我先读取文件。", source: "native_agent" }],
      },
    });
  });
});

test("final ag-ui message replaces polluted live assistant text", async () => {
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
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_START, messageId: "assistant-live", role: "assistant" });
    onAgUiEvent?.({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-live", delta: "internal thinking" });
    return {
      id: "assistant-final",
      role: "assistant",
      text: "ok",
      createdAt: new Date().toISOString(),
      state: "done",
    };
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "回复 ok");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(await screen.findByText("ok")).toBeInTheDocument();
  expect(screen.queryByText("internal thinking")).not.toBeInTheDocument();
});


test("live ag-ui permission can be approved from flat transcript", async () => {
  const user = userEvent.setup();
  const replyNativeAgentPermission = vi.fn(async () => ({ permissionId: "perm-1", approved: true }));
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
      messageId: "activity-perm-1",
      activityType: "TCB_PERMISSION_REQUEST",
      replace: true,
      content: {
        id: "perm-1",
        permissionId: "perm-1",
        title: "允许读取文件？",
        state: "permission.updated",
        source: "native_agent",
      },
    });
    return {
      id: "assistant-perm",
      role: "assistant",
      text: "",
      createdAt: new Date().toISOString(),
      state: "streaming",
    };
  });
  const client = createClient({ sendMessage, replyNativeAgentPermission });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await user.click(await screen.findByRole("button", { name: "允许一次" }));

  await waitFor(() => expect(replyNativeAgentPermission).toHaveBeenCalledWith(
    "main",
    "perm-1",
    expect.objectContaining({ approved: true }),
  ));
  await waitFor(() => expect(screen.queryByRole("button", { name: "允许一次" })).not.toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  expect(await screen.findByText("原生 agent 权限已允许")).toBeInTheDocument();
});

test("live non-native permission activity hides native permission actions", async () => {
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
      messageId: "activity-perm-cli",
      activityType: "TCB_PERMISSION_REQUEST",
      replace: true,
      content: {
        id: "perm-cli",
        permissionId: "perm-cli",
        title: "CLI 请求确认",
        state: "permission.updated",
        source: "codex",
      },
    });
    return {
      id: "assistant-perm-cli",
      role: "assistant",
      text: "",
      createdAt: new Date().toISOString(),
      state: "streaming",
    };
  });
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: "允许一次" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  expect(screen.queryByTestId("native-agent-transcript")).not.toBeInTheDocument();
});


test("live ag-ui run error renders flat transcript error row", async () => {
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
    onAgUiEvent?.({ type: EventType.RUN_ERROR, message: "Pi failed", code: "session.error" });
    onAgUiEvent?.({ type: EventType.RUN_FINISHED, threadId: "thread-1", runId: "run-1", outcome: { type: "interrupt", interrupts: [] } });
    return {
      id: "assistant-error",
      role: "assistant",
      text: "",
      createdAt: new Date().toISOString(),
      state: "error",
    };
  });
  const client = createClient({
    getBotOverview: async (): Promise<BotOverview> => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  await user.type(screen.getByPlaceholderText("输入消息"), "hi");
  await user.click(screen.getByRole("button", { name: "发送" }));

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).getByText("Pi failed")).toBeInTheDocument();
  expect(screen.queryByTestId("native-agent-run-timeline")).not.toBeInTheDocument();
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

test("chat screen can delete all conversations for current bot", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  const favoriteItems: FavoriteAnswerItem[] = [{
    id: "fav-old",
    botId: 1,
    botAlias: "main",
    userId: 1,
    agentId: "main",
    executionMode: "cli",
    conversationId: "conv-1",
    messageId: "assistant-1",
    messageKey: "assistant|assistant-1",
    turnId: "",
    title: "旧会话",
    preview: "旧收藏",
    answerText: "旧收藏",
    createdAt: now,
    favoritedAt: now,
  }];
  const deleteAllConversations = vi.fn(async (): Promise<ConversationBulkDeleteResult> => {
    favoriteItems.splice(0, favoriteItems.length);
    return {
      deletedCount: 2,
      deletedFavoriteCount: 1,
      activeConversationId: "",
      nativeSessionCleared: true,
      items: [],
      messages: [],
    };
  });
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "旧消息",
      createdAt: now,
      state: "done",
    }],
    listConversations: async (): Promise<ConversationListResult> => ({
      activeConversationId: "conv-1",
      items: [{
        id: "conv-1",
        title: "旧会话",
        lastMessagePreview: "旧消息",
        messageCount: 2,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: now,
        updatedAt: now,
      }],
    }),
    listFavoriteAnswers: async () => ({
      executionMode: "cli",
      items: [...favoriteItems],
    }),
    deleteAllConversations,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("旧消息")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "历史会话" }));
  await user.click(await screen.findByRole("button", { name: "清空" }));
  await user.click(await screen.findByRole("button", { name: "删除" }));

  expect(deleteAllConversations).toHaveBeenCalledWith("main", { deleteNativeSession: true });
  expect(await screen.findByText("暂无消息，开始聊天吧")).toBeInTheDocument();
  expect(screen.queryByText("旧会话")).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "历史会话" }));
  await user.click(await screen.findByRole("button", { name: "收藏" }));
  expect(await screen.findByText("暂无收藏")).toBeInTheDocument();
  expect(screen.queryByText("旧收藏")).not.toBeInTheDocument();
});

test("chat screen history panel no longer exposes permanent conversation delete", async () => {
  const user = userEvent.setup();
  const now = new Date().toISOString();
  const deleteAllConversations = vi.fn(async (): Promise<ConversationBulkDeleteResult> => ({
    deletedCount: 1,
    deletedFavoriteCount: 0,
    activeConversationId: "",
    nativeSessionCleared: true,
    items: [],
    messages: [],
  }));
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-1",
      role: "assistant",
      text: "旧消息",
      createdAt: now,
      state: "done",
    }],
    listConversations: async (): Promise<ConversationListResult> => ({
      activeConversationId: "conv-1",
      items: [{
        id: "conv-1",
        title: "旧会话",
        lastMessagePreview: "旧消息",
        messageCount: 2,
        pinned: false,
        active: true,
        status: "active",
        botAlias: "main",
        cliType: "codex",
        workingDir: "C:\\workspace",
        createdAt: now,
        updatedAt: now,
      }],
    }),
    deleteAllConversations,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.click(screen.getByRole("button", { name: "历史会话" }));

  expect(await screen.findByRole("button", { name: "清空" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "彻底删除" })).not.toBeInTheDocument();
  expect(deleteAllConversations).not.toHaveBeenCalled();
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

test("sends native agent execution mode from action bar", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias: string,
    _text: string,
    onChunk: (chunk: string) => void,
  ): Promise<ChatMessage> => {
    onChunk("原生回复");
    return {
      id: "assistant-native",
      role: "assistant",
      text: "原生回复",
      createdAt: new Date().toISOString(),
      state: "done",
    };
  });
  const overview: BotOverview = {
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "cli",
  };
  const client = createClient({
    getBotOverview: async () => overview,
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "原生 agent" }));
  await user.type(screen.getByPlaceholderText("输入消息"), "你好");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ executionMode: "native_agent" });
});

test("sends native agent message to selected child agent", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias: string,
    _text: string,
    onChunk: (chunk: string) => void,
  ): Promise<ChatMessage> => {
    onChunk("审查回复");
    return {
      id: "assistant-native-child",
      role: "assistant",
      text: "审查回复",
      createdAt: new Date().toISOString(),
      state: "done",
    };
  });
  const client = createClient({
    getBotOverview: async (_alias, options) => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      executionMode: "native_agent",
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "gpt-low", medium: "gpt-mid", high: "gpt-high" },
        reasoningEfforts: { low: "", medium: "", high: "" },
      },
      activeAgentId: options?.agentId || "main",
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "reviewer", name: "审查专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    listAgents: async () => ({
      items: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "reviewer", name: "审查专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.selectOptions(await screen.findByRole("combobox", { name: "当前 agent" }), "reviewer");
  await user.type(await screen.findByPlaceholderText("发给 审查专家..."), "帮我审查");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][5]).toMatchObject({
    executionMode: "native_agent",
    agentId: "reviewer",
  });
  expect(sendMessage.mock.calls[0][5]).not.toMatchObject({ cluster: true });
});

test("native agent plan mode keeps cluster options", async () => {
  const user = userEvent.setup();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias: string,
    _text: string,
    onChunk: (chunk: string) => void,
  ): Promise<ChatMessage> => {
    onChunk("原生计划回复");
    return {
      id: "assistant-native-plan-cluster",
      role: "assistant",
      text: "原生计划回复",
      createdAt: new Date().toISOString(),
      state: "done",
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
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "gpt-low", medium: "gpt-mid", high: "gpt-high" },
        reasoningEfforts: { low: "", medium: "", high: "" },
      },
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "tester", name: "测试专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "计划模式" }));
  await user.type(screen.getByPlaceholderText("@ 可指定智能体集群"), "@tester 先出方案");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  expect(sendMessage.mock.calls[0][5]).toMatchObject({
    taskMode: "plan",
    executionMode: "native_agent",
    cluster: true,
    mentions: [{ agentId: "tester", label: "测试专家", start: 0, end: 7 }],
  });
});

test("execute plan in native cluster keeps cluster options for create and auto-send", async () => {
  const user = userEvent.setup();
  const planMarkdown = "# 方案\n\n- 执行测试";
  const executePlan = vi.fn<WebBotClient["executePlan"]>(async () => ({
    planPath: "docs/plan/native.md",
    conversation: {
      id: "conv-native-cluster-plan",
      title: "执行方案",
      lastMessagePreview: "",
      messageCount: 0,
      pinned: false,
      active: true,
      status: "active",
      botAlias: "main",
      cliType: "codex",
      workingDir: "C:\\workspace",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
    messages: [],
    executionMessage: "请按方案执行。方案文件：docs/plan/native.md",
  }));
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async (
    _botAlias: string,
    _text: string,
    onChunk: (chunk: string) => void,
  ): Promise<ChatMessage> => {
    onChunk("已执行");
    return {
      id: "assistant-native-cluster-done",
      role: "assistant",
      text: "已执行",
      createdAt: new Date().toISOString(),
      state: "done",
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
      cluster: {
        enabled: true,
        writePolicy: "selected_agents",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 2,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "gpt-low", medium: "gpt-mid", high: "gpt-high" },
        reasoningEfforts: { low: "", medium: "", high: "" },
      },
      agents: [
        { id: "main", name: "主 agent", systemPrompt: "", enabled: true, isMain: true },
        { id: "tester", name: "测试专家", systemPrompt: "", enabled: true, isMain: false },
      ],
    }),
    listMessages: async (): Promise<ChatMessage[]> => [{
      id: "assistant-plan-draft",
      role: "assistant",
      text: `<PLAN_DRAFT>${planMarkdown}</PLAN_DRAFT>`,
      createdAt: new Date().toISOString(),
      state: "done",
    }],
    executePlan,
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "执行方案" }));

  await waitFor(() => {
    expect(executePlan).toHaveBeenCalledWith("main", expect.objectContaining({
      content: planMarkdown,
      executionMode: "native_agent",
      cluster: true,
      mentions: [],
    }));
  });
  await waitFor(() => {
    expect(sendMessage).toHaveBeenCalledWith(
      "main",
      expect.stringContaining("请按方案执行"),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({
        taskMode: "standard",
        executionMode: "native_agent",
        cluster: true,
        mentions: [],
      }),
      expect.any(Function),
    );
  });
});

test("native agent model select is enabled and saves bot model", async () => {
  const user = userEvent.setup();
  const updateNativeAgentModel = vi.fn<WebBotClient["updateNativeAgentModel"]>(async () => ({
    items: [
      {
        id: "jojocode_max/gpt-5.4",
        provider: "jojocode_max",
        model: "gpt-5.4",
        name: "gpt-5.4",
        label: "jojocode_max / gpt-5.4",
        contextWindow: 1000000,
        outputLimit: 128000,
        reasoningEfforts: ["low", "medium", "high"],
        defaultReasoningEffort: "medium",
      },
      {
        id: "jojocode_max/gpt-5.5",
        provider: "jojocode_max",
        model: "gpt-5.5",
        name: "gpt-5.5",
        label: "jojocode_max / gpt-5.5",
        contextWindow: 1000000,
        outputLimit: 128000,
        reasoningEfforts: ["low", "medium", "high"],
        defaultReasoningEffort: "medium",
      },
    ],
    selectedModel: "jojocode_max/gpt-5.5",
    selectedReasoningEffort: "medium",
  }));
  const updateCliParam = vi.fn<WebBotClient["updateCliParam"]>(async () => modelCliParams("gpt-5.4"));
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: { provider: "", model: "jojocode_max/gpt-5.4", piAgent: "" },
    }),
    getNativeAgentModels: async () => ({
      items: [
        {
          id: "jojocode_max/gpt-5.4",
          provider: "jojocode_max",
          model: "gpt-5.4",
          name: "gpt-5.4",
          label: "jojocode_max / gpt-5.4",
          contextWindow: 1000000,
          outputLimit: 128000,
          reasoningEfforts: ["low", "medium", "high"],
          defaultReasoningEffort: "medium",
        },
        {
          id: "jojocode_max/gpt-5.5",
          provider: "jojocode_max",
          model: "gpt-5.5",
          name: "gpt-5.5",
          label: "jojocode_max / gpt-5.5",
          contextWindow: 1000000,
          outputLimit: 128000,
          reasoningEfforts: ["low", "medium", "high"],
          defaultReasoningEffort: "medium",
        },
      ],
      selectedModel: "jojocode_max/gpt-5.4",
      selectedReasoningEffort: "medium",
    }),
    updateNativeAgentModel,
    updateCliParam,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const modelSelect = await screen.findByLabelText("模型");
  expect(modelSelect).toBeEnabled();
  await waitFor(() => {
    expect(within(modelSelect).getByRole("option", { name: "jojocode_max / gpt-5.4" })).toBeInTheDocument();
  });
  const reasoningSelect = screen.getByLabelText("推理强度");
  expect(reasoningSelect).toBeEnabled();

  await user.selectOptions(modelSelect, "jojocode_max/gpt-5.5");

  await waitFor(() => expect(updateNativeAgentModel).toHaveBeenCalledWith("main", "jojocode_max/gpt-5.5", { reasoningEffort: "medium" }));
  await user.selectOptions(reasoningSelect, "high");
  await waitFor(() => expect(updateNativeAgentModel).toHaveBeenCalledWith("main", "jojocode_max/gpt-5.5", { reasoningEffort: "high" }));
  expect(updateCliParam).not.toHaveBeenCalled();
});

test("shows CLI context usage as text badge without ring", async () => {
  const now = new Date().toISOString();
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-cli-context",
        role: "assistant",
        text: "完成",
        createdAt: now,
        state: "done",
        meta: {
          contextUsage: {
            provider: "codex",
            source: "codex_session_token_count",
            contextUsed: 36565,
            contextWindow: 1000000,
            contextLeftPercent: 74,
            usedDisplay: "36.6K",
            windowDisplay: "1M",
            statusText: "74% context left · 36.6K / 1M",
            compactionCount: 1,
          },
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("完成")).toBeInTheDocument();
  const textBadge = await screen.findByTestId("chat-message-context-usage-text");
  expect(textBadge).toHaveTextContent("74% left · 36.6K / 1M (compacted once)");
  expect(textBadge).toHaveAttribute("title", expect.stringContaining("context left: 74%"));
  expect(textBadge).toHaveAttribute("title", expect.stringContaining("context used: 36,565"));
  const bottomBadge = await screen.findByTestId("chat-message-context-usage-bottom");
  const contextCopyButton = await screen.findByRole("button", { name: "复制上下文详情" });
  const fullCopyButton = await screen.findByRole("button", { name: "复制完整回答" });
  const copyButton = await screen.findByRole("button", { name: "复制最终回答" });
  expect(bottomBadge).toHaveTextContent("ctx 74%");
  expect(contextCopyButton.compareDocumentPosition(fullCopyButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(fullCopyButton.compareDocumentPosition(copyButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(bottomBadge.compareDocumentPosition(copyButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByTestId("chat-message-context-usage")).not.toBeInTheDocument();
});

test("shows context usage ring with native token details", async () => {
  const now = new Date().toISOString();
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-context",
        role: "assistant",
        text: "完成",
        createdAt: now,
        state: "done",
        meta: {
          tracePresentation: "native_agent_flat",
          contextUsage: {
            provider: "原生 agent",
            contextUsed: 36565,
            contextWindow: 1000000,
            contextUsedPercent: 4,
            inputTokens: 1237,
            cacheReadTokens: 35328,
            cacheWriteTokens: 0,
            outputTokens: 512,
            reasoningTokens: 128,
            model: "jojocode_max/gpt-5.4",
          },
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const ring = await screen.findByTestId("chat-message-context-usage");
  expect(ring).toHaveAttribute("aria-label", "context 已用 4%");
  expect(ring).toHaveAttribute("title", expect.stringContaining("context window: 1,000,000"));
  expect(ring).toHaveAttribute("title", expect.stringContaining("cache read: 35,328"));
  const bottomBadge = await screen.findByTestId("chat-message-context-usage-bottom");
  const copyButton = await screen.findByRole("button", { name: "复制最终回答" });
  expect(bottomBadge).toHaveTextContent("ctx 96%");
  expect(bottomBadge.compareDocumentPosition(copyButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("copies context usage details from final answer actions", async () => {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  Object.defineProperty(globalThis.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-copy-context",
        role: "assistant",
        text: "完成",
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          contextUsage: {
            provider: "codex",
            contextUsed: 36565,
            contextWindow: 1000000,
            contextLeftPercent: 74,
            usedDisplay: "36.6K",
            windowDisplay: "1M",
          },
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  await userEvent.click(await screen.findByRole("button", { name: "复制上下文详情" }));

  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("context left: 74%"));
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("context used: 36,565"));
  expect(await screen.findByRole("button", { name: "已复制上下文详情" })).toBeInTheDocument();
});

test("full answer copy skips process text duplicated by final answer", async () => {
  const user = userEvent.setup();
  const writeText = mockClipboardWrite();
  const answer = "不太必要。\n\n建议：\n- 复制\n- 导出";
  const client = createClient({
    listMessages: async (): Promise<ChatMessage[]> => [
      {
        id: "assistant-duplicate-process",
        role: "assistant",
        text: answer,
        createdAt: new Date().toISOString(),
        state: "done",
        meta: {
          tracePresentation: "native_agent_flat",
          trace: [
            { kind: "commentary", summary: answer, source: "native_agent" },
          ],
          traceCount: 1,
          processCount: 1,
        },
      },
    ],
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const transcript = await screen.findByTestId("native-agent-transcript");
  expect(within(transcript).queryByText("过程")).not.toBeInTheDocument();
  const finalResult = within(transcript).getByTestId("native-agent-final-result");
  expect(finalResult).toHaveTextContent("不太必要。");
  expect(finalResult).toHaveTextContent("建议：");
  expect(finalResult).toHaveTextContent("复制");
  expect(finalResult).toHaveTextContent("导出");

  await user.click(await screen.findByRole("button", { name: "复制完整回答" }));

  const lastCopyCall = writeText.mock.calls.at(-1) as unknown[] | undefined;
  const copiedText = String(lastCopyCall?.[0] ?? "");
  expect(copiedText).toBe(`[最终回答]\n${answer}`);
  expect(copiedText).not.toContain("[过程]");
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
  const listMessages = vi.fn<WebBotClient["listMessages"]>(async (_botAlias, options) => options?.executionMode === "native_agent"
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
    }]);
  const client = createClient({
    getBotOverview,
    listMessages,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("CLI 历史")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "原生 agent" }));
  expect(await screen.findByText("原生历史")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "CLI" }));
  expect(await screen.findByText("CLI 历史")).toBeInTheDocument();
  expect(listMessages.mock.calls.some(([, options]) => options?.executionMode === "native_agent")).toBe(true);
  expect(listMessages.mock.calls.some(([, options]) => !options?.executionMode)).toBe(true);
});

test("uses overview default execution mode when storage is empty", async () => {
  const getBotOverview = vi.fn<WebBotClient["getBotOverview"]>(async (_botAlias, options) => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    supportedExecutionModes: ["cli", "native_agent"],
    defaultExecutionMode: "native_agent",
    executionMode: options?.executionMode === "native_agent" ? "native_agent" : "cli",
  }));
  const listMessages = vi.fn<WebBotClient["listMessages"]>(async (_botAlias, options) => options?.executionMode === "native_agent"
    ? [{
      id: "assistant-native",
      role: "assistant",
      text: "原生默认历史",
      createdAt: new Date().toISOString(),
      state: "done",
    }]
    : [{
      id: "assistant-cli",
      role: "assistant",
      text: "CLI 默认历史",
      createdAt: new Date().toISOString(),
      state: "done",
    }]);
  const client = createClient({
    getBotOverview,
    listMessages,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("原生默认历史")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "原生 agent" })).toHaveAttribute("aria-pressed", "true");
  expect(window.localStorage.getItem("tcb.executionMode.main")).toBeNull();
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
    meta: {
      workspaceHistoryHead: "head-1",
      linearIndex: 1,
      rollbackSupported: true,
    },
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
    meta: {
      workspaceHistoryHead: "head-2",
      linearIndex: 2,
      rollbackSupported: true,
    },
  };
  const listMessages = vi.fn<WebBotClient["listMessages"]>(async () => (
    rolledBack ? [user1, assistant1] : [user1, assistant1, user2, assistant2]
  ));
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
  expect(screen.getAllByRole("button", { name: "撤回到此消息前" })).toHaveLength(1);

  await user.click(screen.getByRole("button", { name: "撤回到此消息前" }));
  const dialog = await screen.findByRole("dialog", { name: "确认撤回" });
  expect(dialog).toBeInTheDocument();
  expect(dialog.parentElement?.parentElement).toBe(document.body);
  expect(dialog.parentElement).toHaveClass("z-[1000]");
  expect(screen.getByText("会丢弃该点之后的会话和工作区改动，不可撤销")).toBeInTheDocument();
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








