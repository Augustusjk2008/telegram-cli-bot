import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { NotificationCenter } from "../app/NotificationCenter";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  NotificationSubscription,
  NotificationSubscriptionOptions,
  WebNotificationEvent,
} from "../services/types";

class NotificationClient extends MockWebBotClient {
  onEvent: ((event: WebNotificationEvent) => void) | null = null;

  subscribeNotifications(
    onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    this.onEvent = onEvent;
    options?.onStatus?.("open");
    return {
      close: vi.fn(),
      sendPresenceUpdate: vi.fn(),
    };
  }

  emit(event: WebNotificationEvent) {
    this.onEvent?.(event);
  }
}

function completedEvent(botAlias: string, dedupeKey: string): WebNotificationEvent {
  return {
    type: "chat_completed",
    id: `event-${dedupeKey}`,
    dedupeKey,
    botAlias,
    agentId: "main",
    conversationId: "conversation-1",
    status: "success",
    title: "聊天已完成",
    preview: "回复完成",
    completedAt: "2026-08-27T01:10:05Z",
    terminalAt: "2026-08-27T01:10:00Z",
  };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

test("actively acknowledges a completion for the currently visible bot", async () => {
  const client = new NotificationClient();
  const onUnreadBot = vi.fn();
  const onReadBot = vi.fn();
  render(
    <NotificationCenter
      client={client}
      enabled
      currentBotAlias="main"
      visibleChatBotAlias="main"
      onUnreadBot={onUnreadBot}
      onReadBot={onReadBot}
    />,
  );
  await waitFor(() => expect(client.onEvent).toBeTruthy());

  act(() => client.emit(completedEvent("main", "visible-main")));

  expect(onReadBot).toHaveBeenCalledWith("main", "2026-08-27T01:10:00Z");
  expect(onUnreadBot).not.toHaveBeenCalled();
});

test("marks a completion for another bot unread", async () => {
  const client = new NotificationClient();
  const onUnreadBot = vi.fn();
  const onReadBot = vi.fn();
  render(
    <NotificationCenter
      client={client}
      enabled
      currentBotAlias="main"
      visibleChatBotAlias="main"
      onUnreadBot={onUnreadBot}
      onReadBot={onReadBot}
    />,
  );
  await waitFor(() => expect(client.onEvent).toBeTruthy());

  act(() => client.emit(completedEvent("worker", "hidden-worker")));

  expect(onUnreadBot).toHaveBeenCalledWith("worker", "2026-08-27T01:10:00Z");
  expect(onReadBot).not.toHaveBeenCalled();
});
