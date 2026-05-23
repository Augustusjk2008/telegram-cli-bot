import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useNotificationPresence } from "../app/useNotificationPresence";
import type {
  NotificationPresenceUpdate,
  NotificationSubscription,
  NotificationSubscriptionOptions,
  WebNotificationEvent,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { CHAT_COMPLETION_WEB_NOTIFICATION_KEY } from "../utils/chatNotificationEvents";

class PresenceClient {
  updates: NotificationPresenceUpdate[] = [];
  closed = false;
  onStatus?: NotificationSubscriptionOptions["onStatus"];

  subscribeNotifications(
    _onEvent: (event: WebNotificationEvent) => void,
    options?: NotificationSubscriptionOptions,
  ): NotificationSubscription {
    this.onStatus = options?.onStatus;
    options?.onStatus?.("open");
    return {
      close: () => {
        this.closed = true;
      },
      sendPresenceUpdate: (presence) => {
        this.updates.push(presence);
      },
    };
  }
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("Notification", { permission: "default" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("presence subscribes and reports visibility permission settings and bot alias", () => {
  localStorage.setItem(CHAT_COMPLETION_WEB_NOTIFICATION_KEY, "false");
  const client = new PresenceClient();

  const { result, rerender, unmount } = renderHook(
    ({ botAlias }) => useNotificationPresence({
      client: client as unknown as WebBotClient,
      enabled: true,
      currentBotAlias: botAlias,
      onEvent: vi.fn(),
    }),
    { initialProps: { botAlias: "main" } },
  );

  expect(result.current.permission).toBe("default");
  expect(result.current.subscribed).toBe(true);
  expect(client.updates.at(-1)).toEqual(expect.objectContaining({
    currentBotAlias: "main",
    webNotificationsEnabled: false,
    permission: "default",
  }));

  rerender({ botAlias: "team2" });

  expect(client.updates.at(-1)).toEqual(expect.objectContaining({
    currentBotAlias: "team2",
  }));

  unmount();
  expect(client.closed).toBe(true);
});

test("presence updates after focus and notification setting changes without reconnecting", () => {
  const client = new PresenceClient();
  const subscribeSpy = vi.spyOn(client, "subscribeNotifications");

  renderHook(() => useNotificationPresence({
    client: client as unknown as WebBotClient,
    enabled: true,
    currentBotAlias: "main",
    onEvent: vi.fn(),
  }));

  act(() => {
    localStorage.setItem(CHAT_COMPLETION_WEB_NOTIFICATION_KEY, "false");
    window.dispatchEvent(new Event("chat-notification-settings-changed"));
    window.dispatchEvent(new Event("focus"));
  });

  expect(subscribeSpy).toHaveBeenCalledTimes(1);
  expect(client.updates.length).toBeGreaterThanOrEqual(3);
  expect(client.updates.at(-1)).toEqual(expect.objectContaining({
    currentBotAlias: "main",
    webNotificationsEnabled: false,
  }));
});
