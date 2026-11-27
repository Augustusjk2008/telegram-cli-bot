import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import type { ChatMessage, ChatSessionSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { startConversationAfterCliSwitch } from "../utils/conversationEvents";

const main = { id: "main", title: "主会话" };
const research = { id: "ses_a", title: "调查" };
const review = { id: "ses_b", title: "复核" };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function message(text: string): ChatMessage {
  return { id: text, text, role: "assistant", state: "done", createdAt: "2026-11-20T00:00:00Z" };
}

function sessionClient(history: string) {
  const client = new MockWebBotClient();
  const overview = client.getBotOverview.bind(client);
  let busy = false;
  const turn = deferred<ChatMessage>();
  const send = vi.spyOn(client, "sendMessage").mockImplementation(async () => {
    busy = true;
    return turn.promise;
  });
  vi.spyOn(client, "getBotOverview").mockImplementation(async (alias) => ({
    ...await overview(alias), cliType: "codex", isProcessing: busy,
  }));
  const list = vi.spyOn(client, "listMessages").mockResolvedValue({ items: [message(history)] });
  vi.spyOn(client, "listConversations").mockResolvedValue({ activeConversationId: "", items: [] });
  const kill = vi.spyOn(client, "killTask").mockResolvedValue("已终止");
  return { client, send, list, kill, turn, finish: () => { busy = false; turn.resolve(message("过期的 SSE 回答")); } };
}

function chatDirectory() {
  const root = sessionClient("主会话历史");
  const a = sessionClient("调查历史");
  const b = sessionClient("复核历史");
  const items = [main, research, review];
  const list = vi.spyOn(root.client, "listChatSessions").mockImplementation(async () => ({ enabled: true, items }));
  const bind = vi.spyOn(root.client, "forChatSession").mockImplementation((_alias, id) => {
    if (id === research.id) return a.client;
    if (id === review.id) return b.client;
    throw Error("未知会话");
  });
  return { root, a, b, list, bind };
}

async function choose(item: ChatSessionSummary) {
  fireEvent.change(await screen.findByRole("combobox", { name: "当前聊天会话" }), { target: { value: item.id } });
}

function typeDraft(value: string) {
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value } });
}

async function send(text: string) {
  typeDraft(text);
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(screen.getByPlaceholderText("输入消息")).toHaveValue(""));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

async function openCreateDialog() {
  await screen.findByRole("option", { name: "新建聊天会话…" });
  // jsdom lacks the native modal methods. Keep the stub local to this dialog.
  const dialog = document.querySelector<HTMLDialogElement>('dialog[aria-label="新建聊天会话"]')!;
  dialog.showModal ??= () => { dialog.open = true; };
  dialog.close ??= () => { dialog.open = false; };
  fireEvent.change(screen.getByRole("combobox", { name: "当前聊天会话" }), { target: { value: "" } });
  return within(await screen.findByRole("dialog", { name: "新建聊天会话" }));
}

test("preselects the Bot default even when unavailable, retains a failed choice, and focuses the new session", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.updateBotCli("main", "codex_server", "codex");
  const catalog = await client.listChatSessions("main");
  vi.spyOn(client, "listChatSessions").mockResolvedValue({
    ...catalog, cliOptions: catalog.cliOptions.map((option) => ({ ...option, available: option.cliType !== "codex_server" })),
  });
  const create = vi.spyOn(client, "createChatSession").mockRejectedValueOnce(new Error("工具刚刚离线"));
  render(<ChatScreen botAlias="main" client={client} />);
  const dialog = await openCreateDialog();
  const title = dialog.getByRole("textbox", { name: "聊天会话名称" });
  expect(title).toHaveFocus();
  await user.type(title, "Review");
  await user.tab();
  const tool = dialog.getByRole("combobox", { name: "AI 工具" });
  expect(tool).toHaveFocus();
  expect(tool).toHaveValue("codex_server");
  expect(tool).toHaveAccessibleDescription(/不可用/);
  expect(within(tool).getAllByRole("option")).toHaveLength(5);
  expect(within(tool).getByRole("option", { name: /codex server.*不可用/ })).toBeDisabled();
  const submit = dialog.getByRole("button", { name: "创建" });
  expect(submit).toBeDisabled();
  await user.selectOptions(tool, "claude");
  await user.click(submit);
  expect(await dialog.findByRole("alert")).toHaveTextContent("工具刚刚离线");
  expect(title).toHaveValue("Review");
  expect(tool).toHaveValue("claude");
  expect(tool).toHaveFocus();
  expect(create).toHaveBeenCalledTimes(1);
  await user.click(submit);
  expect(create.mock.calls).toEqual([["main", "Review", "claude"], ["main", "Review", "claude"]]);
  const selector = await screen.findByRole("combobox", { name: "当前聊天会话" });
  await waitFor(() => {
    expect(selector).toHaveDisplayValue("Review · claude · 空闲");
    expect(selector).toHaveFocus();
  });
});

test("creates with only the title on a phase-one host and returns focus after cancel", async () => {
  const { root } = chatDirectory();
  const create = vi.spyOn(root.client, "createChatSession").mockResolvedValue(review);
  render(<ChatScreen botAlias="main" client={root.client} mobileLayout />);
  const first = await openCreateDialog();
  expect(first.queryByRole("combobox", { name: "AI 工具" })).not.toBeInTheDocument();
  fireEvent.click(first.getByRole("button", { name: "取消" }));
  expect(screen.getByRole("combobox", { name: "当前聊天会话" })).toHaveFocus();
  const dialog = await openCreateDialog();
  fireEvent.change(dialog.getByRole("textbox"), { target: { value: review.title } });
  fireEvent.click(dialog.getByRole("button", { name: "创建" }));
  await screen.findByText("复核历史");
  expect(create.mock.calls).toEqual([["main", review.title]]);
});

test("keeps a pinned chat's draft and DeepSeek controls when the Bot's default is changed", async () => {
  const client = new MockWebBotClient();
  const pinned = await client.createChatSession("main", "Pinned", "deepseek");
  const params = vi.spyOn(client, "getCliParams");
  const upload = vi.spyOn(client, "uploadChatAttachment");
  render(<ChatScreen botAlias="main" client={client} />);
  await choose(pinned);
  await waitFor(() => expect(params).toHaveBeenLastCalledWith("main", "deepseek"));
  typeDraft("keep this draft");
  await act(async () => {
    await client.updateBotCli("main", "antigravity", "agy");
    await startConversationAfterCliSwitch(client, "main", "antigravity");
  });
  const selector = screen.getByRole("combobox", { name: "当前聊天会话" });
  expect(selector).toHaveDisplayValue("Pinned · DeepSeek Harness · 空闲");
  expect(within(selector).getByRole("option", { name: /主会话.*Antigravity CLI.*Bot 默认/ })).toBeInTheDocument();
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("keep this draft");
  expect(params).toHaveBeenLastCalledWith("main", "deepseek");
  fireEvent.change(screen.getByTestId("chat-attachment-input"), { target: { files: [new File(["img"], "img.png")] } });
  await screen.findByText("DeepSeek Harness 暂不支持图片或语音附件");
  expect(upload).not.toHaveBeenCalled();
  expect((await openCreateDialog()).getByRole("combobox", { name: "AI 工具" })).toHaveValue("antigravity");
});

test("refreshes an inherited chat's controls from its own overview after a Bot settings switch", async () => {
  const client = new MockWebBotClient();
  const inherited = await client.createChatSession("main", "Legacy");
  const params = vi.spyOn(client, "getCliParams");
  render(<ChatScreen botAlias="main" client={client} />);
  await choose(inherited);
  await waitFor(() => expect(params).toHaveBeenLastCalledWith("main", inherited.effectiveCliType));
  typeDraft("inherited draft");
  await act(async () => {
    await client.updateBotCli("main", "deepseek", "dsh");
    await startConversationAfterCliSwitch(client, "main", "deepseek");
  });
  await waitFor(() => expect(params).toHaveBeenLastCalledWith("main", "deepseek"));
  expect(screen.getByRole("combobox", { name: "当前聊天会话" })).toHaveDisplayValue("Legacy · DeepSeek Harness（Bot 默认） · 空闲");
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("inherited draft");
});

test("switches between two running sessions, restores each draft and drains the queue only in its owning session", async () => {
  const { root, a, b } = chatDirectory();
  render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  await choose(research);
  await screen.findByText("调查历史");
  await send("开始调查");
  await send("继续调查");
  typeDraft("调查草稿");
  const signal = a.send.mock.calls[0][5]?.signal;

  await choose(review);
  await screen.findByText("复核历史");
  expect(signal?.aborted).toBe(true);
  expect(a.kill).not.toHaveBeenCalled();
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("");
  expect(screen.queryByText("继续调查")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /集群模式/ })).not.toBeInTheDocument();
  await send("开始复核");
  fireEvent.click(screen.getByRole("button", { name: "终止任务" }));
  fireEvent.click(within(screen.getByRole("dialog", { name: "确认终止任务" })).getByRole("button", { name: "确认终止" }));
  await waitFor(() => expect(b.kill).toHaveBeenCalledTimes(1));
  typeDraft("复核草稿");

  await choose(research);
  await screen.findByText("继续调查");
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("调查草稿");
  expect(a.send).toHaveBeenCalledTimes(1);
  await choose(review);
  await screen.findByText("复核历史");
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("复核草稿");
  await act(async () => { a.finish(); await a.turn.promise; });
  expect(screen.queryByText("过期的 SSE 回答")).not.toBeInTheDocument();
  await choose(research);
  await waitFor(() => expect(a.send.mock.calls.map((call) => call[1])).toEqual(["开始调查", "继续调查"]));
  expect(b.send.mock.calls.map((call) => call[1])).toEqual(["开始复核"]);
  expect(root.send).not.toHaveBeenCalled();
  expect(root.kill).not.toHaveBeenCalled();
  expect(a.kill).not.toHaveBeenCalled();
});

test("restores the selected session per account, rejects missing saved sessions and keeps guest selection read-only", async () => {
  const { root, list, bind } = chatDirectory();
  const chat = (accountId: string) => <ChatScreen botAlias="main" accountId={accountId} client={root.client} mobileLayout readOnly />;
  const first = render(chat("alice"));
  await choose(review);
  await screen.findByText("复核历史");
  expect(screen.queryByRole("option", { name: /新建聊天会话/ })).not.toBeInTheDocument();
  first.rerender(chat("bob"));
  await screen.findByText("主会话历史");
  first.unmount();
  root.list.mockClear();
  const second = render(chat("alice"));
  await screen.findByText("复核历史");
  expect(root.list).not.toHaveBeenCalled();
  second.unmount();

  list.mockResolvedValue({ enabled: true, items: [main] });
  bind.mockClear();
  render(chat("alice"));
  await screen.findByText("主会话历史");
  expect(bind).not.toHaveBeenCalled();
  expect(screen.getByRole("combobox", { name: "当前聊天会话" })).toHaveValue("main");
});

test("ignores a late upload completion after switching away from its session", async () => {
  const { root, a } = chatDirectory();
  const upload = deferred<Awaited<ReturnType<WebBotClient["uploadChatAttachment"]>>>();
  const tracked = vi.spyOn(a.client, "uploadChatAttachment").mockReturnValue(upload.promise);
  render(<ChatScreen botAlias="main" client={root.client} />);
  await choose(research);
  await screen.findByText("调查历史");
  fireEvent.change(screen.getByTestId("chat-attachment-input"), { target: { files: [new File(["a"], "A.txt")] } });
  await waitFor(() => expect(tracked).toHaveBeenCalledTimes(1));
  await choose(review);
  await screen.findByText("复核历史");
  expect(tracked.mock.calls[0][3]?.aborted).toBe(true);
  await act(async () => {
    upload.resolve({ filename: "A.txt", size: 1, savedPath: "/tmp/A.txt" });
    await upload.promise;
  });
  expect(screen.queryByText("A.txt")).not.toBeInTheDocument();
});

test("a temporary catalog failure keeps a saved session selected until retry succeeds", async () => {
  const { root, list } = chatDirectory();
  window.localStorage.setItem('tcb.webChatSelection.["alice","main"]', review.id);
  list.mockRejectedValueOnce(new Error("连接中断"));
  render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  await screen.findByText("连接中断");
  expect(root.list).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await screen.findByText("复核历史");
  expect(root.list).not.toHaveBeenCalled();
});

test.each(["remote", "old host"])("keeps the default chat on an unsupported %s", async (host) => {
  const { root, list, bind } = chatDirectory();
  if (host === "remote") list.mockResolvedValue({ enabled: false, items: [main] });
  else list.mockRejectedValue(new WebApiClientError("未找到", { status: 404 }));
  render(<ChatScreen botAlias="main" client={root.client} />);
  await screen.findByText("主会话历史");
  expect(screen.queryByRole("combobox", { name: "当前聊天会话" })).not.toBeInTheDocument();
  expect(bind).not.toHaveBeenCalled();
});

test("a stale directory or history response cannot switch a user back to a previous session", async () => {
  const { root, a, list } = chatDirectory();
  const lateList = deferred<Awaited<ReturnType<typeof root.client.listChatSessions>>>();
  const lateHistory = deferred<Awaited<ReturnType<typeof a.client.listMessages>>>();
  const chat = (visible: boolean) => <ChatScreen botAlias="main" client={root.client} isVisible={visible} />;
  const view = render(chat(true));
  await screen.findByRole("combobox", { name: "当前聊天会话" });
  view.rerender(chat(false));
  list.mockReturnValueOnce(lateList.promise);
  a.list.mockReturnValueOnce(lateHistory.promise);
  view.rerender(chat(true));
  await choose(research);
  await waitFor(() => expect(a.list).toHaveBeenCalled());
  await choose(review);
  await screen.findByText("复核历史");
  await act(async () => {
    lateList.resolve({ enabled: true, items: [main] });
    lateHistory.resolve({ items: [message("迟到的调查历史")] });
    await Promise.all([lateHistory.promise, lateList.promise]);
  });
  expect(screen.getByRole("combobox", { name: "当前聊天会话" })).toHaveValue(review.id);
  expect(screen.queryByText("迟到的调查历史")).not.toBeInTheDocument();
});

test.each(["bot_chat_capacity", "session_busy", "chat_catalog_busy"])("keeps a rejected queued follow-up and its attachment until explicit retry (%s)", async (code) => {
  const { root, a, b } = chatDirectory();
  const attachment = { filename: "notes.txt", savedPath: "/chat/notes.txt", size: 3 };
  vi.spyOn(a.client, "uploadChatAttachment").mockResolvedValue(attachment);
  const view = render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  await choose(research);
  await screen.findByText("调查历史");
  await send("调查任务");
  fireEvent.change(screen.getByTestId("chat-attachment-input"), { target: { files: [new File(["abc"], attachment.filename)] } });
  await screen.findByRole("button", { name: "移除附件 notes.txt" });
  await send("使用笔记");
  await choose(review);
  await screen.findByText("复核历史");
  await send("复核任务");
  await act(async () => { a.finish(); await a.turn.promise; });
  const reject = new WebApiClientError("请稍后重试", { status: 409, code });
  a.send.mockRejectedValueOnce(reject);
  await choose(research);
  await screen.findByRole("button", { name: "重试发送" });
  expect(a.send).toHaveBeenCalledTimes(2);
  const queuedText = a.send.mock.calls[1][1];
  expect(queuedText).toContain("使用笔记");
  expect(queuedText).toContain(attachment.savedPath);

  view.unmount();
  render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  await screen.findByRole("button", { name: "重试发送" });
  await choose(review);
  await screen.findByText("复核历史");
  expect(screen.queryByRole("button", { name: "重试发送" })).not.toBeInTheDocument();
  expect(b.send).toHaveBeenCalledTimes(1);
  await act(async () => { b.finish(); await b.turn.promise; });
  await choose(research);
  const retry = await screen.findByRole("button", { name: "重试发送" });
  expect(a.send).toHaveBeenCalledTimes(2);
  a.send.mockResolvedValueOnce(message("笔记已处理"));
  fireEvent.click(retry);
  await screen.findByText("笔记已处理");
  expect(a.send.mock.calls.map((call) => call[1])).toEqual(["调查任务", queuedText, queuedText]);
  expect(screen.queryByRole("button", { name: "重试发送" })).not.toBeInTheDocument();
  expect(root.send).not.toHaveBeenCalled();
});

test("shows a retryable catalog error on the default chat without interrupting its composer", async () => {
  const { root, list } = chatDirectory();
  list.mockRejectedValueOnce(new WebApiClientError("服务暂时不可用", { status: 503 }));
  render(<ChatScreen botAlias="main" client={root.client} mobileLayout />);
  await screen.findByText("主会话历史");
  await screen.findByText("服务暂时不可用");
  typeDraft("主会话草稿");
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByRole("combobox", { name: "当前聊天会话" })).toHaveValue("main");
  expect(screen.getByPlaceholderText("输入消息")).toHaveValue("主会话草稿");
  expect(screen.queryByText("服务暂时不可用")).not.toBeInTheDocument();
});

test.each(["disabled catalog", "missing route"])("asks before opening the default chat for a saved named session on a legacy host (%s)", async (mode) => {
  const { root, list } = chatDirectory();
  const selection = 'tcb.webChatSelection.["alice","main"]';
  localStorage.setItem(selection, research.id);
  if (mode === "disabled catalog") list.mockResolvedValue({ enabled: false, items: [main] });
  else list.mockRejectedValue(new WebApiClientError("此主机仅支持主会话", { status: 404 }));
  render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  const open = await screen.findByRole("button", { name: "打开主会话" });
  expect(root.list).not.toHaveBeenCalled();
  expect(screen.queryByPlaceholderText("输入消息")).not.toBeInTheDocument();
  expect(localStorage.getItem(selection)).toBe(research.id);
  fireEvent.click(open);
  await screen.findByText("主会话历史");
  expect(localStorage.getItem(selection)).toBeNull();
  expect(root.send).not.toHaveBeenCalled();
});

test("clearing named history identifies the selected shared chat in the confirmation", async () => {
  const { root } = chatDirectory();
  render(<ChatScreen botAlias="main" client={root.client} />);
  await choose(research);
  await screen.findByText("调查历史");
  fireEvent.click(screen.getByRole("button", { name: "历史会话" }));
  fireEvent.click(await screen.findByRole("button", { name: "清空" }));
  const dialog = await screen.findByRole("dialog", { name: "删除全部会话" });
  expect(dialog).toHaveTextContent("将清空「调查」的全部聊天历史。所有有权访问此聊天会话的用户都将失去这些记录。");
  expect(dialog).not.toHaveTextContent("全部历史会话，影响所有可访问该 bot 的用户");
});

test("a queued reader survives switching away before admission and restores its attachment on a quick return", async () => {
  const { root, a, b } = chatDirectory();
  const key = 'tcb.webChatQueue.["alice","main","ses_a","main"]';
  const attachment = { id: "notes", filename: "notes.txt", savedPath: "/chat/notes.txt", size: 3 };
  localStorage.setItem(key, JSON.stringify({ text: "迟到的排队请求", attachments: [attachment] }));
  let rejectAdmission!: () => void;
  a.send.mockImplementationOnce((_alias, _text, _chunk, _status, _trace, options) => new Promise((_resolve, reject) => {
    const signal = options!.signal!;
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    rejectAdmission = () => reject(new WebApiClientError("会话正忙", { code: "bot_chat_capacity" }));
  }));
  render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  await choose(research);
  await waitFor(() => expect(a.send).toHaveBeenCalledTimes(1));
  await choose(review);
  await screen.findByText("复核历史");
  await send("B 独立运行");
  await choose(research);
  await screen.findByText("调查历史");
  expect(a.send.mock.calls[0][5]?.signal?.aborted).toBe(false);
  await act(async () => { rejectAdmission(); });
  const retry = await screen.findByRole("button", { name: "重试发送" });
  expect(retry).toBeEnabled();
  expect(JSON.parse(localStorage.getItem(key)!)).toMatchObject({
    text: "迟到的排队请求", attachments: [attachment], rejection: "bot_chat_capacity",
  });
  expect(a.send).toHaveBeenCalledTimes(1);
  a.send.mockResolvedValueOnce(message("已完成重试"));
  fireEvent.click(retry);
  await screen.findByText("已完成重试");
  expect(a.send.mock.calls.map((call) => call[1])).toEqual([a.send.mock.calls[0][1], a.send.mock.calls[0][1]]);
  expect(a.send.mock.calls[1][1]).toContain(attachment.savedPath);
  expect(b.send.mock.calls.map((call) => call[1])).toEqual(["B 独立运行"]);
});

test.each(["accepted", "no response"])("releases a detached queued reader with %s and never replays an uncertain send", async (outcome) => {
  const { root, a } = chatDirectory();
  const key = 'tcb.webChatQueue.["alice","main","ses_a","main"]';
  localStorage.setItem(key, JSON.stringify({ text: "待确认", attachments: [] }));
  let admit!: () => void;
  a.send.mockImplementationOnce((_alias, _text, _chunk, onStatus, _trace, options) => new Promise((_resolve, reject) => {
    options!.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    admit = () => onStatus?.({ turnId: "accepted-turn" });
  }));
  render(<ChatScreen botAlias="main" accountId="alice" client={root.client} />);
  await choose(research);
  await waitFor(() => expect(a.send).toHaveBeenCalledTimes(1));
  const signal = a.send.mock.calls[0][5]?.signal;
  const chooser = screen.getByRole("combobox", { name: "当前聊天会话" });

  vi.useFakeTimers();
  try {
    await act(async () => { fireEvent.change(chooser, { target: { value: review.id } }); });
    expect(signal?.aborted).toBe(false);
    await act(async () => {
      if (outcome === "accepted") admit();
      else await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(signal?.aborted).toBe(true);
  } finally {
    vi.useRealTimers();
  }
  await choose(research);
  await screen.findByText("调查历史");
  expect(screen.queryByRole("button", { name: "重试发送" })).not.toBeInTheDocument();
  if (outcome === "accepted") {
    expect(localStorage.getItem(key)).toBeNull();
  } else {
    expect(screen.getByText("发送状态待确认，请先查看聊天历史")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放回输入框" }));
    expect(screen.getByPlaceholderText("输入消息")).toHaveValue("待确认");
  }
  expect(a.send).toHaveBeenCalledTimes(1);
});
