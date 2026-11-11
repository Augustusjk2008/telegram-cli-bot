import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import * as mermaidRenderer from "../markdown/mermaidRenderer";
import { ChatStreamIncompleteError } from "../services/chatStreamError";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotOverview, ChatMessage, ConversationListResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { CONVERSATION_CREATED_EVENT } from "../utils/conversationEvents";

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

test("renders user Markdown, math and diagrams", async () => {
  vi.spyOn(mermaidRenderer, "renderMermaidSingleFlight").mockResolvedValue({
    svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>Start to End</text></svg>',
    error: "",
  });
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "user-markdown",
      role: "user",
      author: { username: "Alice", isCurrentUser: true },
      text: [
        "## Formatted question",
        "",
        "**Bold** and \\(x^2\\) with `inline code`.",
        "",
        "| Input | Output |",
        "| --- | --- |",
        "| A | B |",
        "",
        "```mermaid",
        "graph LR; A-->B",
        "```",
      ].join("\n"),
      createdAt: "2026-09-17T00:00:00Z",
      state: "done",
    }] }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  const message = await screen.findByTestId("user-markdown-message");
  expect(within(message).getByRole("heading", { level: 2 })).toHaveTextContent("Formatted question");
  expect(message.querySelector("strong")).toHaveTextContent("Bold");
  expect(message.querySelector(".katex annotation")).toHaveTextContent("x^2");
  expect(within(message).getByRole("table")).toHaveTextContent("Input");
  expect(await within(message).findByLabelText("Mermaid 图表")).toContainHTML("<text>Start to End</text>");
});

test("keeps endless mode running and shows the retry countdown without the failed result", async () => {
  const secondAttempt = deferred<ChatMessage>();
  const continueCallbacks: Array<(attempt: number) => void> = [];
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>()
    .mockImplementationOnce(async (...args) => {
      const onEndlessError = args[6];
      const onEndlessContinue = args[7];
      onEndlessError?.({
        id: "assistant-endless-error",
        role: "assistant",
        text: "temporary failure",
        createdAt: "2026-10-23T00:00:01Z",
        state: "error",
      }, 1, 2000);
      if (onEndlessContinue) {
        continueCallbacks.push(onEndlessContinue);
      }
      return secondAttempt.promise;
    });
  const client = createClient({
    listMessages: async () => ({ items: [
      {
        id: "user-existing",
        role: "user",
        text: "原始问题",
        createdAt: "2026-10-22T00:00:00Z",
        state: "done",
      },
      {
        id: "assistant-existing",
        role: "assistant",
        text: "上一轮回答",
        createdAt: "2026-10-22T00:00:01Z",
        state: "error",
      },
    ] }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "无尽模式" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "无尽模式" }));
  expect(await screen.findByRole("dialog", { name: "确认开启无尽模式" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认开启" }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(sendMessage.mock.calls[0][1]).toBe("Continue");
  expect(sendMessage.mock.calls[0][5]?.endlessMode).toBe(true);
  expect(await screen.findByLabelText("ENDLESS...")).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
  expect(screen.getAllByTestId("chat-message-row")[0]).toHaveTextContent("原始问题");
  expect(screen.queryByText("temporary failure")).not.toBeInTheDocument();
  expect(await screen.findByText("（2秒后重试）")).toBeInTheDocument();

  act(() => continueCallbacks[0]?.(1));
  expect(screen.queryByText("（2秒后重试）")).not.toBeInTheDocument();

  await act(async () => {
    secondAttempt.resolve({
      id: "assistant-endless-done",
      role: "assistant",
      text: "完成",
      createdAt: "2026-10-23T00:00:04Z",
      state: "done",
    });
    await Promise.resolve();
  });
  expect(await screen.findByText("完成")).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
});

test("does not show endless mode after a normal answer", async () => {
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "assistant-normal",
      role: "assistant",
      text: "正常完成的回答",
      createdAt: "2026-10-22T00:00:00Z",
      state: "done",
    }] }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByText("正常完成的回答")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "无尽模式" })).not.toBeInTheDocument();
});

test("sends Continue from the Continue button without input translation", async () => {
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "assistant-continued",
    role: "assistant",
    text: "继续后的回答",
    createdAt: "2026-11-10T00:00:01Z",
    state: "done",
  }));
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "assistant-normal",
      role: "assistant",
      text: "正常完成的回答",
      createdAt: "2026-11-10T00:00:00Z",
      state: "done",
    }] }),
    sendMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  fireEvent.click(await screen.findByRole("button", { name: "继续" }));

  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  expect(sendMessage.mock.calls[0][1]).toBe("Continue");
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ skipInputTranslation: true });
});

test("restores backend endless mode after the chat screen is rebuilt", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: true,
      endlessMode: true,
      endlessAttempt: 3,
    }),
    listMessages: async () => ({ items: [{
      id: "assistant-endless-recovered",
      role: "assistant",
      text: "上一轮失败",
      createdAt: "2026-10-22T00:00:00Z",
      state: "error",
    }] }),
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect((await screen.findAllByRole("button", { name: "View context details: Continue ×3" })).length).toBeGreaterThan(0);
});

test("stopping endless mode terminates the active continuation", async () => {
  const activeAttempt = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => activeAttempt.promise);
  const killTask = vi.fn<WebBotClient["killTask"]>(async () => "已发送终止任务请求");
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "assistant-endless-active",
      role: "assistant",
      text: "上一轮回答",
      createdAt: "2026-10-22T00:00:00Z",
      state: "error",
    }] }),
    sendMessage,
    killTask,
  });

  render(<ChatScreen botAlias="main" client={client} />);

  expect(await screen.findByRole("button", { name: "无尽模式" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "无尽模式" }));
  expect(await screen.findByRole("dialog", { name: "确认开启无尽模式" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认开启" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

  fireEvent.click(screen.getByRole("button", { name: "终止任务" }));
  fireEvent.click(within(await screen.findByRole("dialog", { name: "确认终止任务" })).getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("dialog", { name: "确认终止任务" })).not.toBeInTheDocument();
  expect(killTask).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "终止任务" }));
  fireEvent.click(within(await screen.findByRole("dialog", { name: "确认终止任务" })).getByRole("button", { name: "确认终止" }));
  await waitFor(() => expect(killTask).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("dialog", { name: "确认终止任务" })).not.toBeInTheDocument();

  activeAttempt.resolve({
    id: "assistant-endless-stopped",
    role: "assistant",
    text: "已停止",
    createdAt: "2026-10-23T00:00:02Z",
    state: "done",
  });
});

test.each(["posix", "windows"] as const)("remote %s chat uploads, sends, previews and deletes local attachments", async (platform) => {
  const user = userEvent.setup();
  const attachmentRoot = "C:\\control\\remote\\attachments\\tester";
  const savedPath = `${attachmentRoot}\\report.html`;
  const previewPath = savedPath.replace(/\\/g, "/");
  const upload = vi.fn<WebBotClient["uploadChatAttachment"]>(async (_alias, file) => ({
    filename: file.name, savedPath: `${attachmentRoot}\\${file.name}`, size: file.size,
  }));
  const remove = vi.fn<WebBotClient["deleteChatAttachment"]>(async (_alias, path) => ({
    filename: path.split("\\").pop()!, savedPath: path, existed: true, deleted: true,
  }));
  const send = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "attachment-reply", role: "assistant", text: `[查看附件](<${previewPath}>)`,
    createdAt: "2026-10-17T00:00:00Z", state: "done",
  }));
  const read = vi.fn<WebBotClient["readFile"]>(async () => ({ content: "<html>", mode: "head", isFullContent: false }));
  const full = vi.fn<WebBotClient["readFileFull"]>(async () => ({ content: "<html>Local attachment</html>", mode: "cat", isFullContent: true }));
  const download = vi.fn<WebBotClient["downloadFile"]>(async () => undefined);
  const desktopPreview = vi.fn();
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main", cliType: "codex", status: "running", workingDir: "C:\\control\\remote", isProcessing: false,
      executionMode: "cli",
      remoteWorkspace: { connectionId: "ssh-1", host: "remote.test", port: 22, username: "dev", root: platform === "windows" ? "/C:/project" : "/srv/project", hostKeyFingerprint: "SHA256:test", platform },
    }),
    uploadChatAttachment: upload, deleteChatAttachment: remove, sendMessage: send,
    readFile: read, readFileFull: full, downloadFile: download,
  });
  const htmlSession = vi.spyOn(client, "createHtmlPreview");
  render(<ChatScreen botAlias="main" client={client} embedded={platform === "windows"} onRequestDesktopPreview={desktopPreview} />);
  await screen.findByText("暂无消息，开始聊天吧");
  const input = screen.getByLabelText("上传附件");
  expect(input).toBeEnabled();
  const draft = new File(["draft"], "draft.txt", { type: "text/plain" });
  await user.upload(input, draft);
  expect(upload).toHaveBeenCalledWith("main", draft, expect.any(Function), expect.any(AbortSignal));
  await user.click(await screen.findByRole("button", { name: "移除附件 draft.txt" }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith("main", `${attachmentRoot}\\draft.txt`));
  expect(screen.queryByText("draft.txt")).not.toBeInTheDocument();

  const file = new File(["<html>Local attachment</html>"], "report.html", { type: "text/html" });
  await user.upload(input, file);
  expect(upload).toHaveBeenLastCalledWith("main", file, expect.any(Function), expect.any(AbortSignal));
  await screen.findByRole("button", { name: "移除附件 report.html" });
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "检查附件" } });
  await user.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(send).toHaveBeenCalledOnce());
  expect(send.mock.calls[0][1]).toBe(`检查附件\n\nAttachment path: ${savedPath}`);
  expect(screen.queryByRole("button", { name: "移除附件 report.html" })).not.toBeInTheDocument();

  await user.click(await screen.findByRole("link", { name: "查看附件" }));
  const dialog = await screen.findByRole("dialog", { name: previewPath });
  await waitFor(() => expect(full).toHaveBeenCalledWith("main", previewPath));
  expect(read).toHaveBeenCalledWith("main", previewPath);
  expect(htmlSession).not.toHaveBeenCalled();
  expect(desktopPreview).not.toHaveBeenCalled();
  await user.click(within(dialog).getByRole("button", { name: "下载" }));
  await waitFor(() => expect(download).toHaveBeenCalledWith("main", previewPath, expect.any(Function), expect.any(AbortSignal)));
  await user.click(within(dialog).getByRole("button", { name: "关闭" }));
  await user.click(screen.getByRole("button", { name: "删除附件文件 report.html" }));
  await waitFor(() => expect(remove).toHaveBeenLastCalledWith("main", savedPath));
  expect(await screen.findByText("已删除")).toBeInTheDocument();
});

test.each([true, false])("executes the edited plan and leaves plan mode (structured title: %s)", async (hasTitle) => {
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
        text: `${hasTitle ? "<PLAN_TITLE>\n修复计划文件命名\n</PLAN_TITLE>\n" : ""}<PLAN_DRAFT>\n# 执行这个方案\n\n完成目标改动。\n</PLAN_DRAFT>`,
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
  await user.click(await screen.findByRole("button", { name: "修改方案" }));
  const planEditor = screen.getByRole("textbox", { name: "方案内容" });
  expect(planEditor).toHaveValue("# 执行这个方案\n\n完成目标改动。");
  fireEvent.change(planEditor, { target: { value: "# 更新后的方案\n\n完成改动并验证。" } });
  await user.click(await screen.findByRole("button", { name: "执行方案" }));
  await waitFor(() => expect(executePlan).toHaveBeenCalledTimes(1));
  expect(executePlan).toHaveBeenCalledWith("main", expect.objectContaining({
    title: hasTitle ? "修复计划文件命名" : "",
    content: "# 更新后的方案\n\n完成改动并验证。",
  }));

  expect(planModeButton).toHaveAttribute("aria-pressed", "false");
  expect(window.localStorage.getItem("tcb.planMode.main")).toBeNull();

  await act(async () => executionGate.resolve());
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "计划模式" })).toHaveAttribute("aria-pressed", "false");
});

test.each(["Please execute the plan. Plan file: ", "请按方案执行。方案文件："])("sends pasted plan execution in standard mode (%s)", async (prefix) => {
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(async () => ({
    id: "assistant-executed", role: "assistant", text: "完成", createdAt: "2026-09-17T01:00:00Z", state: "done",
  }));
  window.localStorage.setItem("tcb.planMode.main", "1");
  render(<ChatScreen botAlias="main" client={createClient({ sendMessage })} />);
  await screen.findByText("暂无消息，开始聊天吧");
  const text = `${prefix}docs/plan/example.md`;
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  expect(sendMessage.mock.calls[0][1]).toBe(text);
  expect(sendMessage.mock.calls[0][5]).toMatchObject({ taskMode: "standard" });
  expect(screen.getByRole("button", { name: "计划模式" })).toHaveAttribute("aria-pressed", "false");
});

test("shows the Codex cost difference in message details while retaining raw history amounts", async () => {
  const items: ChatMessage[] = [10, 15].map((total, index) => ({
    id: `cost-${index}`, turnId: `turn-${index}`, conversationId: "cost-conversation",
    role: "assistant", text: `Cost reply ${index}`, createdAt: "2026-09-17T00:00:00Z", state: "done",
    meta: { contextUsage: {
      provider: "codex", contextLeftPercent: 72,
      estimatedCost: { model: "test-model", currency: "USD", scope: "turn", total,
        input: total, cacheRead: 0, cacheWrite: 0, output: 0 },
    } },
  }));
  render(<ChatScreen botAlias="main" client={createClient({ listMessages: async () => ({ items }) })} />);
  const rows = await screen.findAllByTestId("chat-message-row");
  fireEvent.click(within(rows[1]).getByTestId("chat-message-context-usage-bottom"));
  expect(screen.getByRole("tooltip")).toHaveTextContent("cost: USD 5");
  expect(items[1].meta?.contextUsage?.estimatedCost?.total).toBe(15);
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

test("steers an active codex server turn without queuing or duplicating the assistant", async () => {
  const user = userEvent.setup();
  const final = deferred<ChatMessage>();
  let activeSignal: AbortSignal | undefined;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((
    _botAlias,
    _text,
    _onChunk,
    onStatus,
    _onTrace,
    options,
  ) => {
    activeSignal = options?.signal;
    onStatus?.({ turnId: "turn-codex-server", assistantMessageId: "assistant-codex-server" });
    return final.promise;
  });
  const steerMessage = vi.fn<WebBotClient["steerMessage"]>(async (_botAlias, text, turnId) => ({
    id: "user-steer-1",
    turnId,
    role: "user",
    text,
    createdAt: "2026-09-30T06:00:01Z",
    state: "done",
  }));
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex_server",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }),
    sendMessage,
    steerMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "原始任务");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

  await user.type(screen.getByPlaceholderText("输入消息"), "追加要求");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(steerMessage).toHaveBeenCalledWith(
    "main",
    "追加要求",
    "turn-codex-server",
    undefined,
  ));
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(activeSignal?.aborted).toBe(false);
  expect(screen.queryByText(/排队中/)).not.toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(3);
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("");

  await act(async () => {
    final.resolve({
      id: "assistant-codex-server",
      turnId: "turn-codex-server",
      role: "assistant",
      text: "完成",
      createdAt: "2026-09-30T06:00:02Z",
      state: "done",
    });
  });
  expect(await screen.findByText("完成")).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(3);
});

test("retains steering input when the Codex server rejects it", async () => {
  const user = userEvent.setup();
  const final = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((_botAlias, _text, _onChunk, onStatus) => {
    onStatus?.({ turnId: "turn-codex-server-error", assistantMessageId: "assistant-codex-server-error" });
    return final.promise;
  });
  const steerMessage = vi.fn<WebBotClient["steerMessage"]>(async () => {
    throw new Error("steering failed");
  });
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex_server",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: false,
    }),
    sendMessage,
    steerMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "原始任务");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

  const input = screen.getByPlaceholderText("输入消息");
  await user.type(input, "保留这条输入");
  await user.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(steerMessage).toHaveBeenCalledTimes(1));
  expect(input).toHaveValue("保留这条输入");
  expect(await screen.findByText("steering failed")).toBeInTheDocument();
  expect(screen.queryByText(/排队中/)).not.toBeInTheDocument();

  await act(async () => {
    final.resolve({
      id: "assistant-codex-server-error",
      turnId: "turn-codex-server-error",
      role: "assistant",
      text: "完成",
      createdAt: "2026-09-30T06:02:02Z",
      state: "done",
    });
  });
});

test("keeps text input locked while an active persisted voice task is foreground", async () => {
  const user = userEvent.setup();
  const steerMessage = vi.fn<WebBotClient["steerMessage"]>(async (_botAlias, text, turnId) => ({
    id: "user-voice-steer",
    turnId,
    role: "user",
    text,
    createdAt: "2026-10-04T06:00:01Z",
    state: "done",
  }));
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "assistant-voice",
      turnId: "tcb-turn-voice",
      conversationId: "conversation-voice",
      role: "assistant",
      text: "语音处理中",
      createdAt: "2026-10-04T06:00:00Z",
      state: "streaming",
      meta: {
        voice: {
          tcbTurnId: "tcb-turn-voice",
          assistantMessageId: "assistant-voice",
          codexTurnId: "codex-turn-voice",
          conversationId: "conversation-voice",
          state: "active",
          transcriptState: "syncing",
          sessionEpoch: 8,
        },
      },
    }] }),
    getBotOverview: async () => ({
      alias: "main",
      cliType: "codex_server",
      status: "running",
      workingDir: "C:\\workspace",
      isProcessing: true,
      activeConversationId: "conversation-voice",
      sessionEpoch: 8,
      effectiveCapabilities: ["chat_send"],
      voice: { enabled: true, reason: "available" },
    }),
    steerMessage,
  });

  render(<ChatScreen botAlias="main" client={client} />);
  const voiceBar = await screen.findByTestId("codex-voice-bar");
  await waitFor(() => expect(voiceBar).toHaveTextContent("运行中"));
  expect(screen.getByPlaceholderText("请先结束语音再发送文字，混合输入将在 M2 支持")).toBeDisabled();
  expect(steerMessage).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "查看会话历史" }));
  expect((await screen.findAllByRole("button", { name: "关闭历史会话" })).length).toBeGreaterThan(0);
});

test("keeps regular codex messages in the existing queue while streaming", async () => {
  const user = userEvent.setup();
  const final = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((_botAlias, _text, _onChunk, onStatus) => {
    onStatus?.({ turnId: "turn-codex", assistantMessageId: "assistant-codex" });
    return final.promise;
  });
  const steerMessage = vi.fn<WebBotClient["steerMessage"]>();
  const client = createClient({ sendMessage, steerMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  await user.type(await screen.findByPlaceholderText("输入消息"), "原始任务");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

  await user.type(screen.getByPlaceholderText("输入消息"), "排队要求");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(steerMessage).not.toHaveBeenCalled();
  expect(await screen.findByText("排队中")).toBeInTheDocument();
  expect(screen.getByText("排队要求")).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);

  await act(async () => {
    final.resolve({
      id: "assistant-codex",
      turnId: "turn-codex",
      role: "assistant",
      text: "完成",
      createdAt: "2026-09-30T06:01:02Z",
      state: "done",
    });
  });
});

test("cancelling a queued message returns it to the composer and confirms before overwriting a draft", async () => {
  const user = userEvent.setup();
  const final = deferred<ChatMessage>();
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>(() => final.promise);
  const client = createClient({ sendMessage });

  render(<ChatScreen botAlias="main" client={client} />);
  const queue = async () => {
    await user.type(screen.getByPlaceholderText("输入消息"), "排队要求");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("排队中")).toBeInTheDocument();
  };
  await user.type(await screen.findByPlaceholderText("输入消息"), "原始任务");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

  await queue();
  await user.click(screen.getByRole("button", { name: "取消排队消息" }));
  expect(screen.queryByText("排队中")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("排队要求");

  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("排队中")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("输入消息"), "新草稿");
  await user.click(screen.getByRole("button", { name: "取消排队消息" }));
  await user.click(within(await screen.findByRole("dialog", { name: "确认覆盖输入框内容" })).getByRole("button", { name: "保留排队" }));
  expect(screen.getByText("排队中")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("新草稿");

  await user.click(screen.getByRole("button", { name: "取消排队消息" }));
  await user.click(within(await screen.findByRole("dialog", { name: "确认覆盖输入框内容" })).getByRole("button", { name: "覆盖并取消排队" }));
  expect(screen.queryByText("排队中")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("排队要求");
  expect(sendMessage).toHaveBeenCalledTimes(1);
});

test("starting a new session from an empty session does nothing", async () => {
  const user = userEvent.setup();
  const createConversation = vi.fn<WebBotClient["createConversation"]>(async () => ({
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
      createdAt: "2026-11-12T00:00:00Z",
      updatedAt: "2026-11-12T00:00:00Z",
    },
    messages: [],
  }));
  const history: ChatMessage[] = [];
  const client = createClient({ createConversation, listMessages: async () => ({ items: history }) });

  const view = render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByPlaceholderText("输入消息");
  await user.click(screen.getByRole("button", { name: "历史会话" }));
  await user.click(await screen.findByRole("button", { name: "新会话" }));
  expect(createConversation).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "新会话" })).toBeInTheDocument();
  view.unmount();

  history.push({ id: "user-old", role: "user", text: "旧问题", createdAt: "2026-11-12T00:00:00Z", state: "done" });
  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("旧问题")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "历史会话" }));
  await user.click(await screen.findByRole("button", { name: "新会话" }));
  await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(1));
});

test("cluster chat stays on the main Agent, preserves @ text, and sends no dispatch fields", async () => {
  const user = userEvent.setup();
  const cluster = {
    enabled: true,
    writePolicy: "main_only" as const,
    maxParallelAgents: 3,
    defaultTimeoutSeconds: 600,
    modelTiers: { low: "", medium: "", high: "", professional: "" },
    reasoningEfforts: { low: "", medium: "", high: "", professional: "" },
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
    maxParallelAgents: 2,
    defaultTimeoutSeconds: 900,
    modelTiers: { low: "fast-model", medium: "", high: "strong-model", professional: "" },
    reasoningEfforts: { low: "low", medium: "medium", high: "high", professional: "" },
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
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 600,
      modelTiers: { low: "", medium: "", high: "", professional: "" },
      reasoningEfforts: { low: "", medium: "", high: "", professional: "" },
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
  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTimeAsync(30_000));

  expect(activeSignal?.aborted).toBe(false);

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

test("renders CLI trace in the CLI transcript", async () => {
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
  const transcript = within(row).getByTestId("cli-transcript");
  expect(within(transcript).getByText("CLI 路由哨兵")).toBeInTheDocument();
  expect(within(transcript).getByTestId("cli-final-result")).toHaveTextContent("CLI 最终答复");
  expect(within(row).queryByTestId("chat-trace-panel-assistant-cli-trace")).not.toBeInTheDocument();
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
    maxParallelAgents: 3,
    defaultTimeoutSeconds: 600,
    modelTiers: { low: "gpt-5.6-mini", medium: "gpt-5.6-codex", high: "gpt-5.6-pro", professional: "" },
    reasoningEfforts: { low: "low", medium: "medium", high: "xhigh", professional: "" },
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

test("DeepSeek selects provider, model, and thinking atomically while retaining CLI boundaries", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main", cliType: "deepseek", status: "running", workingDir: "C:/workspace",
      voice: { enabled: true, reason: "enabled" },
    }),
  });
  await client.updateBotCli("main", "deepseek", "dsh");
  const updateSelection = vi.spyOn(client, "updateDeepSeekSelection");
  const upload = vi.spyOn(client, "uploadChatAttachment");
  render(<ChatScreen botAlias="main" client={client} />);
  const provider = await screen.findByRole("combobox", { name: "Provider" });
  const model = await screen.findByRole("combobox", { name: "模型" });
  const thinking = screen.getByRole("combobox", { name: "思考深度" });
  expect(model).toHaveValue("none");
  expect(thinking).toHaveValue("none");
  await userEvent.selectOptions(model, "deepseek-v4-pro");
  await waitFor(() => expect(model).toHaveValue("deepseek-v4-pro"));
  expect(updateSelection).toHaveBeenLastCalledWith("main", {
    provider: "deepseek",
    model: "deepseek-v4-pro",
    reasoningEffort: "none",
  });
  for (const effort of ["high", "off", "none"]) {
    await userEvent.selectOptions(thinking, effort);
    await waitFor(() => expect(thinking).toHaveValue(effort));
    expect(updateSelection).toHaveBeenLastCalledWith("main", {
      provider: "deepseek",
      model: "deepseek-v4-pro",
      reasoningEffort: effort,
    });
    expect((await client.getCliParams("main")).params.reasoning_effort).toBe(effort);
  }
  await userEvent.selectOptions(provider, "siliconflow");
  await waitFor(() => expect(provider).toHaveValue("siliconflow"));
  expect(updateSelection).toHaveBeenLastCalledWith("main", {
    provider: "siliconflow",
    model: "deepseek-v4-pro",
    reasoningEffort: "high",
  });
  expect(await screen.findByTestId("deepseek-selection-notice")).toHaveTextContent("下一轮将建立新会话");
  await userEvent.selectOptions(model, "none");
  await waitFor(() => expect(model).toHaveValue("none"));
  expect((await client.getCliParams("main")).params.model).toBeNull();
  expect(screen.queryByTestId("codex-voice-foreground")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "开启集群模式" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("上传附件"), { target: { files: [new File(["image"], "photo.png", { type: "image/png" })] } });
  expect(await screen.findByText("DeepSeek Harness 暂不支持图片或语音附件")).toBeInTheDocument();
  expect(upload).not.toHaveBeenCalled();
});

test("DeepSeek preserves a selected custom model in mobile chat options", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main", cliType: "deepseek", status: "running", workingDir: "C:/workspace",
    }),
  });
  await client.updateBotCli("main", "deepseek", "dsh");
  await client.updateCliParam("main", "model", "deepseek-custom", "deepseek");
  render(<ChatScreen botAlias="main" client={client} mobileLayout />);
  await screen.findByText("暂无消息，开始聊天吧");
  await userEvent.click(screen.getByRole("button", { name: "聊天选项" }));
  const model = await screen.findByRole("combobox", { name: "模型" });
  expect(model).toHaveValue("deepseek-custom");
  expect(within(model).getByRole("option", { name: "deepseek-custom" })).toBeInTheDocument();
  const thinking = screen.getByRole("combobox", { name: "思考深度" });
  await userEvent.selectOptions(thinking, "max");
  await waitFor(() => expect(thinking).toHaveValue("max"));
  expect((await client.getCliParams("main")).params).toMatchObject({ model: "deepseek-custom", reasoning_effort: "max" });
});

test("DeepSeek keeps an editable model input when the selected provider has no model catalog", async () => {
  const client = createClient({
    getBotOverview: async () => ({
      alias: "main", cliType: "deepseek", status: "running", workingDir: "C:/workspace",
    }),
  });
  await client.updateBotCli("main", "deepseek", "dsh");
  const base = await client.getCliParams("main");
  vi.spyOn(client, "getCliParams").mockResolvedValue({
    ...base,
    providerOptions: [base.providerOptions?.[0] || { id: "deepseek", label: "DeepSeek" }],
    modelOptionsByProvider: { deepseek: [] },
    selectedProvider: "deepseek",
    schema: { ...base.schema, model: { ...base.schema.model, enum: ["none"] } },
  });
  const updateSelection = vi.spyOn(client, "updateDeepSeekSelection");

  render(<ChatScreen botAlias="main" client={client} mobileLayout />);
  await userEvent.click(await screen.findByRole("button", { name: "聊天选项" }));
  const model = await screen.findByLabelText("模型");
  await userEvent.type(model, "deepseek-custom");
  await userEvent.tab();

  await waitFor(() => expect(updateSelection).toHaveBeenCalledWith("main", {
    provider: "deepseek",
    model: "deepseek-custom",
    reasoningEffort: "none",
  }));
});

test("chat attachment uploads show progress and cancelling keeps files that already finished", async () => {
  const user = userEvent.setup();
  let pendingSignal: AbortSignal | undefined;
  const upload = vi.fn<WebBotClient["uploadChatAttachment"]>(async (_alias, file, onProgress, signal) => {
    if (file.name === "notes.txt") {
      return { filename: file.name, savedPath: `C:\\attachments\\${file.name}`, size: file.size };
    }
    pendingSignal = signal;
    onProgress?.({ uploadedBytes: 512, totalBytes: 2048, percent: 25 });
    return new Promise<never>((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("上传已取消", "AbortError")), { once: true });
    });
  });
  const client = createClient({ uploadChatAttachment: upload });
  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
  const input = screen.getByLabelText("上传附件");
  expect(input).toBeEnabled();

  await user.upload(input, [new File(["notes"], "notes.txt"), new File(["video"], "clip.mp4")]);

  expect(await screen.findByRole("progressbar", { name: "clip.mp4 上传进度" })).toHaveAttribute("aria-valuenow", "25");
  expect(screen.getByRole("status", { name: "附件上传进度" })).toHaveTextContent("正在上传 clip.mp4 (2/2)");
  expect(screen.getByRole("button", { name: "移除附件 notes.txt" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "取消上传附件" }));
  await waitFor(() => expect(screen.queryByRole("status", { name: "附件上传进度" })).not.toBeInTheDocument());
  expect(pendingSignal?.aborted).toBe(true);
  expect(screen.getByRole("button", { name: "移除附件 notes.txt" })).toBeEnabled();
  expect(screen.queryByText("上传已取消")).not.toBeInTheDocument();
});

test("follows a conversation created by a saved CLI switch for the same bot", async () => {
  const client = createClient({
    listMessages: async () => ({ items: [{
      id: "old-cli-answer",
      role: "assistant",
      text: "旧 CLI 的回答",
      createdAt: "2026-11-11T00:00:00Z",
      state: "done",
    }] }),
  });
  render(<ChatScreen botAlias="main" client={client} />);
  expect(await screen.findByText("旧 CLI 的回答")).toBeInTheDocument();

  const announce = (botAlias: string) => act(() => {
    window.dispatchEvent(new CustomEvent(CONVERSATION_CREATED_EVENT, {
      detail: {
        botAlias,
        result: {
          conversation: {
            id: `conv-${botAlias}`,
            title: "新会话",
            lastMessagePreview: "",
            messageCount: 0,
            pinned: false,
            active: true,
            status: "active",
            botAlias,
            cliType: "claude",
            workingDir: "C:\\workspace",
          },
          messages: [],
        },
      },
    }));
  });

  announce("other");
  expect(screen.getByText("旧 CLI 的回答")).toBeInTheDocument();
  announce("main");
  await waitFor(() => expect(screen.queryByText("旧 CLI 的回答")).not.toBeInTheDocument());
});
