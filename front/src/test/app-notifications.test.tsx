import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { NotificationCenter } from "../app/NotificationCenter";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type {
  NotificationPresenceUpdate,
  NotificationSubscription,
  NotificationSubscriptionOptions,
  WebNotificationEvent,
} from "../services/types";
import {
  CHAT_COMPLETION_WEB_NOTIFICATION_KEY,
  reserveChatNotificationDedupe,
} from "../utils/chatNotificationEvents";

class NotificationClient extends MockWebBotClient {
  onEvent: ((event: WebNotificationEvent) => void) | null = null;
  presenceUpdates: NotificationPresenceUpdate[] = [];
  close = vi.fn();

  subscribeNotifications(
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    this.onEvent = onEvent;
    options?.onStatus?.("open");
    return {
      close: this.close,
      sendPresenceUpdate: (presence) => {
        this.presenceUpdates.push(presence);
      },
    };
  }

  emit(event: WebNotificationEvent) {
    this.onEvent?.(event);
  }
}

function chatDoneEvent(overrides: Partial<WebNotificationEvent> = {}) {
  return {
    type: "chat_completed",
    id: `evt-${Math.random()}`,
    dedupeKey: `dedupe-${Math.random()}`,
    botAlias: "main",
    agentId: "agent1",
    conversationId: "conv1",
    status: "success",
    title: "聊天已完成",
    preview: "后台回复完成",
    completedAt: "2026-05-23T12:00:00+08:00",
    url: "/chat/main",
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("Notification", vi.fn().mockImplementation(function MockNotification(this: { onclick?: () => void }) {
    return this;
  }));
  Object.assign(Notification, {
    permission: "granted",
    requestPermission: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

test("visible chat completion shows in-app toast and marks bot unread", async () => {
  const client = new NotificationClient();
  const onUnreadBot = vi.fn();

  render(<NotificationCenter client={client} enabled currentBotAlias="main" onUnreadBot={onUnreadBot} />);

  await waitFor(() => expect(client.onEvent).toBeTruthy());
  act(() => {
    client.emit(chatDoneEvent({ dedupeKey: "visible-dedupe" }));
  });

  expect(await screen.findByRole("status")).toHaveTextContent("聊天已完成");
  expect(screen.getByText("后台回复完成")).toBeInTheDocument();
  expect(Notification).not.toHaveBeenCalled();
  expect(onUnreadBot).toHaveBeenCalledWith("main");
});

test("hidden chat completion uses browser notification when permission is granted", async () => {
  const client = new NotificationClient();
  const originalVisibility = Object.getOwnPropertyDescriptor(Document.prototype, "visibilityState");
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "hidden",
  });

  try {
    render(<NotificationCenter client={client} enabled currentBotAlias="team2" />);
    await waitFor(() => expect(client.onEvent).toBeTruthy());

    act(() => {
      client.emit(chatDoneEvent({ dedupeKey: "hidden-dedupe", botAlias: "team2" }));
    });

    expect(Notification).toHaveBeenCalledWith("聊天已完成", expect.objectContaining({
      body: expect.stringContaining("后台回复完成"),
      tag: "hidden-dedupe",
    }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  } finally {
    if (originalVisibility) {
      Object.defineProperty(document, "visibilityState", originalVisibility);
    }
  }
});

test("permission denied does not throw and only records unread state", async () => {
  Object.assign(Notification, { permission: "denied" });
  const client = new NotificationClient();
  const originalVisibility = Object.getOwnPropertyDescriptor(Document.prototype, "visibilityState");
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "hidden",
  });

  try {
    render(<NotificationCenter client={client} enabled currentBotAlias="main" />);
    await waitFor(() => expect(client.onEvent).toBeTruthy());

    act(() => {
      client.emit(chatDoneEvent({ dedupeKey: "denied-dedupe" }));
    });

    expect(Notification).not.toHaveBeenCalled();
    expect(await screen.findByText("通知 1")).toBeInTheDocument();
  } finally {
    if (originalVisibility) {
      Object.defineProperty(document, "visibilityState", originalVisibility);
    }
  }
});

test("dedupe suppresses repeated notification keys across deliveries", async () => {
  const client = new NotificationClient();

  render(<NotificationCenter client={client} enabled currentBotAlias="main" />);
  await waitFor(() => expect(client.onEvent).toBeTruthy());

  act(() => {
    client.emit(chatDoneEvent({ id: "evt-1", dedupeKey: "same-key", preview: "第一次" }));
    client.emit(chatDoneEvent({ id: "evt-2", dedupeKey: "same-key", preview: "第二次" }));
  });

  expect(await screen.findByText("第一次")).toBeInTheDocument();
  expect(screen.queryByText("第二次")).not.toBeInTheDocument();
});

test("dedupe utility returns false for stored active key", () => {
  expect(reserveChatNotificationDedupe("utility-key", 1000, 1000)).toBe(true);
  expect(reserveChatNotificationDedupe("utility-key", 1500, 1000)).toBe(false);
  expect(reserveChatNotificationDedupe("utility-key", 2501, 1000)).toBe(true);
});

test("real client notification socket builds authenticated ws url and sends heartbeat presence", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      data: {
        token: "web_sess_notify",
        username: "alice",
        role: "member",
        capabilities: ["view_chat_history"],
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);

  const sockets: MockSocket[] = [];
  class MockSocket {
    static OPEN = 1;
    static CLOSED = 3;
    url: string;
    readyState = MockSocket.OPEN;
    listeners = new Map<string, Array<(event: { data?: string }) => void>>();
    sent: string[] = [];

    constructor(url: string) {
      this.url = url;
      sockets.push(this);
    }

    addEventListener(type: string, listener: (event: { data?: string }) => void) {
      const current = this.listeners.get(type) || [];
      current.push(listener);
      this.listeners.set(type, current);
    }

    send(data: string) {
      this.sent.push(data);
    }

    close() {
      this.readyState = MockSocket.CLOSED;
    }

    emit(type: string, event: { data?: string } = {}) {
      this.listeners.get(type)?.forEach((listener) => listener(event));
    }
  }
  vi.stubGlobal("WebSocket", MockSocket);
  const originalLocation = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { protocol: "https:", host: "example.test" },
  });

  try {
    const client = new RealWebBotClient();
    await client.loginGuest();
    const events: WebNotificationEvent[] = [];
    const subscription = client.subscribeNotifications((event) => events.push(event));

    sockets[0].emit("open");
    subscription.sendPresenceUpdate({
      visible: false,
      focused: false,
      permission: "granted",
      webNotificationsEnabled: true,
      currentBotAlias: "main",
    });
    sockets[0].emit("message", { data: JSON.stringify(chatDoneEvent({ id: "ws-event" })) });

    await vi.advanceTimersByTimeAsync(25000);

    expect(sockets[0].url).toBe("wss://example.test/api/notifications/ws?token=web_sess_notify");
    expect(sockets[0].sent.map((item) => JSON.parse(item))).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "hello" }),
      expect.objectContaining({ type: "presence_update", currentBotAlias: "main" }),
      expect.objectContaining({ type: "heartbeat" }),
    ]));
    expect(events[0]).toEqual(expect.objectContaining({ id: "ws-event", type: "chat_completed" }));

    subscription.close();
  } finally {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
    vi.useRealTimers();
  }
});

test("real client notification socket reconnects after close", async () => {
  vi.useFakeTimers();
  const sockets: MockReconnectSocket[] = [];
  class MockReconnectSocket {
    static OPEN = 1;
    static CLOSED = 3;
    url: string;
    readyState = MockReconnectSocket.OPEN;
    listeners = new Map<string, Array<() => void>>();

    constructor(url: string) {
      this.url = url;
      sockets.push(this);
    }

    addEventListener(type: string, listener: () => void) {
      const current = this.listeners.get(type) || [];
      current.push(listener);
      this.listeners.set(type, current);
    }

    send() {}
    close() {
      this.readyState = MockReconnectSocket.CLOSED;
    }
    emit(type: string) {
      this.listeners.get(type)?.forEach((listener) => listener());
    }
  }
  vi.stubGlobal("WebSocket", MockReconnectSocket);

  try {
    const statuses: string[] = [];
    const client = new RealWebBotClient();
    client.subscribeNotifications(vi.fn(), { onStatus: (status) => statuses.push(status) });

    sockets[0].emit("close");
    await vi.advanceTimersByTimeAsync(1000);

    expect(sockets).toHaveLength(2);
    expect(statuses).toContain("reconnecting");
  } finally {
    vi.useRealTimers();
  }
});
