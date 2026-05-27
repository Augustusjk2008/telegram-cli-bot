import { useCallback, useEffect, useMemo, useState } from "react";
import type { BrowserNotificationPermission, ChatCompletedNotificationEvent, WebNotificationEvent } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { useNotificationPresence } from "./useNotificationPresence";
import {
  formatChatNotificationBody,
  getBrowserNotificationPermission,
  isChatCompletedNotificationEvent,
  readChatCompletionWebNotificationEnabled,
  reserveChatNotificationDedupe,
} from "../utils/chatNotificationEvents";

type Props = {
  client: WebBotClient;
  enabled: boolean;
  currentBotAlias?: string | null;
  visibleChatBotAlias?: string | null;
  onUnreadBot?: (alias: string) => void;
};

type ToastState = {
  id: string;
  title: string;
  body: string;
};

function pageIsVisible() {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

function browserNotificationsEnabled(permission: BrowserNotificationPermission) {
  return permission === "granted" && readChatCompletionWebNotificationEnabled();
}

function showBrowserNotification(event: ChatCompletedNotificationEvent) {
  try {
    const notification = new Notification(event.title || "聊天已完成", {
      body: formatChatNotificationBody(event),
      tag: event.dedupeKey,
    });
    if (event.url) {
      notification.onclick = () => {
        try {
          window.focus();
          window.location.assign(event.url || "/");
        } catch {
          // ignore click navigation failures
        }
      };
    }
  } catch {
    // Permission may be revoked between checks; in-app unread state still updates.
  }
}

export function NotificationCenter({ client, enabled, currentBotAlias, visibleChatBotAlias, onUnreadBot }: Props) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);

  const handleEvent = useCallback((event: WebNotificationEvent) => {
    if (!isChatCompletedNotificationEvent(event)) {
      return;
    }
    if (!reserveChatNotificationDedupe(event.dedupeKey || event.id)) {
      return;
    }

    const chatVisibleForEvent = pageIsVisible() && visibleChatBotAlias === event.botAlias;
    if (!chatVisibleForEvent) {
      onUnreadBot?.(event.botAlias);
      setUnreadCount((count) => count + 1);
    }

    if (pageIsVisible()) {
      setToast({
        id: event.id,
        title: event.title || "聊天已完成",
        body: event.preview || `${event.botAlias} 已完成回复`,
      });
      return;
    }

    const permission = getBrowserNotificationPermission();
    if (browserNotificationsEnabled(permission)) {
      showBrowserNotification(event);
    }
  }, [onUnreadBot, visibleChatBotAlias]);

  useNotificationPresence({
    client,
    enabled,
    currentBotAlias,
    onEvent: handleEvent,
  });

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const unreadText = useMemo(() => (unreadCount > 0 ? `通知 ${unreadCount}` : ""), [unreadCount]);

  if (!enabled) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[80] flex max-w-sm flex-col items-end gap-2">
      <div aria-live="polite" className="sr-only">{unreadText}</div>
      {toast ? (
        <div
          role="status"
          className="pointer-events-auto w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--text)] shadow-[var(--shadow-card)]"
        >
          <div className="font-medium">{toast.title}</div>
          {toast.body ? <div className="mt-1 line-clamp-3 text-[var(--muted)]">{toast.body}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
