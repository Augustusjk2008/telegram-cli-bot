import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { BotOverview, ChatMessage, ChatSyncEvent, ConversationListResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

/** A client whose `chat_sync` channel is driven by the test instead of a socket. */
function createPushClient(overrides: Partial<WebBotClient> = {}, initiallyActive = true) {
  const listeners = new Set<(event: ChatSyncEvent) => void>();
  let active = initiallyActive;
  const getBotOverview = vi.fn<WebBotClient["getBotOverview"]>(async (): Promise<BotOverview> => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
  }));
  const listMessageDelta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({
    reset: false,
    revision: 3,
    nextCursor: "",
    items: [],
  }));
  const client: WebBotClient = Object.assign(new MockWebBotClient(), {
    getBotOverview,
    listMessages: async () => ({ items: [], revision: 3 }),
    listMessageDelta,
    listConversations: async (): Promise<ConversationListResult> => ({ activeConversationId: "", items: [] }),
    subscribeChatSync: (listener: (event: ChatSyncEvent) => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    isChatSyncActive: () => active,
    ...overrides,
  });
  const emit = (event: ChatSyncEvent) => {
    if (event.type === "status") {
      active = event.active;
    }
    listeners.forEach((listener) => listener(event));
  };
  const hint = (reason: string, target: { botAlias?: string; agentId?: string } = {}) => emit({
    type: "change",
    botAlias: target.botAlias ?? "main",
    agentId: target.agentId ?? "main",
    reason,
  });
  return { client, emit, hint, getBotOverview, listMessageDelta };
}

async function renderIdleChat(client: WebBotClient) {
  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("暂无消息，开始聊天吧");
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

test("a chat_sync hint for this session syncs at once and other sessions are ignored", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { client, hint, getBotOverview, listMessageDelta } = createPushClient();
  await renderIdleChat(client);
  const loaded = { overview: getBotOverview.mock.calls.length, delta: listMessageDelta.mock.calls.length };

  await act(async () => {
    hint("turn_started", { botAlias: "other" });
    hint("turn_started", { agentId: "worker" });
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(loaded.overview);

  await act(async () => {
    hint("turn_started");
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(loaded.overview + 1);
  expect(listMessageDelta).toHaveBeenCalledTimes(loaded.delta + 1);
});

test("idle polling stretches to the fallback interval only while hints are active", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { client, emit, getBotOverview } = createPushClient();
  await renderIdleChat(client);
  const loaded = getBotOverview.mock.calls.length;

  // The first refresh after load is unchanged; afterwards the timer is only a fallback.
  await act(async () => vi.advanceTimersByTimeAsync(5_000));
  expect(getBotOverview).toHaveBeenCalledTimes(loaded + 1);
  await act(async () => vi.advanceTimersByTimeAsync(50_000));
  expect(getBotOverview).toHaveBeenCalledTimes(loaded + 1);
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(getBotOverview).toHaveBeenCalledTimes(loaded + 2);

  // Losing the socket restores the regular 10 second cadence.
  await act(async () => {
    emit({ type: "status", active: false });
    await vi.advanceTimersByTimeAsync(5_000);
  });
  const afterLoss = getBotOverview.mock.calls.length;
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(getBotOverview).toHaveBeenCalledTimes(afterLoss + 2);

  // Reconnecting catches up immediately, because hints sent meanwhile were lost.
  const beforeReconnect = getBotOverview.mock.calls.length;
  await act(async () => {
    emit({ type: "status", active: true });
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(beforeReconnect + 1);
});

test("a turn watched without the stream is refreshed by hints with a slow fallback timer", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const running: ChatMessage = {
    id: "assistant-running",
    role: "assistant",
    text: "正在处理",
    createdAt: "2026-08-08T00:00:00Z",
    state: "streaming",
  };
  const { client, hint, getBotOverview } = createPushClient({
    listMessages: async () => ({ items: [running], revision: 3 }),
  });
  getBotOverview.mockImplementation(async () => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: true,
  }));
  render(<ChatScreen botAlias="main" client={client} />);
  await waitFor(() => expect(document.querySelector('[data-message-id="assistant-running"]')).not.toBeNull());
  const loaded = getBotOverview.mock.calls.length;

  // Without hints this turn was polled every second.
  await act(async () => vi.advanceTimersByTimeAsync(4_000));
  expect(getBotOverview).toHaveBeenCalledTimes(loaded);
  // The fallback timer still refreshes it when no hint arrives.
  await act(async () => vi.advanceTimersByTimeAsync(1_100));
  const afterFallback = getBotOverview.mock.calls.length;
  expect(afterFallback).toBeGreaterThan(loaded);

  await act(async () => {
    hint("progress");
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(afterFallback + 1);
});

test("without the chat_sync feature a watched turn keeps the one second poll", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { client, getBotOverview } = createPushClient({
    listMessages: async () => ({
      items: [{ id: "assistant-running", role: "assistant", text: "正在处理", createdAt: "2026-08-08T00:00:00Z", state: "streaming" }],
      revision: 3,
    }),
  }, false);
  getBotOverview.mockImplementation(async () => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: true,
  }));
  render(<ChatScreen botAlias="main" client={client} />);
  await waitFor(() => expect(document.querySelector('[data-message-id="assistant-running"]')).not.toBeNull());
  const loaded = getBotOverview.mock.calls.length;

  await act(async () => vi.advanceTimersByTimeAsync(3_100));
  expect(getBotOverview.mock.calls.length).toBeGreaterThanOrEqual(loaded + 3);
});

test("a stalled stream backs off its recovery checks and a hint triggers one immediately", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((_botAlias, _text, _onChunk, onStatus) => {
    onStatus?.({ turnId: "turn-stalled", assistantMessageId: "assistant-stalled" });
    return new Promise<ChatMessage>(() => undefined);
  });
  const { client, hint, getBotOverview } = createPushClient({ sendMessage }, false);
  getBotOverview.mockImplementation(async () => ({
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: sendMessage.mock.calls.length > 0,
  }));
  await renderIdleChat(client);
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "慢链路" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  const sent = getBotOverview.mock.calls.length;

  // First check after 2.5 s as before, then 5 s and 10 s apart (the cap without hints).
  await act(async () => vi.advanceTimersByTimeAsync(2_600));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 1);
  await act(async () => vi.advanceTimersByTimeAsync(2_600));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 1);
  await act(async () => vi.advanceTimersByTimeAsync(2_500));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 2);
  await act(async () => vi.advanceTimersByTimeAsync(9_500));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 2);
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 3);
  await act(async () => vi.advanceTimersByTimeAsync(9_500));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 3);
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 4);

  // While stalled, progress hints are acted on no more often than the watchdog used to check ...
  await act(async () => {
    hint("progress");
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 4);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2_500);
    hint("progress");
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 5);
  // ... while the end of the turn is checked at once.
  await act(async () => {
    hint("turn_finished");
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 6);

  // Checks asked for by hints do not lengthen the timer fallback: it is still 10 s away, not more.
  await act(async () => vi.advanceTimersByTimeAsync(9_500));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 6);
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(getBotOverview).toHaveBeenCalledTimes(sent + 7);
});

test("a live stream ignores hints about its own turn", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let finish!: (message: ChatMessage) => void;
  const sendMessage = vi.fn<WebBotClient["sendMessage"]>((_botAlias, _text, _onChunk, onStatus) => {
    onStatus?.({ turnId: "turn-live", assistantMessageId: "assistant-live" });
    return new Promise<ChatMessage>((resolve) => {
      finish = resolve;
    });
  });
  const { client, hint, getBotOverview } = createPushClient({ sendMessage });
  await renderIdleChat(client);
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "你好" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
  const sent = getBotOverview.mock.calls.length;

  await act(async () => {
    hint("turn_started");
    hint("progress");
    await vi.advanceTimersByTimeAsync(100);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(sent);

  await act(async () => {
    finish({ id: "assistant-live", turnId: "turn-live", role: "assistant", text: "完成", createdAt: "2026-08-08T00:00:00Z", state: "done" });
    await vi.advanceTimersByTimeAsync(50);
  });
  await screen.findByText("完成");
  const finished = getBotOverview.mock.calls.length;
  // The hint about the turn this page just streamed carries nothing new.
  await act(async () => {
    hint("turn_finished");
    await vi.advanceTimersByTimeAsync(100);
  });
  expect(getBotOverview).toHaveBeenCalledTimes(finished);
});

class FakeNotificationSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: FakeNotificationSocket[] = [];
  readyState = FakeNotificationSocket.CONNECTING;
  sent: string[] = [];

  constructor(public url: string) {
    super();
    FakeNotificationSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeNotificationSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }

  open() {
    this.readyState = FakeNotificationSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  receive(payload: unknown) {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
}

test("the notifications socket turns hello features and chat_sync messages into sync events", () => {
  FakeNotificationSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeNotificationSocket);
  const client = new RealWebBotClient();
  const syncEvents: ChatSyncEvent[] = [];
  const notifications: Array<{ type: string }> = [];
  const unsubscribe = client.subscribeChatSync((event) => syncEvents.push(event));
  const subscription = client.subscribeNotifications((event) => notifications.push(event));
  const socket = FakeNotificationSocket.instances[0];
  socket.open();

  // A host without the feature leaves chats on their regular polling.
  socket.receive({ type: "hello", accountId: "alice" });
  expect(client.isChatSyncActive()).toBe(false);
  expect(syncEvents).toEqual([]);

  socket.receive({ type: "hello", accountId: "alice", features: ["chat_sync"] });
  expect(client.isChatSyncActive()).toBe(true);
  socket.receive({ type: "chat_sync", botAlias: "main", agentId: "main", reason: "turn_finished" });
  socket.receive({ type: "chat_completed", id: "ntf_1", dedupeKey: "k", botAlias: "main" });
  expect(syncEvents).toEqual([
    { type: "status", active: true },
    { type: "change", botAlias: "main", agentId: "main", reason: "turn_finished" },
  ]);
  // Hints stay out of the notification handler; completion notifications still reach it.
  expect(notifications.map((event) => event.type)).toEqual(["hello", "hello", "chat_completed"]);

  socket.close();
  expect(client.isChatSyncActive()).toBe(false);
  expect(syncEvents[syncEvents.length - 1]).toEqual({ type: "status", active: false });

  unsubscribe();
  subscription.close();
});
